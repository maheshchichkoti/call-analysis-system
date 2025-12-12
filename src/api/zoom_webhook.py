# src/api/zoom_webhook.py
"""
Zoom Phone Webhook Handler — Hardened Production Version
"""

import hmac
import hashlib
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel

from ..config import settings
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Zoom Webhook"])

# In-memory cache to prevent duplicate event processing
RECENT_EVENTS = {}
EVENT_TTL_SECONDS = 300  # Zoom retries events for several minutes


# ---------------------------------------------------------
# Signature Verification
# ---------------------------------------------------------
def verify_signature(body: bytes, signature: str, timestamp: str) -> bool:
    secret = settings.ZOOM_WEBHOOK_SECRET_TOKEN
    if not secret:
        logger.warning("Missing webhook secret — skipping verification")
        return True

    # Log for debugging
    logger.info("Verifying signature...")
    logger.info(f"  Timestamp from header: {timestamp}")
    logger.info(f"  Signature from header: {signature[:30]}...")
    logger.info(f"  Secret configured: {secret[:8]}...")

    # Replay attack protection (be lenient - allow up to 5 minutes)
    try:
        ts = int(timestamp)
        # Zoom timestamp could be in seconds or milliseconds
        if ts > 10000000000:  # If > 10 billion, it's milliseconds
            ts = ts // 1000

        time_diff = abs(time.time() - ts)
        logger.info(f"  Time difference: {time_diff:.1f} seconds")

        if time_diff > 600:  # 10 minutes tolerance
            logger.warning(f"Webhook timestamp too old ({time_diff:.0f}s)")
            return False
    except ValueError:
        logger.warning("Invalid timestamp header")
        return False

    # Calculate expected signature
    body_str = body.decode("utf-8")
    message = f"v0:{timestamp}:{body_str}"
    expected_hash = hmac.new(
        secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    expected = f"v0={expected_hash}"

    logger.info(f"  Expected signature: {expected[:30]}...")

    # Compare
    is_valid = hmac.compare_digest(expected, signature)
    if not is_valid:
        logger.warning("Signature mismatch!")
        # In development, log but don't reject
        if settings.ENVIRONMENT == "development":
            logger.warning(
                "Development mode - allowing request despite signature mismatch"
            )
            return True

    return is_valid


# ---------------------------------------------------------
# Pydantic Model for Safety
# ---------------------------------------------------------
class RecordingCompletedPayload(BaseModel):
    event: str
    payload: dict


# ---------------------------------------------------------
# WEBHOOK ENTRYPOINT
# ---------------------------------------------------------
@router.post("/zoom")
async def zoom_webhook(
    request: Request,
    x_zm_signature: Optional[str] = Header(None),
    x_zm_request_timestamp: Optional[str] = Header(None),
):
    # Get raw body for logging
    body = await request.body()

    # Log EVERYTHING for debugging
    logger.info("=== ZOOM WEBHOOK RECEIVED ===")
    logger.info(f"Raw body: {body[:500]}")
    logger.info(f"Signature header: {x_zm_signature}")
    logger.info(f"Timestamp header: {x_zm_request_timestamp}")

    # Parse JSON - handle any format
    try:
        data = await request.json()
        logger.info(f"Parsed JSON: {data}")
    except Exception as e:
        logger.error(f"JSON parse error: {e}")
        return {"status": "error", "message": "Invalid JSON"}

    event_type = data.get("event", "")
    payload = data.get("payload", {})

    logger.info(f"Event type: {event_type}")

    # URL validation — Zoom handshake (NO signature required)
    if event_type == "endpoint.url_validation":
        logger.info("Processing URL validation...")
        return handle_url_validation(payload)

    # For all other events, verify signature if configured
    if settings.REQUIRE_ZOOM_SIGNATURE:
        if not (x_zm_signature and x_zm_request_timestamp):
            logger.warning("Missing signature headers")
            raise HTTPException(401, "Missing Zoom signature headers")

        if not verify_signature(body, x_zm_signature, x_zm_request_timestamp):
            logger.warning("Invalid signature")
            raise HTTPException(401, "Invalid Zoom signature")

    logger.info(f"Processing event: {event_type}")

    # Duplicate protection
    event_id = f"{x_zm_request_timestamp}:{hash(body)}"
    clean_old_events()

    if event_id in RECENT_EVENTS:
        logger.info("Duplicate event — ignoring")
        return {"status": "duplicate"}

    RECENT_EVENTS[event_id] = time.time()

    # Process the event
    if event_type == "phone.recording_completed":
        return await handle_recording_completed(payload)

    logger.info(f"Unknown event type: {event_type}")
    return {"status": "ignored", "event": event_type}


# ---------------------------------------------------------
def clean_old_events():
    """Remove cached event IDs older than TTL."""
    cutoff = time.time() - EVENT_TTL_SECONDS
    expired = [k for k, ts in RECENT_EVENTS.items() if ts < cutoff]
    for k in expired:
        RECENT_EVENTS.pop(k, None)


# ---------------------------------------------------------
def handle_url_validation(payload: dict):
    """Zoom initial challenge."""
    plain = payload.get("plainToken", "")
    secret = settings.ZOOM_WEBHOOK_SECRET_TOKEN or "default"
    encrypted = hmac.new(secret.encode(), plain.encode(), hashlib.sha256).hexdigest()

    return {"plainToken": plain, "encryptedToken": encrypted}


# ---------------------------------------------------------
# Recording Completed Handler
# ---------------------------------------------------------
async def handle_recording_completed(payload: dict):
    try:
        obj = payload.get("object", {})

        # Zoom sends recordings as an array
        recordings = obj.get("recordings", [])

        if not recordings:
            logger.warning("No recordings in payload")
            return {"status": "error", "message": "No recordings found"}

        # Process each recording
        results = []
        for rec in recordings:
            call_id = rec.get("call_id") or rec.get("id") or rec.get("call_log_id")
            if not call_id:
                call_id = f"zoom_{time.time_ns()}"
                logger.warning(f"Missing call_id — generated: {call_id}")

            # Extract download URL
            recording_url = rec.get("download_url")

            # Agent info from owner or callee
            owner = rec.get("owner", {})
            agent_name = owner.get("name") or rec.get("callee_name") or "Unknown"

            # Customer info from caller
            customer_number = (
                rec.get("caller_number") or rec.get("caller_name") or "Unknown"
            )

            start_time = rec.get("date_time")
            duration = rec.get("duration")

            logger.info(
                f"Processing recording: call_id={call_id}, agent={agent_name}, duration={duration}s"
            )

            # Prevent duplicate processing
            if CallRecordsDB.get_call_by_call_id(call_id):
                logger.info(f"Call {call_id} already exists — skipping")
                results.append({"call_id": call_id, "status": "duplicate"})
                continue

            record_id = CallRecordsDB.insert_call_record(
                {
                    "call_id": call_id,
                    "agent_name": agent_name,
                    "customer_number": customer_number,
                    "recording_url": recording_url,
                    "start_time": start_time,
                    "duration_seconds": duration,
                }
            )

            logger.info(f"Call record created: {record_id}")
            results.append(
                {"call_id": call_id, "record_id": record_id, "status": "success"}
            )

        return {"status": "success", "recordings": results}

    except DatabaseError as e:
        if "duplicate" in str(e).lower():
            return {"status": "duplicate"}
        raise HTTPException(500, f"Database error: {e}")

    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        raise HTTPException(500, str(e))

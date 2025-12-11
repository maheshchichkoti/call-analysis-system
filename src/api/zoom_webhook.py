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
from pydantic import BaseModel, ValidationError

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

    # Replay attack protection
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > 300:
            logger.warning("Webhook timestamp too old — possible replay attack")
            return False
    except ValueError:
        logger.warning("Invalid timestamp header")
        return False

    message = f"v0:{timestamp}:{body.decode('utf-8')}"
    expected_hash = hmac.new(
        secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()

    expected = f"v0={expected_hash}"

    return hmac.compare_digest(expected, signature)


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
    body = await request.body()

    # Parse JSON safely
    try:
        parsed = RecordingCompletedPayload(**(await request.json()))
    except ValidationError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(400, "Invalid webhook payload")

    event_type = parsed.event
    payload = parsed.payload

    # URL validation — Zoom handshake
    if event_type == "endpoint.url_validation":
        return handle_url_validation(payload)

    # Verify signature for real events
    if settings.REQUIRE_ZOOM_SIGNATURE:
        if not (x_zm_signature and x_zm_request_timestamp):
            raise HTTPException(401, "Missing Zoom signature headers")

        if not verify_signature(body, x_zm_signature, x_zm_request_timestamp):
            raise HTTPException(401, "Invalid Zoom signature")

    logger.info(f"Received Zoom event: {event_type}")

    # Duplicate protection (check BEFORE adding!)
    event_id = f"{x_zm_request_timestamp}:{hash(body)}"
    clean_old_events()

    if event_id in RECENT_EVENTS:
        logger.info("Duplicate event received — ignoring")
        return {"status": "duplicate"}

    # Add to cache AFTER checking
    RECENT_EVENTS[event_id] = time.time()

    # Process the event
    if event_type == "phone.recording_completed":
        return await handle_recording_completed(payload)

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

        call_id = obj.get("call_id") or obj.get("id")
        if not call_id:
            call_id = f"zoom_{time.time_ns()}"
            logger.warning(f"Missing call_id — generated new ID: {call_id}")

        recording_url = obj.get("download_url") or obj.get("recording_file", {}).get(
            "download_url"
        )

        caller = obj.get("caller") or {}
        callee = obj.get("callee") or {}

        agent_name = callee.get("name") or callee.get("extension_number") or "Unknown"
        customer_number = caller.get("phone_number") or caller.get("name") or "Unknown"

        start_time = obj.get("date_time") or obj.get("start_time")
        duration = obj.get("duration")

        # Prevent duplicate processing
        if CallRecordsDB.get_call_by_call_id(call_id):
            logger.info(f"Call {call_id} already exists — skipping")
            return {"status": "duplicate", "call_id": call_id}

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
        return {"status": "success", "record_id": record_id}

    except DatabaseError as e:
        if "duplicate" in str(e).lower():
            return {"status": "duplicate"}
        raise HTTPException(500, f"Database error: {e}")

    except Exception as e:
        logger.error(f"Unhandled error: {e}")
        raise HTTPException(500, str(e))

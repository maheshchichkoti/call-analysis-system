"""
Zoom Phone Webhook Handler

Handles incoming webhooks from Zoom Phone:
- phone.recording_completed — New call recording available
- Validates webhook signature (optional for development)
- Inserts call record into database
"""

import hmac
import hashlib
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, Header
from pydantic import BaseModel

from ..config import settings
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Zoom Webhook"])


def verify_webhook_signature(
    payload: bytes,
    signature: str,
    timestamp: str,
) -> bool:
    """
    Verify Zoom webhook signature.

    Zoom uses: HMAC-SHA256 of 'v0:{timestamp}:{payload}'
    """
    secret = settings.ZOOM_WEBHOOK_SECRET_TOKEN
    if not secret:
        # No secret configured — skip verification (development mode)
        logger.warning("ZOOM_WEBHOOK_SECRET_TOKEN not set, skipping verification")
        return True

    try:
        message = f"v0:{timestamp}:{payload.decode('utf-8')}"
        expected = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        expected_sig = f"v0={expected}"

        # Check both formats (with and without v0= prefix)
        if hmac.compare_digest(expected_sig, signature):
            return True
        if hmac.compare_digest(expected, signature):
            return True
        if hmac.compare_digest(expected_sig, f"v0={signature}"):
            return True

        logger.warning(f"Signature mismatch. Expected: {expected_sig[:20]}...")
        return False

    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False


@router.post("/zoom")
async def zoom_webhook(
    request: Request,
    x_zm_signature: Optional[str] = Header(None, alias="x-zm-signature"),
    x_zm_request_timestamp: Optional[str] = Header(
        None, alias="x-zm-request-timestamp"
    ),
):
    """
    Handle Zoom Phone webhook events.

    Currently supports:
    - endpoint.url_validation (Zoom validation challenge)
    - phone.recording_completed (new recording)
    """
    body = await request.body()

    # Parse event first (needed for URL validation)
    try:
        data = await request.json()
        event_type = data.get("event", "")
        payload = data.get("payload", {})
    except Exception as e:
        logger.error(f"Failed to parse webhook: {e}")
        raise HTTPException(400, "Invalid JSON")

    # Handle URL validation (no signature check needed)
    if event_type == "endpoint.url_validation":
        plain_token = payload.get("plainToken", "")
        secret = settings.ZOOM_WEBHOOK_SECRET_TOKEN or "default_secret"
        encrypted = hmac.new(
            secret.encode(),
            plain_token.encode(),
            hashlib.sha256,
        ).hexdigest()
        logger.info("Zoom URL validation successful")
        return {
            "plainToken": plain_token,
            "encryptedToken": encrypted,
        }

    # Verify signature for other events (if configured)
    if settings.ZOOM_WEBHOOK_SECRET_TOKEN:
        if not x_zm_signature or not x_zm_request_timestamp:
            logger.warning("Missing signature headers, but allowing in development")
            if settings.ENVIRONMENT == "production":
                raise HTTPException(401, "Missing signature headers")
        elif not verify_webhook_signature(body, x_zm_signature, x_zm_request_timestamp):
            if settings.ENVIRONMENT == "production":
                raise HTTPException(401, "Invalid signature")
            logger.warning("Signature verification failed, but allowing in development")

    logger.info(f"Received Zoom event: {event_type}")

    # Handle phone recording completed
    if event_type == "phone.recording_completed":
        return await handle_recording_completed(payload)

    else:
        logger.info(f"Ignoring event type: {event_type}")
        return {"status": "ignored", "event": event_type}


async def handle_recording_completed(payload: dict):
    """
    Handle phone.recording_completed event.

    Extracts call metadata and creates a database record.
    """
    try:
        obj = payload.get("object", {})

        # Extract call data
        call_id = obj.get("call_id", obj.get("id", ""))
        recording_url = obj.get("download_url") or obj.get("recording_file", {}).get(
            "download_url"
        )

        # Participant info
        caller = obj.get("caller", {})
        callee = obj.get("callee", {})

        agent_name = callee.get("name") or callee.get("extension_number")
        customer_number = caller.get("phone_number") or caller.get("name")

        # Timing
        start_time = obj.get("date_time") or obj.get("start_time")
        duration = obj.get("duration")

        if not call_id:
            # Generate a unique call_id if not provided
            call_id = f"zoom_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            logger.warning(f"Missing call_id in webhook, generated: {call_id}")

        # Check if call already exists
        try:
            existing = CallRecordsDB.get_call_by_call_id(call_id)
            if existing:
                logger.info(f"Call {call_id} already exists, skipping")
                return {
                    "status": "skipped",
                    "message": "Call already processed",
                    "call_id": call_id,
                }
        except Exception:
            pass  # Method might not exist yet, continue

        # Insert into database
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

        logger.info(f"Created call record {record_id} from webhook")

        return {
            "status": "success",
            "record_id": record_id,
            "call_id": call_id,
        }

    except DatabaseError as e:
        error_msg = str(e)
        # Handle duplicate key error gracefully
        if "unique constraint" in error_msg.lower() or "duplicate" in error_msg.lower():
            logger.warning(f"Duplicate call_id, skipping: {e}")
            return {
                "status": "skipped",
                "message": "Call already exists",
            }
        logger.error(f"Database error: {e}")
        raise HTTPException(500, f"Database error: {e}")

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(500, str(e))

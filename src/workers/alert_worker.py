# src/workers/alert_worker.py
"""
Email Alert Background Worker.

Sends email alerts for calls with warnings.
"""

import logging
import time
import json
from typing import Dict, Any

from ..config import settings
from ..services.email_service import EmailService
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)


class AlertWorker:
    """
    Background worker for sending email alerts.

    Flow:
    1. Find records with has_warning=true and alert_email_status='pending'
    2. Send email alert with call details
    3. Update record with sent or failed status
    """

    def __init__(self):
        self.email_service = EmailService()
        self.batch_size = settings.WORKER_BATCH_SIZE
        self.poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

    # ----------------------------------------------------------------------
    # PROCESS BATCH
    # ----------------------------------------------------------------------
    def process_batch(self) -> int:
        try:
            pending = CallRecordsDB.find_pending_alerts(self.batch_size)
        except DatabaseError as e:
            logger.error(f"Database error finding pending alerts: {e}")
            return 0

        if not pending:
            logger.debug("No pending alerts")
            return 0

        logger.info(f"Processing {len(pending)} pending alerts")
        sent = 0

        for record in pending:
            record_id = record["id"]

            try:
                self._send_alert(record)
                sent += 1

            except Exception as e:
                logger.error(f"Failed to send alert for {record_id}: {e}")

                # store the actual error message
                CallRecordsDB.update_alert_status(
                    record_id, status="failed", error=str(e)
                )

        return sent

    # ----------------------------------------------------------------------
    # SEND SINGLE ALERT
    # ----------------------------------------------------------------------
    def _send_alert(self, record: Dict[str, Any]):
        record_id = record["id"]
        logger.info(f"Sending alert for {record_id}")

        # Parse warning reasons JSON
        raw_reasons = record.get("warning_reasons_json")
        warning_reasons = []

        if raw_reasons:
            try:
                # If already list → use it directly
                warning_reasons = (
                    raw_reasons
                    if isinstance(raw_reasons, list)
                    else json.loads(raw_reasons)
                )
            except Exception:
                logger.warning(f"Invalid warning_reasons_json for {record_id}")
                warning_reasons = []

        # Build call data for email
        call_data = {
            "agent_name": record.get("agent_name", "Unknown"),
            "agent_id": record.get("agent_id"),
            "customer_number": record.get("customer_number"),
            "start_time": str(record.get("start_time", "")),
            "end_time": str(record.get("end_time", "")),
            "duration_seconds": record.get("duration_seconds", 0),
            "overall_score": record.get("overall_score"),
            "has_warning": record.get("has_warning", False),
            "warning_reasons": warning_reasons,
            "short_summary": record.get("short_summary"),
            "customer_sentiment": record.get("customer_sentiment"),
            "transcript_text": record.get("transcript_text", "")[:3000],
        }

        # Send email
        self.email_service.send_call_alert(call_data)

        # Mark as sent
        CallRecordsDB.update_alert_status(record_id, status="sent")

        logger.info(f"Alert sent for {record_id}")

    # ----------------------------------------------------------------------
    # LOOP MODE
    # ----------------------------------------------------------------------
    def run_forever(self):
        logger.info("Starting Alert Worker")

        while True:
            try:
                sent = self.process_batch()
                if sent > 0:
                    logger.info(f"Sent {sent} alerts")

            except Exception as e:
                logger.error(f"Worker error: {e}")

            time.sleep(self.poll_interval)


def run_worker():
    worker = AlertWorker()
    worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()

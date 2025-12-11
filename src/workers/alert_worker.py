# src/workers/alert_worker.py
"""
Email Alert Background Worker — Production Version

Improvements:
- Retry logic with exponential backoff
- Proper classification of transient vs permanent SMTP errors
- Safer JSON parsing for warning_reasons_json
- Circuit breaker for repeated failures
- Clean DB update behavior
"""

import logging
import time
import json
from typing import Dict, Any, List

from ..config import settings
from ..services.email_service import EmailService, EmailSendError
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)


class AlertWorker:
    MAX_EMAIL_RETRIES = 3
    BACKOFF_STEPS = [1, 3, 8]  # seconds
    CIRCUIT_BREAKER_THRESHOLD = 5
    CIRCUIT_BREAKER_COOLDOWN = 60  # seconds

    def __init__(self):
        self.email_service = EmailService()
        self.batch_size = settings.WORKER_BATCH_SIZE
        self.poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

        self.failure_count = 0
        self.circuit_open = False
        self.circuit_reopen_time = 0

    # ---------------------------------------------------------
    def process_batch(self) -> int:
        """Process a batch of pending alerts."""
        # Circuit breaker: stop sending emails until cooldown expires
        if self.circuit_open:
            if time.time() < self.circuit_reopen_time:
                logger.warning("AlertWorker circuit breaker active — skipping batch")
                return 0
            else:
                logger.info("Circuit breaker reset — resuming email sending")
                self.circuit_open = False
                self.failure_count = 0

        try:
            pending = CallRecordsDB.find_pending_alerts(self.batch_size)
        except DatabaseError as e:
            logger.error(f"DB error retrieving alerts: {e}")
            return 0

        if not pending:
            return 0

        logger.info(f"Processing {len(pending)} pending alerts")
        sent_count = 0

        for record in pending:
            record_id = record["id"]

            try:
                self._attempt_send(record)
                sent_count += 1

            except Exception as e:
                logger.error(f"Alert send failed for {record_id}: {e}")
                try:
                    CallRecordsDB.update_alert_status(
                        record_id, status="failed", error=str(e)
                    )
                except Exception:
                    logger.error("Failed to update alert failure status")

                # Circuit breaker escalation
                self.failure_count += 1
                if self.failure_count >= self.CIRCUIT_BREAKER_THRESHOLD:
                    self._trip_circuit_breaker()

        return sent_count

    # ---------------------------------------------------------
    def _attempt_send(self, record: Dict[str, Any]):
        """Send an alert with retries + backoff."""
        record_id = record["id"]

        warning_reasons = self._parse_warning_reasons(record)

        call_data = {
            "agent_name": record.get("agent_name", "Unknown"),
            "customer_number": record.get("customer_number", "Unknown"),
            "overall_score": record.get("overall_score"),
            "has_warning": record.get("has_warning"),
            "warning_reasons": warning_reasons,
            "short_summary": record.get("short_summary", ""),
            "customer_sentiment": record.get("customer_sentiment"),
            "start_time": str(record.get("start_time", "")),
            "duration_seconds": record.get("duration_seconds"),
            "department": record.get("department", "unknown"),
        }

        last_err = None

        for attempt in range(self.MAX_EMAIL_RETRIES):
            try:
                logger.info(f"Sending alert for {record_id} (attempt {attempt + 1})")
                self.email_service.send_call_alert(call_data)

                CallRecordsDB.update_alert_status(record_id, status="sent")
                logger.info(f"Alert sent for {record_id}")
                self.failure_count = 0  # reset failure count after success
                return

            except EmailSendError as e:
                last_err = e
                logger.warning(f"Email attempt {attempt + 1} failed: {e}")

                # transient errors → retry
                time.sleep(
                    self.BACKOFF_STEPS[min(attempt, len(self.BACKOFF_STEPS) - 1)]
                )
                continue

            except Exception as e:
                last_err = e
                break  # non-email error → do not retry

        # Retries exhausted
        CallRecordsDB.update_alert_status(
            record_id, status="failed", error=str(last_err)
        )
        raise EmailSendError(f"Retries exhausted for {record_id}: {last_err}")

    # ---------------------------------------------------------
    def _parse_warning_reasons(self, record: Dict[str, Any]) -> List[str]:
        raw = record.get("warning_reasons_json")
        if not raw:
            return []

        # Already a list?
        if isinstance(raw, list):
            return raw

        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            logger.warning(
                f"Invalid warning_reasons_json for record {record.get('id')}"
            )
            return []

    # ---------------------------------------------------------
    def _trip_circuit_breaker(self):
        self.circuit_open = True
        self.circuit_reopen_time = time.time() + self.CIRCUIT_BREAKER_COOLDOWN
        logger.error(
            f"AlertWorker Circuit Breaker TRIPPED — too many failures. "
            f"Cooling down for {self.CIRCUIT_BREAKER_COOLDOWN} seconds."
        )

    # ---------------------------------------------------------
    def run_forever(self):
        logger.info("Alert Worker started")

        while True:
            try:
                sent = self.process_batch()
                if sent > 0:
                    logger.info(f"Sent {sent} alert emails")

            except Exception as e:
                logger.error(f"AlertWorker crash: {e}")

            time.sleep(self.poll_interval)


def run_worker():
    AlertWorker().run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()

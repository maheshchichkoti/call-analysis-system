#!/usr/bin/env python
"""
Background Workers Runner — Production Ready

Runs:
  • AnalysisWorker
  • AlertWorker

Handles:
  • Graceful shutdown (SIGINT/SIGTERM)
  • Config validation
  • Thread lifecycle management
"""

import logging
import threading
import time
import signal

from src.config import settings
from src.workers.analysis_worker import AnalysisWorker
from src.workers.alert_worker import AlertWorker

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
)
logger = logging.getLogger("workers")

shutdown_event = threading.Event()


# -------------------------------------------------------------------
# WORKER WRAPPERS
# -------------------------------------------------------------------
def run_analysis_worker():
    worker = AnalysisWorker()
    logger.info("Analysis Worker started")

    while not shutdown_event.is_set():
        try:
            processed = worker.process_batch()
            if processed:
                logger.info(f"Processed {processed} calls")
        except Exception as e:
            logger.exception(f"Analysis Worker error: {e}")

        shutdown_event.wait(settings.WORKER_POLL_INTERVAL_SECONDS)

    logger.info("Analysis Worker stopped")


def run_alert_worker():
    worker = AlertWorker()
    logger.info("Alert Worker started")

    while not shutdown_event.is_set():
        try:
            sent = worker.process_batch()
            if sent:
                logger.info(f"Sent {sent} alert emails")
        except Exception as e:
            logger.exception(f"Alert Worker error: {e}")

        shutdown_event.wait(settings.WORKER_POLL_INTERVAL_SECONDS)

    logger.info("Alert Worker stopped")


# -------------------------------------------------------------------
# SIGNAL HANDLERS
# -------------------------------------------------------------------
def signal_handler(signum, _frame):
    logger.info(f"Shutdown signal received: {signum}")
    shutdown_event.set()


# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
def main():
    logger.info("=" * 65)
    logger.info("CALL ANALYSIS SYSTEM — WORKERS INITIALIZING")
    logger.info("=" * 65)

    # Validate configuration
    for issue in settings.validate():
        logger.warning(f"[CONFIG] {issue}")

    # Linux/macOS signal handling
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    threads = [
        threading.Thread(
            target=run_analysis_worker, name="AnalysisWorker", daemon=True
        ),
        threading.Thread(target=run_alert_worker, name="AlertWorker", daemon=True),
    ]

    for t in threads:
        t.start()
        logger.info(f"Started {t.name}")

    # Main wait loop
    try:
        while not shutdown_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_event.set()

    logger.info("Stopping workers...")

    for t in threads:
        t.join(timeout=5)

    logger.info("All workers stopped cleanly")


if __name__ == "__main__":
    main()

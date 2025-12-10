#!/usr/bin/env python3
"""
Worker Runner - Runs all background workers.

Usage:
    python run_workers.py                  # Run all workers
    python run_workers.py --worker transcription  # Run specific worker
"""

import argparse
import logging
import signal
import time
import threading
from concurrent.futures import ThreadPoolExecutor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("worker_runner")

# Graceful shutdown flag
shutdown_event = threading.Event()


def handle_shutdown(signum, frame):
    """Handle shutdown signals."""
    logger.info("Received shutdown signal, stopping workers...")
    shutdown_event.set()


def run_transcription_worker():
    """Run transcription worker loop."""
    from src.workers.transcription_worker import TranscriptionWorker
    from src.config import settings

    worker = TranscriptionWorker()
    logger.info("Transcription worker started")

    while not shutdown_event.is_set():
        try:
            worker.process_batch()
        except Exception as e:
            logger.error(f"Transcription worker error: {e}")

        # Interruptible sleep
        for _ in range(settings.WORKER_POLL_INTERVAL_SECONDS):
            if shutdown_event.is_set():
                break
            time.sleep(1)

    logger.info("Transcription worker stopped")


def run_analysis_worker():
    """Run analysis worker loop."""
    from src.workers.analysis_worker import AnalysisWorker
    from src.config import settings

    worker = AnalysisWorker()
    logger.info("Analysis worker started")

    while not shutdown_event.is_set():
        try:
            worker.process_batch()
        except Exception as e:
            logger.error(f"Analysis worker error: {e}")

        for _ in range(settings.WORKER_POLL_INTERVAL_SECONDS):
            if shutdown_event.is_set():
                break
            time.sleep(1)

    logger.info("Analysis worker stopped")


def run_alert_worker():
    """Run alert worker loop."""
    from src.workers.alert_worker import AlertWorker
    from src.config import settings

    worker = AlertWorker()
    logger.info("Alert worker started")

    while not shutdown_event.is_set():
        try:
            worker.process_batch()
        except Exception as e:
            logger.error(f"Alert worker error: {e}")

        for _ in range(settings.WORKER_POLL_INTERVAL_SECONDS):
            if shutdown_event.is_set():
                break
            time.sleep(1)

    logger.info("Alert worker stopped")


def main():
    parser = argparse.ArgumentParser(description="Run background workers")
    parser.add_argument(
        "--worker",
        "-w",
        choices=["transcription", "analysis", "alert", "all"],
        default="all",
        help="Which worker(s) to run",
    )

    args = parser.parse_args()

    # Set up signal handlers
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info("=" * 50)
    logger.info("  Call Analysis Workers Starting")
    logger.info("=" * 50)

    workers = {
        "transcription": run_transcription_worker,
        "analysis": run_analysis_worker,
        "alert": run_alert_worker,
    }

    if args.worker == "all":
        # Run all workers in threads
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = []
            for name, worker_fn in workers.items():
                logger.info(f"Starting {name} worker...")
                futures.append(executor.submit(worker_fn))

            # Wait for shutdown
            try:
                while not shutdown_event.is_set():
                    time.sleep(1)
            except KeyboardInterrupt:
                shutdown_event.set()

            logger.info("Waiting for workers to stop...")
    else:
        # Run single worker
        worker_fn = workers[args.worker]
        try:
            worker_fn()
        except KeyboardInterrupt:
            pass

    logger.info("All workers stopped")


if __name__ == "__main__":
    main()

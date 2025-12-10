# src/workers/analysis_worker.py
"""
Analysis Background Worker.

Processes transcribed calls with pending analysis.
Uses Gemini AI to analyze transcripts.
"""

import logging
import time
from typing import Dict, Any

from ..config import settings
from ..services.call_analyzer import CallAnalyzer, CallAnalysisError
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)


class AnalysisWorker:
    """
    Background worker for analyzing call transcripts.

    Flow:
      1. Find transcription_status='success' AND analysis_status='pending'
      2. Analyze transcript with Gemini
      3. Save results or failure status
    """

    def __init__(self):
        self.analyzer = CallAnalyzer()
        self.batch_size = settings.WORKER_BATCH_SIZE
        self.poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

    # ----------------------------------------------------------------------
    # PROCESS BATCH
    # ----------------------------------------------------------------------
    def process_batch(self) -> int:
        try:
            pending = CallRecordsDB.find_pending_analysis(self.batch_size)
        except DatabaseError as e:
            logger.error(f"Database error fetching pending analysis: {e}")
            return 0

        if not pending:
            logger.debug("No pending analysis tasks")
            return 0

        logger.info(f"Processing {len(pending)} pending analyses")
        processed = 0

        for record in pending:
            record_id = record["id"]

            try:
                self._process_record(record)
                processed += 1

            except Exception as e:
                logger.error(f"Failed to analyze record {record_id}: {e}")

                try:
                    CallRecordsDB.update_analysis(
                        record_id, status="failed", error=str(e)
                    )
                except Exception as db_err:
                    logger.error(
                        f"Failed to update analysis failure state for {record_id}: {db_err}"
                    )

        return processed

    # ----------------------------------------------------------------------
    # PROCESS SINGLE RECORD
    # ----------------------------------------------------------------------
    def _process_record(self, record: Dict[str, Any]):
        record_id = record["id"]
        transcript = record.get("transcript_text", "")
        language = record.get("language_detected")
        agent_name = record.get("agent_name")

        logger.info(f"Analyzing record {record_id}")

        if not transcript:
            raise CallAnalysisError("Transcript missing — cannot analyze")

        # Gemini analysis
        analysis = self.analyzer.analyze(
            transcript=transcript,
            language_detected=language,
            agent_name=agent_name,
        )

        # Save results
        CallRecordsDB.update_analysis(
            record_id,
            analysis=analysis,
            status="success",
        )

        logger.info(
            f"Analysis complete for {record_id} — "
            f"score={analysis['overall_score']}, warning={analysis['has_warning']}"
        )

    # ----------------------------------------------------------------------
    # LOOP MODE
    # ----------------------------------------------------------------------
    def run_forever(self):
        logger.info("Starting Analysis Worker")

        while True:
            try:
                processed = self.process_batch()
                if processed > 0:
                    logger.info(f"Processed {processed} analyses")
            except Exception as e:
                logger.error(f"Worker error: {e}")

            time.sleep(self.poll_interval)


def run_worker():
    worker = AnalysisWorker()
    worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()

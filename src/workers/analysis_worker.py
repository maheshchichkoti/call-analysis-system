# src/workers/analysis_worker.py
"""
Unified Analysis Worker — Single Gemini Call.

Processes pending calls:
1. Downloads audio from recording_url
2. Uploads to Gemini Files API
3. Analyzes with single Gemini call
4. Saves results to database
"""

import logging
import time
import tempfile
import httpx
from pathlib import Path
from typing import Dict, Any

from ..config import settings
from ..services.call_analyzer import CallAnalyzer, CallAnalysisError
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)


class AnalysisWorker:
    """
    Unified background worker for analyzing calls.

    Flow:
      1. Find records with analysis_status='pending'
      2. Download audio from recording_url (if available)
      3. Analyze with single Gemini call
      4. Save results to database
    """

    def __init__(self):
        self.analyzer = CallAnalyzer()
        self.batch_size = settings.WORKER_BATCH_SIZE
        self.poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

    # ------------------------------------------------------------------
    # PROCESS BATCH
    # ------------------------------------------------------------------
    def process_batch(self) -> int:
        try:
            pending = CallRecordsDB.find_pending_analysis(self.batch_size)
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            return 0

        if not pending:
            logger.debug("No pending analysis tasks")
            return 0

        logger.info(f"Processing {len(pending)} pending analyses")
        processed = 0

        for record in pending:
            record_id = record["id"]

            try:
                # Mark as processing
                CallRecordsDB.update_analysis_status(record_id, "processing")

                self._process_record(record)
                processed += 1

            except Exception as e:
                logger.error(f"Failed to analyze {record_id}: {e}")

                try:
                    CallRecordsDB.update_analysis(
                        record_id, status="failed", error=str(e)
                    )
                except Exception as db_err:
                    logger.error(f"Failed to update failure status: {db_err}")

        return processed

    # ------------------------------------------------------------------
    # PROCESS SINGLE RECORD
    # ------------------------------------------------------------------
    def _process_record(self, record: Dict[str, Any]):
        record_id = record["id"]
        recording_url = record.get("recording_url")
        agent_name = record.get("agent_name")
        local_file = record.get("local_audio_path")

        logger.info(f"Analyzing record {record_id}")

        # Determine audio source
        audio_path = None

        if local_file and Path(local_file).exists():
            # Use local file if available
            audio_path = local_file
            logger.info(f"Using local file: {audio_path}")

        elif recording_url:
            # Download from URL
            audio_path = self._download_audio(record_id, recording_url)
            logger.info(f"Downloaded audio to: {audio_path}")

        else:
            # Fallback: try transcript if available
            transcript = record.get("transcript_text")
            if transcript and len(transcript) > 20:
                logger.info("Using existing transcript for analysis")
                analysis = self.analyzer.analyze(
                    transcript=transcript,
                    language_detected=record.get("language_detected"),
                    agent_name=agent_name,
                )
                self._save_analysis(record_id, analysis)
                return
            else:
                raise CallAnalysisError("No audio or transcript available")

        # Analyze audio with Gemini
        analysis = self.analyzer.analyze_audio(
            audio_path=audio_path,
            agent_name=agent_name,
        )

        self._save_analysis(record_id, analysis)

        # Clean up temp file
        if recording_url and audio_path:
            try:
                Path(audio_path).unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DOWNLOAD AUDIO
    # ------------------------------------------------------------------
    def _download_audio(self, record_id: str, url: str) -> str:
        """Download audio from URL to temp file."""
        logger.info(f"Downloading audio for {record_id}")

        try:
            with httpx.Client(timeout=120) as client:
                response = client.get(url)
                response.raise_for_status()

            # Determine file extension
            content_type = response.headers.get("content-type", "")
            if "audio/mpeg" in content_type or url.endswith(".mp3"):
                ext = ".mp3"
            elif "audio/wav" in content_type or url.endswith(".wav"):
                ext = ".wav"
            elif "audio/mp4" in content_type or url.endswith(".m4a"):
                ext = ".m4a"
            else:
                ext = ".mp3"  # Default

            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(response.content)
                return tmp.name

        except Exception as e:
            raise CallAnalysisError(f"Failed to download audio: {e}")

    # ------------------------------------------------------------------
    # SAVE ANALYSIS
    # ------------------------------------------------------------------
    def _save_analysis(self, record_id: str, analysis: dict):
        """Save analysis results to database."""
        CallRecordsDB.update_analysis(
            record_id,
            analysis=analysis,
            status="success",
        )

        logger.info(
            f"Analysis complete: {record_id} — "
            f"score={analysis['overall_score']}, warning={analysis['has_warning']}"
        )

    # ------------------------------------------------------------------
    # LOOP MODE
    # ------------------------------------------------------------------
    def run_forever(self):
        logger.info("Starting Analysis Worker (Single Gemini Call Mode)")

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

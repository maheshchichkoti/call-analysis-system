# src/workers/transcription_worker.py
"""
Transcription Background Worker.

Processes call_records with pending transcription.
Downloads audio from Zoom and transcribes using AssemblyAI.
"""

import logging
import time
import requests
from typing import Dict, Any
from pathlib import Path
import tempfile

from ..config import settings
from ..services.transcription import TranscriptionService, TranscriptionError
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)


class TranscriptionWorker:
    """
    Background worker for transcribing call recordings.

    Flow:
    1. Find pending transcription records
    2. Download audio from recording_url
    3. Transcribe with AssemblyAI
    4. Update record with transcript
    """

    def __init__(self):
        self.transcription_service = TranscriptionService()
        self.batch_size = settings.WORKER_BATCH_SIZE
        self.poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

    def process_batch(self) -> int:
        """
        Process a batch of pending transcriptions.

        Returns:
            Number of records processed
        """
        try:
            pending = CallRecordsDB.find_pending_transcription(self.batch_size)
        except DatabaseError as e:
            logger.error(f"Database error finding pending records: {e}")
            return 0

        if not pending:
            logger.debug("No pending transcriptions")
            return 0

        logger.info(f"Processing {len(pending)} pending transcriptions")
        processed = 0

        for record in pending:
            try:
                self._process_record(record)
                processed += 1
            except Exception as e:
                logger.error(f"Failed to process record {record['id']}: {e}")
                CallRecordsDB.update_transcription(
                    record["id"], transcript="", status="failed", error=str(e)
                )

        return processed

    def _process_record(self, record: Dict[str, Any]):
        """Process a single transcription record."""
        record_id = record["id"]
        recording_url = record.get("recording_url")

        logger.info(f"Processing transcription for {record_id}")

        # Mark as processing
        # (In production, you'd set transcription_status = 'processing' first)

        if not recording_url:
            raise TranscriptionError("No recording URL available")

        # Download audio to temp file
        audio_path = self._download_audio(recording_url, record_id)

        try:
            # Transcribe
            result = self.transcription_service.transcribe_file(
                audio_path, language_code=None, speaker_labels=True  # Auto-detect
            )

            # Update database
            CallRecordsDB.update_transcription(
                record_id,
                transcript=result["text"],
                language=result.get("language_code"),
                status="success",
            )

            logger.info(f"Transcription complete for {record_id}")

        finally:
            # Clean up temp file
            try:
                Path(audio_path).unlink()
            except Exception:
                pass

    def _download_audio(self, url: str, record_id: str) -> str:
        """Download audio from URL to temp file."""
        logger.info(f"Downloading audio for {record_id}")

        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        # Save to temp file
        suffix = ".m4a"  # Default, adjust based on content-type
        content_type = response.headers.get("content-type", "")
        if "mp3" in content_type:
            suffix = ".mp3"
        elif "wav" in content_type:
            suffix = ".wav"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
            return f.name

    def run_forever(self):
        """Run the worker continuously."""
        logger.info("Starting Transcription Worker")

        while True:
            try:
                processed = self.process_batch()
                if processed > 0:
                    logger.info(f"Processed {processed} transcriptions")

            except Exception as e:
                logger.error(f"Worker error: {e}")

            time.sleep(self.poll_interval)


def run_worker():
    """Entry point for transcription worker."""
    worker = TranscriptionWorker()
    worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()

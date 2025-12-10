# src/workers/transcription_worker.py
"""
Transcription Background Worker.

Uses the new TranscriptionService (diarization v2 + normalization).
Downloads recording, transcribes, saves cleaned transcript, updates status.
"""

import logging
import time
import requests
import tempfile
from typing import Dict, Any
from pathlib import Path

from ..config import settings
from ..services.transcription import TranscriptionService, TranscriptionError
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)


class TranscriptionWorker:
    """
    Background worker for transcribing call recordings.
    """

    def __init__(self):
        self.transcription_service = TranscriptionService()
        self.batch_size = getattr(settings, "WORKER_BATCH_SIZE", 5)
        self.poll_interval = getattr(settings, "WORKER_POLL_INTERVAL_SECONDS", 10)

    # ------------------------------------------------------------------
    # PROCESS BATCH
    # ------------------------------------------------------------------
    def process_batch(self) -> int:
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
            record_id = record.get("id")

            try:
                self._process_record(record)
                processed += 1

            except Exception as e:
                logger.exception(f"Failed to process record {record_id}: {e}")
                try:
                    CallRecordsDB.update_transcription(
                        record_id, transcript="", status="failed", error=str(e)
                    )
                except Exception as ex:
                    logger.error(
                        f"Failed to update transcription failure for {record_id}: {ex}"
                    )

        return processed

    # ------------------------------------------------------------------
    # PROCESS SINGLE RECORD
    # ------------------------------------------------------------------
    def _process_record(self, record: Dict[str, Any]):
        record_id = record["id"]
        recording_url = record.get("recording_url")

        logger.info(f"Processing transcription for {record_id}")

        if not recording_url:
            raise TranscriptionError("No recording URL available")

        audio_path = self._download_audio(recording_url, record_id)

        try:
            result = self.transcription_service.transcribe_file(
                audio_path,
                language_code=None,
                speakers_expected=2,
            )

            clean_text = result.get("text", "")
            language = result.get("language_code", None)

            # Save completed transcription
            CallRecordsDB.update_transcription(
                record_id,
                transcript=clean_text,
                language=language,
                status="success",
            )

            logger.info(f"Transcription complete for {record_id}")

        except TranscriptionError as e:
            logger.error(f"TranscriptionError for {record_id}: {e}")
            raise

        finally:
            # Delete temporary audio file
            try:
                if audio_path and Path(audio_path).exists():
                    Path(audio_path).unlink()
            except Exception as e:
                logger.debug(f"Failed to delete temp file {audio_path}: {e}")

    # ------------------------------------------------------------------
    # DOWNLOAD AUDIO TEMPORARY FILE
    # ------------------------------------------------------------------
    def _download_audio(self, url: str, record_id: str) -> str:
        logger.info(f"Downloading audio for {record_id} from {url}")

        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()

        # Determine file type
        suffix = ".m4a"
        content_type = resp.headers.get("content-type", "").lower()
        if "mp3" in content_type or url.lower().endswith(".mp3"):
            suffix = ".mp3"
        elif "wav" in content_type or url.lower().endswith(".wav"):
            suffix = ".wav"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
            temp_path = f.name

        logger.debug(f"Downloaded audio to {temp_path}")
        return temp_path

    # ------------------------------------------------------------------
    # LOOP MODE
    # ------------------------------------------------------------------
    def run_forever(self):
        logger.info("Starting Transcription Worker")
        while True:
            try:
                processed = self.process_batch()
                if processed > 0:
                    logger.info(f"Processed {processed} transcriptions")
            except Exception as e:
                logger.exception(f"Worker error: {e}")

            time.sleep(self.poll_interval)


def run_worker():
    worker = TranscriptionWorker()
    worker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()

# src/workers/analysis_worker.py
"""
Analysis Worker — Production Version
"""

import logging
import time
import tempfile
from pathlib import Path
from typing import Dict, Any

import httpx

from ..config import settings
from ..services.call_analyzer import CallAnalyzer, CallAnalysisError
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)


class AnalysisWorker:
    MAX_DOWNLOAD_RETRIES = 3
    DOWNLOAD_BACKOFF = [1, 2, 5]

    def __init__(self):
        self.analyzer = CallAnalyzer()
        self.batch_size = settings.WORKER_BATCH_SIZE
        self.poll_interval = settings.WORKER_POLL_INTERVAL_SECONDS

    # ----------------------------------------------------
    def process_batch(self) -> int:
        try:
            pending = CallRecordsDB.find_pending_analysis(self.batch_size)
        except DatabaseError as e:
            logger.error(f"Database error fetching records: {e}")
            return 0

        if not pending:
            return 0

        logger.info(f"Found {len(pending)} calls needing analysis")
        processed = 0

        for record in pending:
            record_id = record["id"]

            try:
                CallRecordsDB.update_analysis_status(record_id, "processing")
                self._process_record(record)
                processed += 1

            except Exception as e:
                logger.error(f"Record {record_id} analysis failed: {e}")
                try:
                    CallRecordsDB.update_analysis(
                        record_id, status="failed", error=str(e)
                    )
                except Exception:
                    logger.error("Unable to update DB failure status")

        return processed

    # ----------------------------------------------------
    def _process_record(self, record: Dict[str, Any]):
        record_id = record["id"]
        recording_url = record.get("recording_url")
        agent_name = record.get("agent_name")
        local_file = record.get("local_audio_path")

        logger.info(f"Processing record {record_id}")

        # determine audio source
        if local_file and Path(local_file).exists():
            audio_path = local_file
        elif recording_url:
            audio_path = self._download_audio(record_id, recording_url)
        else:
            transcript = record.get("transcript_text")
            if transcript and len(transcript) > 20:
                logger.info(f"Record {record_id}: Using transcript fallback")
                analysis = self.analyzer.analyze(
                    transcript,
                    language_detected=record.get("language_detected"),
                    agent_name=agent_name,
                )
                self._save_analysis(record_id, analysis)
                return
            raise CallAnalysisError("No audio or transcript available")

        # run Gemini analysis
        analysis = self.analyzer.analyze_audio(audio_path, agent_name)
        self._save_analysis(record_id, analysis)

        # cleanup temp files
        if recording_url and audio_path and audio_path.startswith("/tmp"):
            try:
                Path(audio_path).unlink()
            except Exception:
                pass

    # ----------------------------------------------------
    def _download_audio(self, record_id: str, url: str) -> str:
        logger.info(f"Downloading audio for {record_id} → {url}")

        # Check if this is a Zoom URL that needs OAuth
        is_zoom_url = "zoom.us" in url

        last_err = None

        for attempt in range(self.MAX_DOWNLOAD_RETRIES):
            try:
                if is_zoom_url:
                    # Use Zoom OAuth for authenticated download
                    from ..services.zoom_auth import ZoomAuth, ZoomAuthError

                    try:
                        content = ZoomAuth.download_recording(url)
                        content_type = "audio/mpeg"  # Zoom recordings are typically mp3
                    except ZoomAuthError as e:
                        raise CallAnalysisError(f"Zoom auth failed: {e}")
                else:
                    # Regular HTTP download for non-Zoom URLs
                    with httpx.Client(timeout=60) as client:
                        resp = client.get(url)
                        resp.raise_for_status()
                        content = resp.content
                        content_type = resp.headers.get("content-type", "")

                if len(content) < 2000:
                    raise CallAnalysisError("Downloaded audio file is too small")

                ext = self._infer_extension(url, content_type)

                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(content)
                    logger.info(f"Downloaded {len(content)} bytes to {tmp.name}")
                    return tmp.name

            except Exception as e:
                last_err = e
                logger.error(f"Download failed (attempt {attempt+1}): {e}")

            time.sleep(
                self.DOWNLOAD_BACKOFF[min(attempt, len(self.DOWNLOAD_BACKOFF) - 1)]
            )

        raise CallAnalysisError(f"Audio download retries exhausted: {last_err}")

    # ----------------------------------------------------
    def _infer_extension(self, url: str, content_type: str) -> str:
        if "mp3" in content_type or url.endswith(".mp3"):
            return ".mp3"
        if "wav" in content_type or url.endswith(".wav"):
            return ".wav"
        if "m4a" in content_type or url.endswith(".m4a"):
            return ".m4a"
        return ".mp3"

    # ----------------------------------------------------
    def _save_analysis(self, record_id: str, analysis: dict):
        CallRecordsDB.update_analysis(record_id, analysis=analysis, status="success")

    # ----------------------------------------------------
    def run_forever(self):
        logger.info("Analysis Worker started")

        while True:
            try:
                count = self.process_batch()
                if count:
                    logger.info(f"Processed {count} calls")
            except Exception as e:
                logger.error(f"Worker crash: {e}")

            time.sleep(self.poll_interval)


def run_worker():
    AnalysisWorker().run_forever()

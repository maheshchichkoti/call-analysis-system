# src/services/transcription.py
"""
AssemblyAI Transcription Service with TRUE Diarization V2 + Clean Transcript.

This version:
- Uses correct AssemblyAI diarization parameters
- Extracts real speaker-separated segments
- Converts to Agent/Customer roles
- Produces clean, readable transcript for Gemini
"""

import time
import logging
import requests
from pathlib import Path
from typing import Dict, Any, List

from ..config import settings

logger = logging.getLogger(__name__)


class TranscriptionError(Exception):
    pass


class TranscriptionService:
    BASE_URL = "https://api.assemblyai.com/v2"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.ASSEMBLYAI_API_KEY
        if not self.api_key:
            raise TranscriptionError("ASSEMBLYAI_API_KEY missing")

        self.headers = {
            "authorization": self.api_key,
            "content-type": "application/json",
        }

    # ----------------------------------------------------------------------
    # PUBLIC
    # ----------------------------------------------------------------------
    def transcribe_file(
        self,
        audio_path: str,
        language_code: str = None,
        speakers_expected: int = 2,
    ) -> Dict[str, Any]:

        logger.info(f"Starting transcription for: {audio_path}")

        upload_url = self._upload_file(audio_path)

        logger.info(f"Audio uploaded successfully.")

        job_id = self._create_transcription_job(
            upload_url,
            language_code=language_code,
            speakers_expected=speakers_expected,
        )

        result = self._poll(job_id)

        segments = result.get("utterances") or result.get("words") or []

        clean_text = self._normalize_segments(segments)

        return {
            "text": clean_text,
            "raw_text": result.get("text", ""),
            "language_code": result.get("language_code"),
            "segments": segments,
            "audio_duration": result.get("audio_duration"),
        }

    # ----------------------------------------------------------------------
    # UPLOAD
    # ----------------------------------------------------------------------
    def _upload_file(self, audio_path: str) -> str:
        p = Path(audio_path)
        if not p.exists():
            raise TranscriptionError(f"File not found: {audio_path}")

        with open(p, "rb") as f:
            return self._upload_bytes(f.read())

    def _upload_bytes(self, b: bytes) -> str:
        url = f"{self.BASE_URL}/upload"
        resp = requests.post(url, headers={"authorization": self.api_key}, data=b)

        if resp.status_code != 200:
            raise TranscriptionError(f"Upload failed: {resp.text}")

        return resp.json()["upload_url"]

    # ----------------------------------------------------------------------
    # CREATE JOB
    # ----------------------------------------------------------------------
    def _create_transcription_job(
        self,
        audio_url: str,
        language_code: str,
        speakers_expected: int,
    ) -> str:

        payload = {
            "audio_url": audio_url,
            "punctuate": True,
            "format_text": True,
            "language_detection": not bool(language_code),
            "disfluencies": False,
            # REAL DIARIZATION V2
            "diarization": {
                "enable": True,
                "min_speakers": speakers_expected,
                "max_speakers": speakers_expected,
            },
        }

        if language_code:
            payload["language_code"] = language_code

        url = f"{self.BASE_URL}/transcript"
        resp = requests.post(url, json=payload, headers=self.headers)

        if resp.status_code != 200:
            raise TranscriptionError(f"Job creation failed: {resp.text}")

        return resp.json()["id"]

    # ----------------------------------------------------------------------
    # POLLING
    # ----------------------------------------------------------------------
    def _poll(self, job_id: str, timeout: int = 650) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/transcript/{job_id}"

        start = time.time()
        while True:
            r = requests.get(url, headers=self.headers)
            data = r.json()
            status = data.get("status")

            if status == "completed":
                logger.info(f"Transcription finished in {time.time() - start:.1f}s")
                return data

            if status == "error":
                raise TranscriptionError(data.get("error", "Unknown failure"))

            if time.time() - start > timeout:
                raise TranscriptionError("Transcription timed out")

            time.sleep(3)

    # ----------------------------------------------------------------------
    # NORMALIZATION
    # ----------------------------------------------------------------------
    def _normalize_segments(self, segments: List[Dict[str, Any]]) -> str:
        """
        Convert diarized segments into:
        Agent: text
        Customer: text
        """

        if not segments:
            return ""

        lines = []
        last_role = None

        for seg in segments:
            text = seg.get("text", "").strip()
            speaker = seg.get("speaker")

            if not text:
                continue

            # Speaker mapping (0 = Agent, 1 = Customer)
            role = "Agent" if str(speaker) in ("0", "A") else "Customer"

            if role != last_role:
                lines.append(f"{role}: {text}")
            else:
                lines[-1] += " " + text

            last_role = role

        return "\n".join(lines)

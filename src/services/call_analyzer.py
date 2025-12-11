# src/services/call_analyzer.py
"""
Gemini Call Analyzer — Production-Stable Version
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import TypedDict, Literal, List, Optional

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError

from ..config import settings

logger = logging.getLogger(__name__)


# -------------------------------
# TYPES
# -------------------------------
class AnalysisResult(TypedDict):
    overall_score: int
    has_warning: bool
    warning_reasons: List[str]
    short_summary: str
    customer_sentiment: Literal["positive", "neutral", "negative"]
    department: str


class CallAnalysisError(Exception):
    """Raised when Gemini fails or returns invalid output."""


# -------------------------------
# DEFAULT PROMPT
# -------------------------------
DEFAULT_PROMPT = """You are an expert call center quality analyst...

(unchanged — keep your original prompt here)
"""


# -------------------------------
# ANALYZER CLASS
# -------------------------------
class CallAnalyzer:
    """
    Production-stable Gemini analyzer with:
    - retries
    - safer JSON parsing
    - structured error fallback
    - validated output
    """

    MAX_RETRIES = 3
    RETRY_BACKOFF = [1, 2, 5]

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model or settings.GEMINI_MODEL

        if not self.api_key:
            raise CallAnalysisError("GEMINI_API_KEY not configured")

        genai.configure(api_key=self.api_key)

        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config={
                "temperature": 0.15,
                "max_output_tokens": 4096,
                "response_mime_type": "application/json",
            },
        )

        env_prompt = settings.GEMINI_CALL_ANALYSIS_PROMPT
        self.prompt_template = (
            env_prompt if env_prompt and len(env_prompt) < 3000 else DEFAULT_PROMPT
        )

    # ----------------------------------------------------
    def analyze_audio(
        self, audio_path: str, agent_name: Optional[str] = None
    ) -> AnalysisResult:
        """Analyze an audio file with retry logic + stable JSON parsing."""

        path = Path(audio_path)
        if not path.exists() or path.stat().st_size < 2000:  # <2KB == empty Zoom file
            raise CallAnalysisError("Audio file missing or too small for analysis")

        # build prompt
        prompt = self._build_audio_prompt(agent_name)

        last_err = None

        for attempt in range(self.MAX_RETRIES):
            try:
                logger.info(
                    f"[Gemini] Uploading file (attempt {attempt+1}) → {audio_path}"
                )
                uploaded_file = genai.upload_file(audio_path)

                logger.info(f"[Gemini] Analyzing file using model={self.model_name}")
                response = self.model.generate_content([prompt, uploaded_file])

                raw = response.text or ""
                parsed = self._parse_json_response(raw)
                return self._validate_result(parsed)

            except GoogleAPIError as gex:
                last_err = gex
                logger.error(f"[Gemini] API failure: {gex}")
            except Exception as ex:
                last_err = ex
                logger.error(f"[Gemini] Unexpected error: {ex}")

            time.sleep(self.RETRY_BACKOFF[min(attempt, len(self.RETRY_BACKOFF) - 1)])

        raise CallAnalysisError(f"Gemini retries exhausted: {last_err}")

    # ----------------------------------------------------
    def analyze(
        self, transcript: str, language_detected=None, agent_name=None
    ) -> AnalysisResult:
        """Legacy transcript-only analysis."""
        if not transcript or len(transcript) < 20:
            raise CallAnalysisError("Transcript too short for analysis")

        prompt = self._build_text_prompt(transcript, language_detected, agent_name)

        try:
            response = self.model.generate_content(prompt)
            raw = response.text or ""
            parsed = self._parse_json_response(raw)
            return self._validate_result(parsed)
        except Exception as e:
            logger.error(f"Transcript analysis error: {e}")
            raise CallAnalysisError(str(e))

    # ----------------------------------------------------
    # PROMPT BUILDERS
    # ----------------------------------------------------
    def _build_audio_prompt(self, agent_name=None) -> str:
        context = f"Agent Name: {agent_name}" if agent_name else ""
        return f"{self.prompt_template}\n\n{context}\n\nListen to the audio and return JSON only."

    def _build_text_prompt(
        self, transcript, language_detected=None, agent_name=None
    ) -> str:
        ctx = []
        if agent_name:
            ctx.append(f"Agent: {agent_name}")
        if language_detected:
            ctx.append(f"Language: {language_detected}")

        ctx_str = "\n".join(ctx)
        return (
            f"{self.prompt_template}\n\n{ctx_str}\n\n"
            f"=== TRANSCRIPT ===\n{transcript}\n=== END ==="
        )

    # ----------------------------------------------------
    # JSON PARSER (improved for nested objects)
    # ----------------------------------------------------
    def _parse_json_response(self, raw: str) -> dict:
        if not raw:
            raise CallAnalysisError("Empty response from Gemini")

        # direct attempt
        try:
            return json.loads(raw)
        except Exception:
            pass

        # extract the largest balanced JSON object
        json_str = self._extract_balanced_json(raw)
        if json_str:
            try:
                return json.loads(json_str)
            except Exception:
                pass

        logger.warning("Falling back to default result due to parse error")
        return {
            "overall_score": 3,
            "has_warning": True,
            "warning_reasons": ["parse_error"],
            "short_summary": "Gemini response could not be parsed.",
            "customer_sentiment": "neutral",
            "department": "unknown",
        }

    # ----------------------------------------------------
    def _extract_balanced_json(self, text: str) -> Optional[str]:
        """
        Robust extraction for Gemini JSON output.
        Parses nested braces properly.
        """
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]

        return None

    # ----------------------------------------------------
    # VALIDATION
    # ----------------------------------------------------
    def _validate_result(self, result: dict) -> AnalysisResult:
        score = int(result.get("overall_score", 3))
        score = max(1, min(5, score))

        reasons = result.get("warning_reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]

        sentiment = str(result.get("customer_sentiment", "neutral")).lower()
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = "neutral"

        summary = str(result.get("short_summary", ""))[:500]

        return AnalysisResult(
            overall_score=score,
            has_warning=bool(result.get("has_warning", False)),
            warning_reasons=reasons,
            short_summary=summary,
            customer_sentiment=sentiment,
            department=str(result.get("department", "unknown")).lower(),
        )

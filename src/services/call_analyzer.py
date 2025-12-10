"""
Gemini AI Call Analyzer.

Analyzes call transcripts and returns structured JSON with:
- overall_score (1–5)
- has_warning
- warning_reasons
- short_summary
- customer_sentiment
- department
"""

import json
import logging
from typing import TypedDict, Literal, List

import google.generativeai as genai

from ..config import settings

logger = logging.getLogger(__name__)


class AnalysisResult(TypedDict):
    overall_score: int
    has_warning: bool
    warning_reasons: List[str]
    short_summary: str
    customer_sentiment: Literal["positive", "neutral", "negative"]
    department: str


class CallAnalysisError(Exception):
    pass


class CallAnalyzer:
    """
    Gemini-based analyzer.

    KEY SAFETY FEATURES:
    - STRICT JSON output enforced via `response_mime_type="application/json"`
    - Defensive JSON parsing to avoid worker crashes
    - Normalization to ensure DB always receives correct types
    """

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model or settings.GEMINI_MODEL

        if not self.api_key:
            raise CallAnalysisError("GEMINI_API_KEY not configured")

        genai.configure(api_key=self.api_key)

        # Strict JSON output mode (IMPORTANT)
        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 2048,
                "response_mime_type": "application/json",
            },
        )

        self.prompt_template = settings.GEMINI_CALL_ANALYSIS_PROMPT

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------
    def analyze(
        self, transcript: str, language_detected: str = None, agent_name: str = None
    ) -> AnalysisResult:

        if not transcript or len(transcript.strip()) < 10:
            raise CallAnalysisError("Transcript too short for analysis")

        prompt = self._build_prompt(transcript, language_detected, agent_name)

        logger.info(
            f"Sending transcript ({len(transcript)} chars) to Gemini model {self.model_name}"
        )

        try:
            response = self.model.generate_content(prompt)

            raw_text = response.text or ""
            logger.debug(f"Raw Gemini JSON:\n{raw_text[:400]}")

            parsed = self._parse_json_response(raw_text)
            validated = self._validate_result(parsed)

            logger.info(
                f"Gemini analysis OK: score={validated['overall_score']} warning={validated['has_warning']}"
            )

            return validated

        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            raise CallAnalysisError(f"Analysis failed: {str(e)}")

    # ------------------------------------------------------------------
    # PROMPT BUILDER
    # ------------------------------------------------------------------
    def _build_prompt(
        self, transcript: str, language_detected: str, agent_name: str
    ) -> str:

        context_lines = []
        if language_detected:
            context_lines.append(f"Language Detected: {language_detected}")
        if agent_name:
            context_lines.append(f"Agent Name: {agent_name}")

        context = "\n".join(context_lines)

        return f"""
{self.prompt_template}

{context}

=== CALL TRANSCRIPT START ===
{transcript}
=== CALL TRANSCRIPT END ===
"""

    # ------------------------------------------------------------------
    # JSON PARSING (DEFENSIVE)
    # ------------------------------------------------------------------
    def _parse_json_response(self, raw_text: str) -> dict:
        if not raw_text:
            raise CallAnalysisError("Empty response from Gemini")

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise CallAnalysisError(
                f"Gemini returned invalid JSON: {raw_text[:300]}"
            ) from e

    # ------------------------------------------------------------------
    # VALIDATION + NORMALIZATION
    # ------------------------------------------------------------------
    def _validate_result(self, result: dict) -> AnalysisResult:

        # Score normalization
        score = result.get("overall_score", 3)
        try:
            score = int(score)
        except Exception:
            score = 3
        score = max(1, min(5, score))

        has_warning = bool(result.get("has_warning", False))

        # Reasons normalization
        reasons = result.get("warning_reasons", [])
        if isinstance(reasons, str):
            reasons = [reasons]
        if not isinstance(reasons, list):
            reasons = []

        sentiment = str(result.get("customer_sentiment", "neutral")).lower()
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = "neutral"

        summary = str(result.get("short_summary", "No summary available."))
        department = str(result.get("department", "unknown")).lower()

        return AnalysisResult(
            overall_score=score,
            has_warning=has_warning,
            warning_reasons=reasons,
            short_summary=summary,
            customer_sentiment=sentiment,
            department=department,
        )


# Helper
def analyze_call(transcript: str, language_detected: str = None) -> AnalysisResult:
    return CallAnalyzer().analyze(transcript, language_detected)

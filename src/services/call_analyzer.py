# src/services/call_analyzer.py
"""
Gemini AI Call Analyzer.

Analyzes call transcripts and returns structured JSON with:
- overall_score (1-5)
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
    """Structured result from call analysis."""

    overall_score: int
    has_warning: bool
    warning_reasons: List[str]
    short_summary: str
    customer_sentiment: Literal["positive", "neutral", "negative"]
    department: str


class CallAnalysisError(Exception):
    """Custom exception for analysis failures."""

    pass


class CallAnalyzer:
    """
    Gemini-based call transcript analyzer.

    STRICT JSON MODE ENABLED:
    - Gemini is forced to return ONLY valid JSON
    - No markdown, no backticks, no extra text
    - json.loads() always succeeds
    """

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model or settings.GEMINI_MODEL

        if not self.api_key:
            raise CallAnalysisError("GEMINI_API_KEY not configured")

        # Configure Gemini
        genai.configure(api_key=self.api_key)

        # STRICT JSON MODE
        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 2048,
                "response_mime_type": "application/json",  # <-- THE FIX
            },
        )

        # Load dynamic prompt template
        self.prompt_template = settings.GEMINI_CALL_ANALYSIS_PROMPT

    # ----------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ----------------------------------------------------------------------
    def analyze(
        self, transcript: str, language_detected: str = None, agent_name: str = None
    ) -> AnalysisResult:

        if not transcript or len(transcript.strip()) < 10:
            raise CallAnalysisError("Transcript too short for analysis")

        prompt = self._build_prompt(transcript, language_detected, agent_name)

        logger.info(
            f"Analyzing transcript ({len(transcript)} chars) with {self.model_name}"
        )

        try:
            response = self.model.generate_content(prompt)

            # Now ALWAYS pure JSON because of strict mode
            raw_text = response.text
            logger.debug(f"Gemini raw JSON: {raw_text[:400]}...")

            parsed = self._parse_json_response(raw_text)
            validated = self._validate_result(parsed)

            logger.info(
                f"Analysis complete: score={validated['overall_score']} warning={validated['has_warning']}"
            )

            return validated

        except Exception as e:
            logger.error(f"Gemini analysis failed: {e}")
            raise CallAnalysisError(f"Analysis failed: {str(e)}")

    # ----------------------------------------------------------------------
    # PROMPT BUILDER
    # ----------------------------------------------------------------------
    def _build_prompt(
        self, transcript: str, language_detected: str = None, agent_name: str = None
    ) -> str:

        context_parts = []
        if language_detected:
            context_parts.append(f"Language: {language_detected}")
        if agent_name:
            context_parts.append(f"Agent: {agent_name}")

        context = "\n".join(context_parts)

        return f"""{self.prompt_template}

{context}

=== CALL TRANSCRIPT ===
{transcript}
=== END TRANSCRIPT ===
"""

    # ----------------------------------------------------------------------
    # STRICT JSON PARSER — SIMPLE & BULLETPROOF
    # ----------------------------------------------------------------------
    def _parse_json_response(self, raw_text: str) -> dict:
        """
        In strict JSON mode Gemini returns *only* valid JSON.
        If parsing fails, something is catastrophically wrong.
        """

        if not raw_text:
            raise CallAnalysisError("Empty response from model")

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise CallAnalysisError(
                f"Gemini did not return valid JSON:\n{raw_text[:300]}..."
            ) from e

    # ----------------------------------------------------------------------
    # VALIDATION & NORMALIZATION
    # ----------------------------------------------------------------------
    def _validate_result(self, result: dict) -> AnalysisResult:

        # Score
        score = result.get("overall_score", 3)
        score = int(score) if isinstance(score, (str, int)) else 3
        score = max(1, min(5, score))

        has_warning = bool(result.get("has_warning", False))

        # Warning reasons
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


# Convenience helper
def analyze_call(transcript: str, language_detected: str = None) -> AnalysisResult:
    analyzer = CallAnalyzer()
    return analyzer.analyze(transcript, language_detected)

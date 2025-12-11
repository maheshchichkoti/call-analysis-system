"""
Gemini AI Call Analyzer — Single API Call for Audio Analysis.

Uses Gemini 2.0 Flash to analyze audio files directly:
- Uploads audio via Gemini Files API
- Returns structured JSON with score, warnings, summary, sentiment, department
- No separate transcription step needed
"""

import json
import logging
import re
from pathlib import Path
from typing import TypedDict, Literal, List, Optional

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


# Default prompt (used if not set in .env)
DEFAULT_PROMPT = """You are an expert call center quality analyst. Analyze this customer call audio.

TASK: Evaluate the AGENT's performance and provide a JSON response.

SCORING (1-5):
• 5 = Excellent: Professional, helpful, satisfied customer
• 4 = Good: Professional with minor gaps
• 3 = Average: Adequate but noticeable issues
• 2 = Below Average: Unprofessional or unhelpful
• 1 = Poor: Major issues

WARNING FLAGS (only if applicable):
- rude_agent, unresolved_issue, customer_angry, lack_of_empathy, escalation_needed

RULES:
- Focus on AGENT behavior, not customer
- Summary in English, 1-3 sentences max
- Be concise

OUTPUT (JSON only):
{
  "overall_score": 3,
  "has_warning": false,
  "warning_reasons": [],
  "short_summary": "Brief summary here.",
  "customer_sentiment": "neutral",
  "department": "support"
}"""


class CallAnalyzer:
    """
    Gemini 2.0 Flash audio analyzer.

    SINGLE API CALL:
    - Audio file → Upload → Gemini → JSON result
    - No separate transcription step
    - Strict JSON output mode
    """

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model or settings.GEMINI_MODEL

        if not self.api_key:
            raise CallAnalysisError("GEMINI_API_KEY not configured")

        genai.configure(api_key=self.api_key)

        # Strict JSON output mode with HIGHER token limit
        self.model = genai.GenerativeModel(
            self.model_name,
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 4096,  # Increased from 2048
                "response_mime_type": "application/json",
            },
        )

        # Use default prompt if env prompt is too long or missing
        env_prompt = settings.GEMINI_CALL_ANALYSIS_PROMPT
        if env_prompt and len(env_prompt) < 3000:
            self.prompt_template = env_prompt
        else:
            self.prompt_template = DEFAULT_PROMPT
            logger.info("Using default prompt (env prompt too long or missing)")

    # ------------------------------------------------------------------
    # MAIN: Analyze Audio File
    # ------------------------------------------------------------------
    def analyze_audio(
        self,
        audio_path: str,
        agent_name: str = None,
    ) -> AnalysisResult:
        """
        Analyze audio file with Gemini in a single API call.

        Args:
            audio_path: Path to audio file (MP3, WAV, M4A, etc.)
            agent_name: Optional agent name for context

        Returns:
            AnalysisResult with score, warnings, summary, etc.
        """
        path = Path(audio_path)
        if not path.exists():
            raise CallAnalysisError(f"Audio file not found: {audio_path}")

        logger.info(f"Analyzing audio: {audio_path}")

        try:
            # Step 1: Upload audio to Gemini Files API
            logger.info("Uploading audio to Gemini...")
            uploaded_file = genai.upload_file(audio_path)
            logger.info(f"Upload complete: {uploaded_file.name}")

            # Step 2: Build prompt
            prompt = self._build_audio_prompt(agent_name)

            # Step 3: Analyze with Gemini
            logger.info(f"Analyzing with {self.model_name}...")
            response = self.model.generate_content([prompt, uploaded_file])

            raw_text = response.text or ""
            logger.debug(f"Gemini response ({len(raw_text)} chars): {raw_text[:500]}")

            # Step 4: Parse and validate
            parsed = self._parse_json_response(raw_text)
            validated = self._validate_result(parsed)

            logger.info(
                f"Analysis complete: score={validated['overall_score']}, "
                f"warning={validated['has_warning']}"
            )

            return validated

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            raise CallAnalysisError(f"Analysis failed: {str(e)}")

    # ------------------------------------------------------------------
    # LEGACY: Analyze Transcript Text (for backwards compatibility)
    # ------------------------------------------------------------------
    def analyze(
        self,
        transcript: str,
        language_detected: str = None,
        agent_name: str = None,
    ) -> AnalysisResult:
        """
        Analyze transcript text (legacy method).
        Use analyze_audio() for new code.
        """
        if not transcript or len(transcript.strip()) < 10:
            raise CallAnalysisError("Transcript too short for analysis")

        prompt = self._build_text_prompt(transcript, language_detected, agent_name)

        logger.info(f"Analyzing transcript ({len(transcript)} chars)")

        try:
            response = self.model.generate_content(prompt)
            raw_text = response.text or ""

            parsed = self._parse_json_response(raw_text)
            return self._validate_result(parsed)

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            raise CallAnalysisError(f"Analysis failed: {str(e)}")

    # ------------------------------------------------------------------
    # PROMPT BUILDERS
    # ------------------------------------------------------------------
    def _build_audio_prompt(self, agent_name: str = None) -> str:
        """Build prompt for audio analysis."""
        context = f"Agent Name: {agent_name}" if agent_name else ""

        return f"""
{self.prompt_template}

{context}

Listen to the audio recording above and provide your analysis as JSON.
"""

    def _build_text_prompt(
        self,
        transcript: str,
        language_detected: str = None,
        agent_name: str = None,
    ) -> str:
        """Build prompt for text transcript analysis."""
        context_lines = []
        if language_detected:
            context_lines.append(f"Language: {language_detected}")
        if agent_name:
            context_lines.append(f"Agent: {agent_name}")

        context = "\n".join(context_lines)

        return f"""
{self.prompt_template}

{context}

=== CALL TRANSCRIPT ===
{transcript}
=== END TRANSCRIPT ===
"""

    # ------------------------------------------------------------------
    # JSON PARSING (with fallback for truncated responses)
    # ------------------------------------------------------------------
    def _parse_json_response(self, raw_text: str) -> dict:
        if not raw_text:
            raise CallAnalysisError("Empty response from Gemini")

        # Try direct parse first
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from response
        try:
            # Find JSON object
            match = re.search(r"\{[^{}]*\}", raw_text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

        # If JSON is truncated, try to fix common issues
        try:
            # Try to complete truncated JSON
            fixed = raw_text.strip()

            # Count braces
            open_braces = fixed.count("{")
            close_braces = fixed.count("}")

            # Add missing closing braces
            if open_braces > close_braces:
                # Try to close the JSON properly
                if '"short_summary' in fixed and not fixed.rstrip().endswith("}"):
                    # Truncated in summary - add placeholder ending
                    fixed = re.sub(
                        r'"short_summary":\s*"[^"]*$',
                        '"short_summary": "Analysis truncated."',
                        fixed,
                    )
                    fixed += "}"
                else:
                    fixed += "}" * (open_braces - close_braces)

                return json.loads(fixed)
        except Exception:
            pass

        # Last resort: return default with warning
        logger.warning(
            f"Could not parse Gemini response, using defaults. Raw: {raw_text[:200]}"
        )
        return {
            "overall_score": 3,
            "has_warning": True,
            "warning_reasons": ["parse_error"],
            "short_summary": "Analysis could not be parsed. Please review manually.",
            "customer_sentiment": "neutral",
            "department": "unknown",
        }

    # ------------------------------------------------------------------
    # VALIDATION + NORMALIZATION
    # ------------------------------------------------------------------
    def _validate_result(self, result: dict) -> AnalysisResult:
        # Score
        score = result.get("overall_score", 3)
        try:
            score = int(score)
        except Exception:
            score = 3
        score = max(1, min(5, score))

        has_warning = bool(result.get("has_warning", False))

        # Warning reasons
        reasons = result.get("warning_reasons", [])
        if isinstance(reasons, str):
            reasons = [reasons]
        if not isinstance(reasons, list):
            reasons = []

        # Sentiment
        sentiment = str(result.get("customer_sentiment", "neutral")).lower()
        if sentiment not in ("positive", "neutral", "negative"):
            sentiment = "neutral"

        summary = str(result.get("short_summary", "No summary available."))[:500]
        department = str(result.get("department", "unknown")).lower()

        return AnalysisResult(
            overall_score=score,
            has_warning=has_warning,
            warning_reasons=reasons,
            short_summary=summary,
            customer_sentiment=sentiment,
            department=department,
        )


# ------------------------------------------------------------------
# CONVENIENCE FUNCTIONS
# ------------------------------------------------------------------
def analyze_audio_file(audio_path: str, agent_name: str = None) -> AnalysisResult:
    """Analyze audio file with single Gemini call."""
    return CallAnalyzer().analyze_audio(audio_path, agent_name)


def analyze_transcript(
    transcript: str, language_detected: str = None
) -> AnalysisResult:
    """Analyze transcript text (legacy)."""
    return CallAnalyzer().analyze(transcript, language_detected)

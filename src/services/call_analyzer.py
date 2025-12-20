# src/services/call_analyzer.py
"""
Gemini Call Analyzer — Production-Stable Version
"""

import json
import logging
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
    overall_score: Optional[int]  # None for non-agent calls (voicemail, disconnects)
    has_warning: bool
    warning_reasons: List[str]
    short_summary: str
    customer_sentiment: Literal["positive", "neutral", "negative"]
    department: str
    is_agent_call: bool  # False for voicemail/automated systems


class CallAnalysisError(Exception):
    """Raised when Gemini fails or returns invalid output."""


# -------------------------------
# DEFAULT PROMPT
# -------------------------------
DEFAULT_PROMPT = """You are a **Senior Quality Assurance Analyst** reviewing an AGENT’s performance in a professional call-center interaction.

### 🌍 LANGUAGE HANDLING
- The conversation may be in **Hebrew**, **Arabic**, or **English**.
- Analyze the conversation in its original language to preserve nuance, tone, and cultural context.
- Produce **all outputs strictly in ENGLISH**.

### 🎯 OBJECTIVE
Provide a fair, accurate, and production-grade evaluation of the **agent’s conduct and effectiveness**, independent of the customer’s attitude or the root cause of the issue.

### 🧠 EVALUATION PRINCIPLES
1. **Agent-Only Accountability**  
   Evaluate ONLY the agent’s behavior and decisions.  
   Do NOT penalize the agent for customer frustration, technical issues, or policy limitations outside the agent’s control.

2. **Communication Quality**  
   Assess:
   - Tone (calm, respectful, professional)
   - Active listening (clear acknowledgments such as “I understand”, including Hebrew/Arabic equivalents)
   - Clarity, pacing, and confidence

3. **Cultural Appropriateness**  
   Judge professionalism relative to language norms:
   - Hebrew: direct, efficient communication
   - Arabic: respectful, formal, courteous phrasing

4. **Compliance & Process**  
   Confirm whether the agent:
   - Followed identity-verification rules (if applicable)
   - Avoided sharing restricted or sensitive information
   - Provided correct procedural guidance

5. **Call Completeness**  
   Evaluate based strictly on what occurred:
   - **Incomplete calls** (greetings only, language confirmation only, silence, early disengagement):  
     Score conservatively based on actual interaction. Maximum score 3.
   - **Short calls** (<30 seconds):  
     Limited opportunity to demonstrate skill. Cap score at 4 unless clearly exceptional.
   - **Complete interactions**:  
     Full scoring range available.

   If the interaction ends **before the customer expresses a clear need or request**, the summary must explicitly state that no meaningful discussion took place.

### 📊 SCORING RUBRIC (1–5)
- **5 – Excellent**: Clear resolution, strong empathy, effective problem-solving, proactive guidance
- **4 – Good**: Resolved professionally with minor soft-skill or efficiency gaps
- **3 – Fair**: Incomplete or minimal handling; transactional or flat delivery
- **2 – Poor**: Missed cues, confusion, weak handling, or incorrect guidance
- **1 – Unacceptable**: Rudeness, compliance breach, misinformation, or failure to address the issue

### ⚠️ NON-AGENT CALL DETECTION (CRITICAL)
Before scoring, determine whether this is a real agent-customer interaction:
- Voicemail or automated systems
- Immediate disconnects (<5 seconds, no dialogue)
- Wrong number, background noise only, or no agent engagement

If this is **not** an agent call:
- Return `"overall_score": null`
- Set `"is_agent_call": false`

### 🚩 WARNING FLAGS
Include ONLY when clearly supported by the conversation:
- `rude_agent`
- `lack_of_empathy`
- `escalation_needed`
- `compliance_issue`
- `unresolved_issue`

### 📝 SUMMARY STYLE (CRITICAL)
Write the summary as a **human quality analyst**, not a transcript.

Rules:
- Do NOT narrate obvious mechanics (e.g., “the agent answered the call”).
- Focus on **why the customer contacted**, **how the agent handled it**, and **how the interaction concluded**.
- Use natural, professional language with smooth flow.
- Prioritize meaningful details; omit trivial or mechanical actions.
- Avoid repeating “The agent…” or “The customer…” in consecutive sentences.
- Mention the call language only if contextually relevant.
- If no meaningful discussion occurred, clearly state this.
- The summary must sound like it was written by a real person reviewing the call.

### 📝 SUMMARY REQUIREMENTS
Provide **3–4 sentences** covering:
1. Customer’s reason for contacting (if expressed)
2. Agent’s response and actions
3. Professional tone and handling
4. Final outcome (resolved, redirected, incomplete, disconnected)

For non-agent calls, clearly explain what was detected (voicemail, automated system, disconnect, background noise).

### 🧾 OUTPUT REQUIREMENTS
- Output JSON ONLY
- No markdown
- No explanations
- No extra keys
- No trailing text
- If no warnings apply, return an empty array for `warning_reasons`

### 📦 OUTPUT SCHEMA
{
  "overall_score": <integer 1–5 OR null>,
  "has_warning": <boolean>,
  "warning_reasons": ["<flag1>", "<flag2>"],
  "short_summary": "<3–4 human-written sentences>",
  "customer_sentiment": "positive | neutral | negative",
  "department": "sales | support | billing | general",
  "is_agent_call": <boolean>
}
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
        self.last_duration = 0  # Track duration for safety net

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
        self,
        audio_path: str,
        agent_name: Optional[str] = None,
        duration_seconds: Optional[int] = None,
    ) -> AnalysisResult:
        """Analyze an audio file with retry logic + stable JSON parsing."""

        # Store duration for validation safety net
        self.last_duration = duration_seconds or 0

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
            "overall_score": None,  # No score for parse errors
            "has_warning": True,
            "warning_reasons": ["parse_error"],
            "short_summary": "Gemini response could not be parsed. Unable to analyze call.",
            "customer_sentiment": "neutral",
            "department": "unknown",
            "is_agent_call": False,  # Treat as non-agent call to avoid false metrics
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
        # Check if this is a non-agent call
        is_agent = result.get("is_agent_call", True)

        # Handle score - can be None for non-agent calls
        score_raw = result.get("overall_score")

        # SAFETY NET: Override Gemini if it gave a score to a very short call
        # This catches cases where Gemini ignores our non-agent call instructions
        if score_raw is not None and self.last_duration > 0 and self.last_duration < 10:
            logger.warning(
                f"🛡️ SAFETY NET: Forcing is_agent_call=false for {self.last_duration}s call "
                f"(Gemini incorrectly scored it as {score_raw})"
            )
            is_agent = False
            score = None
        elif score_raw is None:
            score = None
        else:
            score = int(score_raw)
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
            is_agent_call=is_agent,
        )

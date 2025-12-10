# src/services/email_service.py
"""
Resend Email Service (HARDENED PRODUCTION VERSION)

✔ Keeps your full HTML design
✔ Sanitizes all user-provided text (prevents HTML injection)
✔ Handles long transcripts safely
✔ Ensures warnings are always array[str]
✔ Strong error handling for worker stability
"""

import logging
import html
from typing import Optional, Dict, Any, List
import resend

from ..config import settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Custom exception for email failures."""

    pass


# ---------------------------------------------------------------------------
# SAFE HELPERS
# ---------------------------------------------------------------------------


def _safe_text(value) -> str:
    """Ensure text is printable and HTML-escaped."""
    if value is None:
        return ""
    return html.escape(str(value))


def _safe_list(value) -> List[str]:
    """Ensure value is always a list of strings."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


# ---------------------------------------------------------------------------
# EMAIL SERVICE
# ---------------------------------------------------------------------------


class EmailService:
    """
    Sends styled alert emails for calls with warnings.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.RESEND_API_KEY
        self.from_email = settings.RESEND_FROM_EMAIL
        self.default_to = settings.CALL_ALERT_TARGET_EMAIL

        if not self.api_key:
            raise EmailError("RESEND_API_KEY not set")

        resend.api_key = self.api_key

    # ----------------------------------------------------------------------
    # PUBLIC SEND METHOD
    # ----------------------------------------------------------------------
    def send_call_alert(
        self, call_data: Dict[str, Any], to_email: str = None
    ) -> Dict[str, Any]:

        recipient = to_email or self.default_to
        if not recipient:
            raise EmailError("Target email is missing")

        logger.info(f"Sending call alert email → {recipient}")

        subject = self._build_subject(call_data)
        html_body = self._build_html_body(call_data)
        text_body = self._build_text_body(call_data)

        try:
            result = resend.Emails.send(
                {
                    "from": self.from_email,
                    "to": recipient,
                    "subject": subject,
                    "html": html_body,
                    "text": text_body,
                }
            )

            if isinstance(result, dict) and result.get("id"):
                logger.info(f"Email sent successfully (id={result['id']})")
                return result

            raise EmailError(f"Unexpected Resend response: {result}")

        except Exception as e:
            logger.error(f"Email sending failed: {e}")
            raise EmailError(str(e))

    # ----------------------------------------------------------------------
    # SUBJECT BUILDER
    # ----------------------------------------------------------------------
    def _build_subject(self, call_data: Dict[str, Any]) -> str:
        agent = _safe_text(call_data.get("agent_name", "Agent"))
        warnings = _safe_list(call_data.get("warning_reasons"))

        if warnings:
            warn_str = ", ".join(warnings[:3])
            warn_str = warn_str[:80]  # prevent over-long subjects
            return f"⚠️ Call Alert – {agent} – {warn_str}"

        return f"⚠️ Call Alert – {agent}"

    # ----------------------------------------------------------------------
    # HTML EMAIL BUILDER
    # ----------------------------------------------------------------------
    def _build_html_body(self, call_data: Dict[str, Any]) -> str:

        # SAFELY EXTRACT DATA
        agent = _safe_text(call_data.get("agent_name"))
        agent_id = _safe_text(call_data.get("agent_id"))
        customer = _safe_text(call_data.get("customer_number"))
        start_time = _safe_text(call_data.get("start_time"))
        end_time = _safe_text(call_data.get("end_time"))
        score = call_data.get("overall_score", "N/A")
        sentiment = _safe_text(call_data.get("customer_sentiment"))
        summary = _safe_text(call_data.get("short_summary"))
        warnings = _safe_list(call_data.get("warning_reasons"))

        # TRANSCRIPT (safely truncated + escaped)
        transcript_raw = call_data.get("transcript_text", "") or ""
        transcript_clean = _safe_text(transcript_raw[:3000])
        transcript_html = (
            f"<div class='section'><div class='section-title'>📜 Full Transcript</div>"
            f"<div class='transcript'>{transcript_clean}"
            f"{'...' if len(transcript_raw) > 3000 else ''}</div></div>"
            if transcript_raw
            else ""
        )

        # Duration formatting
        dur = call_data.get("duration_seconds") or 0
        duration_str = f"{dur // 60}m {dur % 60}s"

        # WARNING LIST HTML
        if warnings:
            items = "".join(f"<li>{_safe_text(w)}</li>" for w in warnings)
            warnings_html = f"<ul style='color:#dc2626'>{items}</ul>"
        else:
            warnings_html = "<span style='color:#6b7280'>None</span>"

        # Color logic
        sentiment_color = {
            "positive": "#16a34a",
            "neutral": "#6b7280",
            "negative": "#dc2626",
        }.get(sentiment.lower(), "#6b7280")

        score_color = (
            "#16a34a" if score >= 4 else "#f59e0b" if score >= 3 else "#dc2626"
        )

        # FINAL HTML
        return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<style>
body {{ font-family: Arial, sans-serif; background:#fafafa; }}
.container {{ max-width:600px; margin:auto; background:white; border-radius:8px; }}
.header {{ background:#991b1b; color:white; padding:20px; border-radius:8px 8px 0 0; }}
.section {{ padding:15px; border-bottom:1px solid #eee; }}
.section-title {{ font-weight:bold; margin-bottom:8px; }}
.transcript {{ white-space:pre-wrap; background:#f3f4f6; padding:10px; border-radius:6px; }}
.metric {{ display:inline-block; margin:4px; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h2>⚠️ Call Alert</h2>
  <p>A call requires your attention</p>
</div>

<div class="section">
  <div class="metric"><b>Agent:</b> {agent}</div>
  <div class="metric"><b>Score:</b> <span style="color:{score_color}">{score}/5</span></div>
  <div class="metric"><b>Sentiment:</b> <span style="color:{sentiment_color}">{sentiment}</span></div>
  <div class="metric"><b>Duration:</b> {duration_str}</div>
</div>

<div class="section">
  <div class="section-title">📋 Call Details</div>
  <div><b>Customer:</b> {customer}</div>
  <div><b>Start:</b> {start_time}</div>
  <div><b>End:</b> {end_time}</div>
  <div><b>Agent ID:</b> {agent_id}</div>
</div>

<div class="section">
  <div class="section-title">⚠️ Warnings</div>
  {warnings_html}
</div>

<div class="section">
  <div class="section-title">📝 Summary</div>
  <div>{summary}</div>
</div>

{transcript_html}

</div>
</body>
</html>
"""

    # ----------------------------------------------------------------------
    # TEXT EMAIL BUILDER (fallback)
    # ----------------------------------------------------------------------
    def _build_text_body(self, call_data: Dict[str, Any]) -> str:

        agent = call_data.get("agent_name", "Unknown")
        customer = call_data.get("customer_number", "N/A")
        start = call_data.get("start_time", "N/A")
        end = call_data.get("end_time", "N/A")
        score = call_data.get("overall_score", "N/A")
        sentiment = call_data.get("customer_sentiment", "N/A")
        warnings = _safe_list(call_data.get("warning_reasons"))
        summary = call_data.get("short_summary", "")
        transcript = (call_data.get("transcript_text") or "")[:1000]

        warnings_str = ", ".join(warnings) if warnings else "None"

        return f"""
CALL ALERT

Agent: {agent}
Customer: {customer}
Time: {start} → {end}
Score: {score}/5
Sentiment: {sentiment}

Warnings:
{warnings_str}

Summary:
{summary}

Transcript (truncated):
{transcript}
""".strip()


# ----------------------------------------------------------------------
# Convenience function
# ----------------------------------------------------------------------


def send_call_alert(call_data: Dict[str, Any], to_email: str = None) -> bool:
    try:
        EmailService().send_call_alert(call_data, to_email)
        return True
    except Exception as e:
        logger.error(f"send_call_alert failed: {e}")
        return False

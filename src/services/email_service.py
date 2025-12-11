# src/services/email_service.py
"""
SMTP Email Service — Production Version

Sends alert emails via SMTP (your company email server).
Supports Gmail, Outlook, or any SMTP server.
"""

import logging
import smtplib
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional

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
    Uses SMTP (your company email server).
    """

    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL or self.smtp_user
        self.default_to = settings.CALL_ALERT_TARGET_EMAIL

        if not self.smtp_host or not self.smtp_user:
            logger.warning("SMTP not fully configured - emails will be disabled")

    # ----------------------------------------------------------------------
    # PUBLIC SEND METHOD
    # ----------------------------------------------------------------------
    def send_call_alert(
        self, call_data: Dict[str, Any], to_email: str = None
    ) -> Dict[str, Any]:

        recipient = to_email or self.default_to
        if not recipient:
            raise EmailError("Target email is missing")

        if not self.smtp_host or not self.smtp_user:
            raise EmailError("SMTP not configured")

        logger.info(f"Sending call alert email → {recipient}")

        subject = self._build_subject(call_data)
        html_body = self._build_html_body(call_data)
        text_body = self._build_text_body(call_data)

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.from_email
            msg["To"] = recipient

            # Attach text and HTML versions
            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            # Send via SMTP
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info("Email sent successfully!")
            return {"status": "sent", "to": recipient}

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
            warn_str = ", ".join(warnings[:3])[:80]
            return f"⚠️ Call Alert – {agent} – {warn_str}"

        return f"⚠️ Call Alert – {agent}"

    # ----------------------------------------------------------------------
    # HTML EMAIL BUILDER
    # ----------------------------------------------------------------------
    def _build_html_body(self, call_data: Dict[str, Any]) -> str:

        agent = _safe_text(call_data.get("agent_name"))
        agent_id = _safe_text(call_data.get("agent_id"))
        customer = _safe_text(call_data.get("customer_number"))
        start_time = _safe_text(call_data.get("start_time"))
        end_time = _safe_text(call_data.get("end_time"))
        score = call_data.get("overall_score", "N/A")
        sentiment = _safe_text(call_data.get("customer_sentiment"))
        summary = _safe_text(call_data.get("short_summary"))
        warnings = _safe_list(call_data.get("warning_reasons"))

        dur = call_data.get("duration_seconds") or 0
        duration_str = f"{dur // 60}m {dur % 60}s"

        # Warning list HTML
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
        }.get(str(sentiment).lower(), "#6b7280")

        try:
            score_val = int(score)
            score_color = (
                "#16a34a"
                if score_val >= 4
                else "#f59e0b" if score_val >= 3 else "#dc2626"
            )
        except:
            score_color = "#6b7280"

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
.metric {{ display:inline-block; margin:4px 10px 4px 0; }}
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
        score = call_data.get("overall_score", "N/A")
        sentiment = call_data.get("customer_sentiment", "N/A")
        warnings = _safe_list(call_data.get("warning_reasons"))
        summary = call_data.get("short_summary", "")

        warnings_str = ", ".join(warnings) if warnings else "None"

        return f"""
CALL ALERT

Agent: {agent}
Customer: {customer}
Time: {start}
Score: {score}/5
Sentiment: {sentiment}

Warnings:
{warnings_str}

Summary:
{summary}
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

# src/services/email_service.py
"""
SMTP Email Service — Hardened Production Version

Additions:
- Retries handled in worker via structured errors
- SMTP transient/permanent error separation
- Proper TLS handling (STARTTLS + SSL fallback)
- Header sanitization
- Optional CC/BCC
- EmailSendError hierarchy
"""

import logging
import smtplib
import socket
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional

from ..config import settings

logger = logging.getLogger(__name__)


# -------------------------------------------------------------
# CUSTOM ERROR TYPES
# -------------------------------------------------------------
class EmailSendError(Exception):
    """Base class for email-related failures."""

    pass


class EmailTransientError(EmailSendError):
    """Temporary SMTP issue — safe to retry."""

    pass


class EmailPermanentError(EmailSendError):
    """Permanent SMTP issue — should not retry."""

    pass


# -------------------------------------------------------------
# SANITIZATION HELPERS
# -------------------------------------------------------------
def _safe_text(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _safe_list(value) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _clean_header(header: str) -> str:
    """Prevent header injection."""
    return header.replace("\n", " ").replace("\r", " ").strip()


# -------------------------------------------------------------
# EMAIL SERVICE
# -------------------------------------------------------------
class EmailService:
    """
    Production-grade SMTP email sender.
    """

    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = _clean_header(settings.SMTP_FROM_EMAIL or self.smtp_user)
        self.default_to = settings.CALL_ALERT_TARGET_EMAIL

        if not self.smtp_host or not self.smtp_user:
            logger.warning("SMTP is not fully configured — alert emails disabled")

    # ---------------------------------------------------------
    def send_call_alert(
        self,
        call_data: Dict[str, Any],
        to_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
    ) -> Dict[str, Any]:

        recipient = to_email or self.default_to
        if not recipient:
            raise EmailPermanentError("No recipient email configured")

        if not self.smtp_host or not self.smtp_user:
            raise EmailPermanentError("SMTP server not configured")

        msg = self._build_message(call_data, recipient, cc, bcc)

        try:
            self._send_smtp(msg, recipient, cc, bcc)
            return {"status": "sent", "recipient": recipient}

        except EmailSendError:
            raise

        except Exception as e:
            logger.error(f"Unhandled email error: {e}")
            raise EmailPermanentError(str(e))

    # ---------------------------------------------------------
    def _build_message(
        self,
        call_data: Dict[str, Any],
        to_email: str,
        cc: Optional[List[str]],
        bcc: Optional[List[str]],
    ) -> MIMEMultipart:

        subject = _clean_header(self._build_subject(call_data))

        html_body = self._build_html_body(call_data)
        text_body = self._build_text_body(call_data)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_email
        msg["To"] = _clean_header(to_email)

        if cc:
            msg["Cc"] = ", ".join(_clean_header(v) for v in cc)

        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        return msg

    # ---------------------------------------------------------
    def _send_smtp(
        self,
        msg,
        to_email: str,
        cc: Optional[List[str]],
        bcc: Optional[List[str]],
    ):
        """Robust SMTP sending logic with STARTTLS + fallback."""

        recipients = [to_email]
        if cc:
            recipients.extend(cc)
        if bcc:
            recipients.extend(bcc)

        try:
            logger.info(f"Connecting to SMTP server {self.smtp_host}:{self.smtp_port}")
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20)

            try:
                server.ehlo()
                server.starttls()
                server.ehlo()
            except Exception:
                logger.warning("STARTTLS failed, attempting SSL fallback")
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=20)

            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg, to_addrs=recipients)
            server.quit()

            logger.info("SMTP email sent successfully")

        except smtplib.SMTPResponseException as e:
            code = e.smtp_code
            message = (
                e.smtp_error.decode()
                if isinstance(e.smtp_error, bytes)
                else str(e.smtp_error)
            )

            logger.error(f"SMTP error {code}: {message}")

            if 400 <= code < 500:
                raise EmailTransientError(f"Temporary SMTP error {code}: {message}")
            else:
                raise EmailPermanentError(f"Permanent SMTP error {code}: {message}")

        except (socket.timeout, smtplib.SMTPServerDisconnected) as e:
            raise EmailTransientError(f"SMTP connection issue: {e}")

        except Exception as e:
            raise EmailPermanentError(f"Unhandled email error: {e}")

    # ---------------------------------------------------------
    def _build_subject(self, call_data: Dict[str, Any]) -> str:
        agent = _safe_text(call_data.get("agent_name", "Agent"))
        warnings = _safe_list(call_data.get("warning_reasons"))

        if warnings:
            warn = ", ".join(warnings[:3])
            return f"⚠️ Call Alert – {agent} – {warn}"

        return f"⚠️ Call Alert – {agent}"

    # ---------------------------------------------------------
    def _build_html_body(self, call_data: Dict[str, Any]) -> str:
        """Build HTML email body with proper styling."""

        agent = _safe_text(call_data.get("agent_name"))
        warnings = _safe_list(call_data.get("warning_reasons"))
        summary = _safe_text(call_data.get("short_summary"))
        customer = _safe_text(call_data.get("customer_number"))
        score = call_data.get("overall_score")
        sentiment = _safe_text(call_data.get("customer_sentiment"))
        duration = call_data.get("duration_seconds")

        # Format duration (handle None/0)
        if duration and duration > 0:
            duration_str = f"{duration // 60}m {duration % 60}s"
        else:
            duration_str = "N/A"

        # Score color coding
        if score and score >= 4:
            score_color = "#16a34a"  # green
        elif score and score == 3:
            score_color = "#f59e0b"  # yellow/orange
        else:
            score_color = "#dc2626"  # red

        score_display = f"{score}/5" if score else "N/A"

        warnings_html = (
            "<ul>" + "".join(f"<li>{_safe_text(w)}</li>" for w in warnings) + "</ul>"
            if warnings
            else "<i>No warnings</i>"
        )

        sentiment_color = {
            "positive": "#16a34a",
            "neutral": "#6b7280",
            "negative": "#dc2626",
        }.get(sentiment.lower(), "#6b7280")

        return f"""
<html>
<body style="font-family:Arial;background:#fafafa;padding:20px">
<div style="max-width:600px;margin:auto;background:white;border-radius:8px;padding:20px">

<h2 style="color:#991b1b">⚠️ Call Alert</h2>

<p><b>Agent:</b> {agent}</p>
<p><b>Customer:</b> {customer}</p>
<p><b>Score:</b> <span style="color:{score_color};font-weight:bold">{score_display}</span></p>
<p><b>Sentiment:</b> <span style="color:{sentiment_color}">{sentiment}</span></p>
<p><b>Duration:</b> {duration_str}</p>

<h3>Warnings</h3>
{warnings_html}

<h3>Summary</h3>
<p>{summary}</p>

</div>
</body>
</html>
"""

    # ---------------------------------------------------------
    def _build_text_body(self, call_data: Dict[str, Any]) -> str:
        warnings = _safe_list(call_data.get("warning_reasons"))
        warnings_text = ", ".join(warnings) if warnings else "None"

        return (
            "CALL ALERT\n\n"
            f"Agent: {call_data.get('agent_name')}\n"
            f"Customer: {call_data.get('customer_number')}\n"
            f"Score: {call_data.get('overall_score')}\n"
            f"Sentiment: {call_data.get('customer_sentiment')}\n\n"
            "Warnings:\n"
            f"{warnings_text}\n\n"
            "Summary:\n"
            f"{call_data.get('short_summary')}"
        )


# Convenience wrapper
def send_call_alert(call_data: Dict[str, Any], to_email: Optional[str] = None) -> bool:
    try:
        EmailService().send_call_alert(call_data, to_email)
        return True
    except EmailSendError as e:
        logger.error(f"send_call_alert failed: {e}")
        return False

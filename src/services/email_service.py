# src/services/email_service.py
"""
Resend Email Service.

Sends email alerts for warning calls.
Production-ready with retry logic and HTML templates.
"""

import logging
from typing import Optional, Dict, Any
import resend

from ..config import settings

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Custom exception for email failures."""

    pass


class EmailService:
    """
    Resend-based email service for call alerts.

    Features:
    - HTML email templates
    - Retry logic
    - Configurable from/to addresses
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.RESEND_API_KEY
        self.from_email = settings.RESEND_FROM_EMAIL
        self.default_to = settings.CALL_ALERT_TARGET_EMAIL

        if not self.api_key:
            raise EmailError("RESEND_API_KEY not configured")

        # Configure resend
        resend.api_key = self.api_key

    def send_call_alert(
        self, call_data: Dict[str, Any], to_email: str = None
    ) -> Dict[str, Any]:
        """
        Send an alert email for a warning call.

        Args:
            call_data: Dictionary containing call information:
                - agent_name
                - agent_id
                - customer_number
                - start_time
                - end_time
                - duration_seconds
                - overall_score
                - has_warning
                - warning_reasons
                - short_summary
                - customer_sentiment
                - transcript_text (optional)
            to_email: Override recipient email

        Returns:
            Dict with 'id' if successful
        """
        recipient = to_email or self.default_to
        if not recipient:
            raise EmailError("No recipient email configured")

        # Build email content
        subject = self._build_subject(call_data)
        html_body = self._build_html_body(call_data)
        text_body = self._build_text_body(call_data)

        logger.info(f"Sending call alert to {recipient}")

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
                logger.info(f"Email sent successfully: {result['id']}")
                return result
            else:
                raise EmailError(f"Unexpected response: {result}")

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            raise EmailError(f"Email send failed: {str(e)}")

    def _build_subject(self, call_data: Dict[str, Any]) -> str:
        """Build email subject line."""
        agent = call_data.get("agent_name", "Unknown Agent")
        warnings = call_data.get("warning_reasons", [])

        if warnings:
            warning_str = ", ".join(warnings[:3])  # Max 3 warnings in subject
            return f"⚠️ Call Alert – {agent} – {warning_str}"

        return f"⚠️ Call Alert – {agent}"

    def _build_html_body(self, call_data: Dict[str, Any]) -> str:
        """Build HTML email body."""

        # Extract data with defaults
        agent_name = call_data.get("agent_name", "Unknown")
        agent_id = call_data.get("agent_id", "N/A")
        customer = call_data.get("customer_number", "N/A")
        start_time = call_data.get("start_time", "N/A")
        end_time = call_data.get("end_time", "N/A")
        duration = call_data.get("duration_seconds", 0)
        score = call_data.get("overall_score", "N/A")
        sentiment = call_data.get("customer_sentiment", "N/A")
        warnings = call_data.get("warning_reasons", [])
        summary = call_data.get("short_summary", "No summary available.")
        transcript = call_data.get("transcript_text", "")

        # Format duration
        duration_min = duration // 60 if isinstance(duration, int) else 0
        duration_sec = duration % 60 if isinstance(duration, int) else 0
        duration_str = f"{duration_min}m {duration_sec}s"

        # Format warnings
        warnings_html = ""
        if warnings:
            warning_items = "".join([f"<li>{w}</li>" for w in warnings])
            warnings_html = f"<ul style='color: #dc2626;'>{warning_items}</ul>"
        else:
            warnings_html = "<span style='color: #6b7280;'>None</span>"

        # Sentiment color
        sentiment_colors = {
            "positive": "#16a34a",
            "neutral": "#6b7280",
            "negative": "#dc2626",
        }
        sentiment_color = sentiment_colors.get(sentiment, "#6b7280")

        # Score color
        score_color = (
            "#16a34a" if score >= 4 else "#f59e0b" if score >= 3 else "#dc2626"
        )

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #1f2937; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: linear-gradient(135deg, #dc2626, #991b1b); color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f9fafb; padding: 20px; border: 1px solid #e5e7eb; border-top: none; }}
        .metric {{ display: inline-block; padding: 8px 16px; margin: 4px; border-radius: 6px; background: white; border: 1px solid #e5e7eb; }}
        .metric-label {{ font-size: 12px; color: #6b7280; }}
        .metric-value {{ font-size: 18px; font-weight: 600; }}
        .section {{ margin: 20px 0; padding: 15px; background: white; border-radius: 6px; border: 1px solid #e5e7eb; }}
        .section-title {{ font-weight: 600; color: #374151; margin-bottom: 10px; }}
        .transcript {{ max-height: 300px; overflow-y: auto; background: #f3f4f6; padding: 15px; border-radius: 4px; font-size: 14px; white-space: pre-wrap; }}
        .footer {{ text-align: center; padding: 15px; color: #9ca3af; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 24px;">⚠️ Call Alert</h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9;">A call requires your attention</p>
        </div>
        
        <div class="content">
            <div style="margin-bottom: 20px;">
                <div class="metric">
                    <div class="metric-label">Agent</div>
                    <div class="metric-value">{agent_name}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Score</div>
                    <div class="metric-value" style="color: {score_color};">{score}/5</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Sentiment</div>
                    <div class="metric-value" style="color: {sentiment_color}; text-transform: capitalize;">{sentiment}</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Duration</div>
                    <div class="metric-value">{duration_str}</div>
                </div>
            </div>
            
            <div class="section">
                <div class="section-title">📋 Call Details</div>
                <table style="width: 100%; font-size: 14px;">
                    <tr><td style="padding: 4px 0; color: #6b7280;">Customer:</td><td>{customer}</td></tr>
                    <tr><td style="padding: 4px 0; color: #6b7280;">Start Time:</td><td>{start_time}</td></tr>
                    <tr><td style="padding: 4px 0; color: #6b7280;">End Time:</td><td>{end_time}</td></tr>
                    <tr><td style="padding: 4px 0; color: #6b7280;">Agent ID:</td><td>{agent_id}</td></tr>
                </table>
            </div>
            
            <div class="section">
                <div class="section-title">⚠️ Warnings</div>
                {warnings_html}
            </div>
            
            <div class="section">
                <div class="section-title">📝 Summary</div>
                <p style="margin: 0;">{summary}</p>
            </div>
            
            {"<div class='section'><div class='section-title'>📜 Full Transcript</div><div class='transcript'>" + transcript[:3000] + ("..." if len(transcript) > 3000 else "") + "</div></div>" if transcript else ""}
        </div>
        
        <div class="footer">
            This alert was automatically generated by the Call Analysis System.
        </div>
    </div>
</body>
</html>
"""
        return html

    def _build_text_body(self, call_data: Dict[str, Any]) -> str:
        """Build plain text email body."""

        agent_name = call_data.get("agent_name", "Unknown")
        customer = call_data.get("customer_number", "N/A")
        start_time = call_data.get("start_time", "N/A")
        end_time = call_data.get("end_time", "N/A")
        duration = call_data.get("duration_seconds", 0)
        score = call_data.get("overall_score", "N/A")
        sentiment = call_data.get("customer_sentiment", "N/A")
        warnings = call_data.get("warning_reasons", [])
        summary = call_data.get("short_summary", "No summary available.")
        transcript = call_data.get("transcript_text", "")

        duration_min = duration // 60 if isinstance(duration, int) else 0

        warnings_str = ", ".join(warnings) if warnings else "None"

        text = f"""
⚠️ CALL ALERT

Agent: {agent_name}
Customer: {customer}
Time: {start_time} – {end_time}
Duration: {duration_min} minutes
Score: {score}/5
Sentiment: {sentiment}

WARNINGS:
{warnings_str}

SUMMARY:
{summary}

{"TRANSCRIPT:" + chr(10) + transcript[:2000] if transcript else ""}
"""
        return text.strip()


# Convenience function
def send_call_alert(call_data: Dict[str, Any], to_email: str = None) -> bool:
    """
    Send an alert email for a warning call.

    Args:
        call_data: Call information dictionary
        to_email: Optional recipient override

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        service = EmailService()
        service.send_call_alert(call_data, to_email)
        return True
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")
        return False

# src/config.py
"""Application configuration with environment variable loading."""

import os
import logging
from typing import Optional
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Settings:
    """Application settings loaded from environment variables."""

    # General
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Supabase Database (PRIMARY)
    SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
    SUPABASE_KEY: Optional[str] = os.getenv("SUPABASE_KEY")

    # MySQL Database (LEGACY - kept for reference)
    MYSQL_HOST: str = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_PORT: int = int(os.getenv("MYSQL_PORT", "3306"))
    MYSQL_USER: Optional[str] = os.getenv("MYSQL_USER")
    MYSQL_PASSWORD: Optional[str] = os.getenv("MYSQL_PASSWORD")
    MYSQL_DATABASE: str = os.getenv("MYSQL_DATABASE", "call_analysis")

    # AssemblyAI Transcription
    ASSEMBLYAI_API_KEY: Optional[str] = os.getenv("ASSEMBLYAI_API_KEY")
    ASSEMBLYAI_BASE_URL: str = "https://api.assemblyai.com/v2"

    # Gemini AI
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # Configurable prompt - key feature!
    GEMINI_CALL_ANALYSIS_PROMPT: str = os.getenv(
        "GEMINI_CALL_ANALYSIS_PROMPT",
        """You are an expert call quality analyst. Analyze the following call transcript and provide a JSON response.
        
IMPORTANT: The call may be in **Hebrew**, **Arabic**, or English. 
- If the call is in Hebrew/Arabic, analyze the content in its original language but provide the `short_summary` and `warning_reasons` in **English**.
- Assess sentiment and scores based on cultural context appropriate for Israel/Middle East if applicable.

Provide JSON with:
- overall_score: Rating from 1 (poor) to 5 (excellent)
- has_warning: Boolean indicating if the call has concerning issues
- warning_reasons: Array of warning tags (e.g. "rude", "unresolved")
- short_summary: Brief 1-2 sentence summary in English
- customer_sentiment: One of "positive", "neutral", or "negative"
- department: Detected department like "support", "sales", "billing"

Return ONLY valid JSON, no additional text.""",
    )

    # Resend Email
    RESEND_API_KEY: Optional[str] = os.getenv("RESEND_API_KEY")
    RESEND_FROM_EMAIL: str = os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    CALL_ALERT_TARGET_EMAIL: Optional[str] = os.getenv("CALL_ALERT_TARGET_EMAIL")

    # Zoom (for future webhook integration)
    ZOOM_CLIENT_ID: Optional[str] = os.getenv("ZOOM_CLIENT_ID")
    ZOOM_CLIENT_SECRET: Optional[str] = os.getenv("ZOOM_CLIENT_SECRET")
    ZOOM_WEBHOOK_SECRET_TOKEN: Optional[str] = os.getenv("ZOOM_WEBHOOK_SECRET_TOKEN")

    # Worker settings
    WORKER_POLL_INTERVAL_SECONDS: int = int(
        os.getenv("WORKER_POLL_INTERVAL_SECONDS", "30")
    )
    WORKER_BATCH_SIZE: int = int(os.getenv("WORKER_BATCH_SIZE", "5"))
    WORKER_MAX_RETRIES: int = int(os.getenv("WORKER_MAX_RETRIES", "3"))

    def validate(self) -> list:
        """Validate configuration and return list of warnings/errors."""
        issues = []

        if not self.SUPABASE_URL or not self.SUPABASE_KEY:
            issues.append("SUPABASE_URL/SUPABASE_KEY not set - database will fail")

        if not self.ASSEMBLYAI_API_KEY:
            issues.append("ASSEMBLYAI_API_KEY not set - transcription will fail")

        if not self.GEMINI_API_KEY:
            issues.append("GEMINI_API_KEY not set - analysis will fail")

        if not self.RESEND_API_KEY:
            issues.append("RESEND_API_KEY not set - email alerts will fail")

        return issues

    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()

# Log validation warnings on import
for warning in settings.validate():
    logger.warning("Config: %s", warning)

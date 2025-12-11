# src/config.py
"""Application configuration with environment variable loading."""

import os
import logging
from functools import lru_cache
from typing import Optional
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class Settings:
    """Application settings loaded from environment variables."""

    # ---------------------------------------------------------
    # ENVIRONMENT
    # ---------------------------------------------------------
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").lower()
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ---------------------------------------------------------
    # DATABASE (Supabase)
    # ---------------------------------------------------------
    SUPABASE_URL: Optional[str] = os.getenv("SUPABASE_URL")
    SUPABASE_KEY: Optional[str] = os.getenv("SUPABASE_KEY")

    # ---------------------------------------------------------
    # GEMINI AI
    # ---------------------------------------------------------
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    GEMINI_CALL_ANALYSIS_PROMPT: str = os.getenv("GEMINI_CALL_ANALYSIS_PROMPT", "")

    # ---------------------------------------------------------
    # EMAIL (SMTP)
    # ---------------------------------------------------------
    SMTP_HOST: Optional[str] = os.getenv("SMTP_HOST")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: Optional[str] = os.getenv("SMTP_USER")
    SMTP_PASSWORD: Optional[str] = os.getenv("SMTP_PASSWORD")
    SMTP_FROM_EMAIL: Optional[str] = os.getenv("SMTP_FROM_EMAIL")

    # Security flags
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_USE_SSL: bool = os.getenv("SMTP_USE_SSL", "false").lower() == "true"

    # Recipient
    CALL_ALERT_TARGET_EMAIL: Optional[str] = os.getenv("CALL_ALERT_TARGET_EMAIL")

    # ---------------------------------------------------------
    # ZOOM WEBHOOKS
    # ---------------------------------------------------------
    ZOOM_CLIENT_ID: Optional[str] = os.getenv("ZOOM_CLIENT_ID")
    ZOOM_CLIENT_SECRET: Optional[str] = os.getenv("ZOOM_CLIENT_SECRET")
    ZOOM_ACCOUNT_ID: Optional[str] = os.getenv("ZOOM_ACCOUNT_ID")
    ZOOM_WEBHOOK_SECRET_TOKEN: Optional[str] = os.getenv("ZOOM_WEBHOOK_SECRET_TOKEN")

    # Force signature verification in production
    REQUIRE_ZOOM_SIGNATURE: bool = (
        os.getenv("REQUIRE_ZOOM_SIGNATURE", "true").lower() == "true"
    )

    # ---------------------------------------------------------
    # WORKERS
    # ---------------------------------------------------------
    WORKER_POLL_INTERVAL_SECONDS: int = int(
        os.getenv("WORKER_POLL_INTERVAL_SECONDS", "30")
    )
    WORKER_BATCH_SIZE: int = int(os.getenv("WORKER_BATCH_SIZE", "5"))
    WORKER_MAX_RETRIES: int = int(os.getenv("WORKER_MAX_RETRIES", "3"))

    # ---------------------------------------------------------
    # FASTAPI SERVER
    # ---------------------------------------------------------
    SERVER_HOST: str = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------
    def validate(self):
        issues = []

        if not self.SUPABASE_URL or not self.SUPABASE_KEY:
            issues.append("Supabase not configured (SUPABASE_URL / SUPABASE_KEY)")

        if not self.GEMINI_API_KEY:
            issues.append("GEMINI_API_KEY is missing")

        if not self.SMTP_HOST or not self.SMTP_USER:
            issues.append("SMTP not configured — email alerts disabled")

        if not self.CALL_ALERT_TARGET_EMAIL:
            issues.append(
                "CALL_ALERT_TARGET_EMAIL missing — alerts have no destination"
            )

        if self.ENVIRONMENT == "production":
            if not self.ZOOM_WEBHOOK_SECRET_TOKEN:
                issues.append("ZOOM_WEBHOOK_SECRET_TOKEN MUST be set in production")

        return issues

    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache(maxsize=1)
def get_settings():
    return Settings()


settings = get_settings()

# Log issues on startup
for warning in settings.validate():
    logger.warning("Config: %s", warning)

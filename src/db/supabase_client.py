# src/db/supabase_client.py
"""
Supabase client layer for call_records.

Provides:
- Insert
- Update fields
- Fetch by id / call_id
- Pending work queues

This version is production-hardened:
- Safe error handling
- Retry support
- Normalized responses
- Predictable typing
"""

import logging
import json
import time
import functools
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from supabase import create_client, Client
from src.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def retry(operation_name: str, retries: int = 3, delay: float = 0.5):
    """Simple retry decorator for Supabase operations."""

    def wrapper(func):
        @functools.wraps(func)
        def inner(*args, **kwargs):
            last_err = None
            for attempt in range(1, retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    logger.error(
                        f"[DB] {operation_name} failed (attempt {attempt}/{retries}): {e}"
                    )
                    time.sleep(delay)
            raise DatabaseError(
                f"{operation_name} failed after {retries} retries: {last_err}"
            )

        return inner

    return wrapper


class DatabaseError(Exception):
    pass


class CallRecordsDB:
    _client: Optional[Client] = None

    @classmethod
    def client(cls) -> Client:
        if cls._client is None:
            if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
                raise DatabaseError("Supabase credentials missing")

            cls._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            logger.info("Supabase client initialized")

        return cls._client

    # ---------------------------------------------------------
    # INSERT
    # ---------------------------------------------------------
    @classmethod
    @retry("insert_call_record")
    def insert_call_record(cls, call_data: Dict[str, Any]) -> str:
        sb = cls.client()

        payload = {
            "call_id": call_data.get("call_id"),
            "agent_id": call_data.get("agent_id"),
            "agent_name": call_data.get("agent_name"),
            "customer_number": call_data.get("customer_number"),
            "start_time": call_data.get("start_time"),
            "end_time": call_data.get("end_time"),
            "duration_seconds": call_data.get("duration_seconds"),
            "recording_url": call_data.get("recording_url"),
            "local_audio_path": call_data.get("local_audio_path"),
            "analysis_status": "pending",
            "alert_email_status": "pending",
        }

        payload = {k: v for k, v in payload.items() if v is not None}

        resp = sb.table("call_records").insert(payload).execute()

        if not resp.data or "id" not in resp.data[0]:
            raise DatabaseError("Supabase insert returned no row ID")

        return resp.data[0]["id"]

    # ---------------------------------------------------------
    # QUEUE QUERIES
    # ---------------------------------------------------------
    @classmethod
    @retry("find_pending_analysis")
    def find_pending_analysis(cls, limit=5) -> List[Dict[str, Any]]:
        sb = cls.client()
        resp = (
            sb.table("call_records")
            .select("*")
            .eq("analysis_status", "pending")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    @classmethod
    @retry("find_pending_alerts")
    def find_pending_alerts(cls, limit=5) -> List[Dict[str, Any]]:
        sb = cls.client()
        resp = (
            sb.table("call_records")
            .select("*")
            .eq("analysis_status", "success")
            .eq("has_warning", True)
            .eq("alert_email_status", "pending")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    # ---------------------------------------------------------
    # UPDATES
    # ---------------------------------------------------------
    @classmethod
    @retry("update_analysis_status")
    def update_analysis_status(cls, record_id: str, status: str):
        sb = cls.client()
        sb.table("call_records").update({"analysis_status": status}).eq(
            "id", record_id
        ).execute()

    @classmethod
    @retry("update_alert_status")
    def update_alert_status(cls, record_id: str, status="sent", error=None):
        sb = cls.client()

        if status == "sent":
            payload = {"alert_email_status": "sent", "alert_sent_at": _now_iso()}
        else:
            payload = {"alert_email_status": status, "alert_email_error": error}

        sb.table("call_records").update(payload).eq("id", record_id).execute()

    @classmethod
    @retry("update_analysis")
    def update_analysis(
        cls, record_id: str, analysis=None, status="success", error=None
    ):
        sb = cls.client()

        if status == "success" and analysis:
            payload = {
                "overall_score": analysis["overall_score"],
                "has_warning": analysis["has_warning"],
                "warning_reasons_json": json.dumps(analysis.get("warning_reasons", [])),
                "short_summary": analysis["short_summary"],
                "customer_sentiment": analysis["customer_sentiment"],
                "department": analysis["department"],
                "analysis_status": "success",
                "analysis_completed_at": _now_iso(),
                "alert_email_status": (
                    "pending" if analysis["has_warning"] else "not_needed"
                ),
            }
        else:
            payload = {
                "analysis_status": status,
                "analysis_error": error,
                "analysis_completed_at": _now_iso(),
            }

        sb.table("call_records").update(payload).eq("id", record_id).execute()

    # ---------------------------------------------------------
    # READ QUERIES
    # ---------------------------------------------------------
    @classmethod
    @retry("get_recent_calls")
    def get_recent_calls(cls, limit: int = 50):
        sb = cls.client()
        resp = (
            sb.table("call_records")
            .select(
                "id, call_id, agent_name, customer_number, start_time, "
                "duration_seconds, overall_score, customer_sentiment, "
                "has_warning, analysis_status, alert_email_status, created_at"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    @classmethod
    @retry("get_call_by_id")
    def get_call_by_id(cls, record_id: str):
        sb = cls.client()
        resp = (
            sb.table("call_records").select("*").eq("id", record_id).single().execute()
        )
        return resp.data

    @classmethod
    @retry("get_call_by_call_id")
    def get_call_by_call_id(cls, call_id: str):
        sb = cls.client()
        resp = sb.table("call_records").select("*").eq("call_id", call_id).execute()
        return resp.data[0] if resp.data else None

    @classmethod
    @retry("list_calls")
    def list_calls(
        cls,
        limit: int = 50,
        offset: int = 0,
        analysis_status: Optional[str] = None,
        warnings_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Paginated, filterable list of calls for the dashboard.
        """
        sb = cls.client()
        query = sb.table("call_records").select(
            "id, call_id, agent_name, customer_number, start_time, "
            "duration_seconds, overall_score, customer_sentiment, "
            "has_warning, analysis_status, alert_email_status, created_at"
        )

        if analysis_status:
            query = query.eq("analysis_status", analysis_status)

        if warnings_only:
            query = query.eq("has_warning", True)

        resp = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return resp.data or []

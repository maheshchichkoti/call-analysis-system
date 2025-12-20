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
from datetime import datetime, timezone, timedelta
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

        if status in ("success", "not_agent_call") and analysis:
            payload = {
                "overall_score": analysis.get(
                    "overall_score"
                ),  # Can be None for non-agent calls
                "has_warning": analysis.get("has_warning", False),
                "warning_reasons_json": json.dumps(analysis.get("warning_reasons", [])),
                "short_summary": analysis.get("short_summary", ""),
                "customer_sentiment": analysis.get("customer_sentiment", "neutral"),
                "department": analysis.get("department", "unknown"),
                "analysis_status": status,
                "analysis_completed_at": _now_iso(),
            }

            # Only set alert status if this is an actual agent call
            if status == "success":
                payload["alert_email_status"] = (
                    "pending" if analysis.get("has_warning") else "not_needed"
                )
            else:
                payload["alert_email_status"] = "not_needed"
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
        search: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sentiment: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Paginated, filterable list of calls for the dashboard.

        Args:
            limit: Max records to return
            offset: Starting position
            analysis_status: Filter by status (pending, processing, success, failed)
            warnings_only: Only show calls with warnings
            search: Search agent_name, customer_number, or call_id
            date_from: ISO date string for range start
            date_to: ISO date string for range end
            sentiment: Filter by customer_sentiment
        """
        sb = cls.client()
        query = sb.table("call_records").select(
            "id, call_id, agent_name, customer_number, start_time, "
            "duration_seconds, overall_score, customer_sentiment, "
            "has_warning, analysis_status, alert_email_status, created_at"
        )

        # Status filter
        if analysis_status:
            query = query.eq("analysis_status", analysis_status)

        # Warnings filter
        if warnings_only:
            query = query.eq("has_warning", True)

        # Sentiment filter
        if sentiment:
            query = query.eq("customer_sentiment", sentiment)

        # Search filter (agent name, customer number, call_id)
        if search:
            search_term = f"%{search}%"
            # Supabase uses .or_ for OR queries with ilike
            query = query.or_(
                f"agent_name.ilike.{search_term},"
                f"customer_number.ilike.{search_term},"
                f"call_id.ilike.{search_term}"
            )

        # Date range filters
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)

        resp = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return resp.data or []

    @classmethod
    @retry("count_calls")
    def count_calls(
        cls,
        analysis_status: Optional[str] = None,
        warnings_only: bool = False,
        search: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        sentiment: Optional[str] = None,
    ) -> int:
        """
        Get total count of calls matching filters (for pagination).
        Uses .select("*", count="exact") for efficient counting.
        """
        sb = cls.client()
        query = sb.table("call_records").select("*", count="exact")

        # Apply same filters as list_calls
        if analysis_status:
            query = query.eq("analysis_status", analysis_status)
        if warnings_only:
            query = query.eq("has_warning", True)
        if sentiment:
            query = query.eq("customer_sentiment", sentiment)
        if search:
            search_term = f"%{search}%"
            query = query.or_(
                f"agent_name.ilike.{search_term},"
                f"customer_number.ilike.{search_term},"
                f"call_id.ilike.{search_term}"
            )
        if date_from:
            query = query.gte("created_at", date_from)
        if date_to:
            query = query.lte("created_at", date_to)

        resp = query.execute()
        return resp.count if resp.count is not None else 0

    @classmethod
    @retry("get_aggregated_stats")
    def get_aggregated_stats(cls) -> Dict[str, Any]:
        """
        Fetch aggregated statistics using minimal DB queries.
        EXCLUDES non-agent calls (voicemail, automated, disconnects) from all metrics.
        """
        sb = cls.client()

        # Get total calls (exclude non-agent calls)
        total_resp = (
            sb.table("call_records")
            .select("*", count="exact")
            .neq("analysis_status", "not_agent_call")  # EXCLUDE voicemail/disconnects
            .execute()
        )
        total_calls = total_resp.count if total_resp.count is not None else 0

        # Fetch scores to compute average (exclude non-agent calls and null scores)
        score_resp = (
            sb.table("call_records")
            .select("overall_score")
            .neq("analysis_status", "not_agent_call")  # EXCLUDE voicemail/disconnects
            .not_.is_("overall_score", "null")
            .execute()
        )
        scores = [r["overall_score"] for r in score_resp.data if r.get("overall_score")]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # Count warnings (exclude non-agent calls)
        warning_resp = (
            sb.table("call_records")
            .select("*", count="exact")
            .neq("analysis_status", "not_agent_call")  # EXCLUDE voicemail/disconnects
            .eq("has_warning", True)
            .execute()
        )
        warning_count = warning_resp.count if warning_resp.count is not None else 0

        # Sentiment breakdown (exclude non-agent calls)
        sentiment_resp = (
            sb.table("call_records")
            .select("customer_sentiment")
            .neq("analysis_status", "not_agent_call")  # EXCLUDE voicemail/disconnects
            .execute()
        )
        sentiments = {}
        for r in sentiment_resp.data:
            sent = r.get("customer_sentiment", "neutral")
            sentiments[sent] = sentiments.get(sent, 0) + 1

        # Today's calls
        today = datetime.utcnow().date()
        start_today = datetime.combine(today, datetime.min.time())
        calls_today_resp = (
            sb.table("call_records")
            .select("*", count="exact")
            .neq("analysis_status", "not_agent_call")  # EXCLUDE voicemail/disconnects
            .gte("created_at", start_today.isoformat())
            .execute()
        )
        calls_today = (
            calls_today_resp.count if calls_today_resp.count is not None else 0
        )

        # This week's calls
        start_week = datetime.utcnow() - timedelta(days=7)
        calls_week_resp = (
            sb.table("call_records")
            .select("*", count="exact")
            .neq("analysis_status", "not_agent_call")  # EXCLUDE voicemail/disconnects
            .gte("created_at", start_week.isoformat())
            .execute()
        )
        calls_this_week = (
            calls_week_resp.count if calls_week_resp.count is not None else 0
        )

        return {
            "total_calls": total_calls,
            "avg_score": round(avg_score, 2) if avg_score else 0.0,
            "warning_count": warning_count,
            "sentiment_breakdown": sentiments,
            "calls_today": calls_today,
            "calls_this_week": calls_this_week,
        }

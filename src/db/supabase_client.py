"""
Supabase PostgreSQL client for call_records.

Uses Supabase REST interface for all operations.
"""

import logging
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from supabase import create_client, Client

from ..config import settings

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format for Supabase."""
    return datetime.now(timezone.utc).isoformat()


class DatabaseError(Exception):
    pass


class CallRecordsDB:
    """
    Supabase-backed call_records client.
    API remains identical to MySQL version to avoid breaking workers.
    """

    _client: Optional[Client] = None

    @classmethod
    def client(cls) -> Client:
        if cls._client is None:
            url = settings.SUPABASE_URL
            key = settings.SUPABASE_KEY

            if not url or not key:
                raise DatabaseError("Supabase credentials missing")

            cls._client = create_client(url, key)
            logger.info("Supabase client initialized")

        return cls._client

    # ----------------------------------------------------------------------
    # INSERT
    # ----------------------------------------------------------------------
    @classmethod
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
            "transcription_status": "pending",
            "analysis_status": "pending",
            "alert_email_status": "pending",
        }

        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            resp = sb.table("call_records").insert(payload).execute()
        except Exception as e:
            raise DatabaseError(f"Insert failed: {e}")

        if not resp.data:
            raise DatabaseError("Insert failed: Supabase returned no data")

        record_id = resp.data[0]["id"]
        logger.info(f"Inserted call record {record_id}")

        return record_id

    # ----------------------------------------------------------------------
    # QUERY HELPERS
    # ----------------------------------------------------------------------
    @classmethod
    def find_pending_transcription(cls, limit=5) -> List[Dict[str, Any]]:
        sb = cls.client()
        resp = (
            sb.table("call_records")
            .select("*")
            .eq("transcription_status", "pending")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    @classmethod
    def find_pending_analysis(cls, limit=5) -> List[Dict[str, Any]]:
        sb = cls.client()
        resp = (
            sb.table("call_records")
            .select("*")
            .eq("transcription_status", "success")
            .eq("analysis_status", "pending")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    @classmethod
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

    # ----------------------------------------------------------------------
    # UPDATE: TRANSCRIPTION
    # ----------------------------------------------------------------------
    @classmethod
    def update_transcription(
        cls,
        record_id: str,
        transcript: str,
        language=None,
        status="success",
        error=None,
    ):
        sb = cls.client()

        if status == "success":
            payload = {
                "transcript_text": transcript,
                "language_detected": language,
                "transcription_status": "success",
                "transcription_completed_at": _now_iso(),
            }
        else:
            payload = {
                "transcription_status": status,
                "transcription_error": error,
                "transcription_completed_at": _now_iso(),
            }

        sb.table("call_records").update(payload).eq("id", record_id).execute()
        logger.info(f"Updated transcription for {record_id}: {status}")

    # ----------------------------------------------------------------------
    # UPDATE: ANALYSIS
    # ----------------------------------------------------------------------
    @classmethod
    def update_analysis(
        cls, record_id: str, analysis=None, status="success", error=None
    ):
        sb = cls.client()

        if status == "success" and analysis:

            # Encode warning reasons as JSON string for storage
            reasons_json = json.dumps(analysis.get("warning_reasons", []))

            payload = {
                "overall_score": analysis["overall_score"],
                "has_warning": analysis["has_warning"],
                "warning_reasons_json": reasons_json,
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
        logger.info(f"Updated analysis for {record_id}: {status}")

    # ----------------------------------------------------------------------
    # UPDATE: ALERT STATUS
    # ----------------------------------------------------------------------
    @classmethod
    def update_alert_status(cls, record_id: str, status="sent", error=None):
        sb = cls.client()

        if status == "sent":
            payload = {
                "alert_email_status": "sent",
                "alert_sent_at": _now_iso(),
            }
        else:
            payload = {
                "alert_email_status": status,
                "alert_email_error": error,
            }

        sb.table("call_records").update(payload).eq("id", record_id).execute()
        logger.info(f"Updated alert status for {record_id}: {status}")

    # ----------------------------------------------------------------------
    # ADMIN QUERIES
    # ----------------------------------------------------------------------
    @classmethod
    def get_recent_calls(cls, limit: int = 50) -> List[Dict[str, Any]]:
        sb = cls.client()
        resp = (
            sb.table("call_records")
            .select(
                "id, call_id, agent_name, customer_number, start_time, "
                "duration_seconds, overall_score, customer_sentiment, has_warning, "
                "transcription_status, analysis_status, alert_email_status, created_at"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    @classmethod
    def get_call_by_id(cls, record_id: str) -> Optional[Dict[str, Any]]:
        sb = cls.client()
        resp = (
            sb.table("call_records").select("*").eq("id", record_id).single().execute()
        )
        return resp.data

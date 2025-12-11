"""
Admin Dashboard API

Provides REST API for the admin dashboard:
- GET /api/calls — List recent calls
- GET /api/calls/{id} — Get call details
- GET /api/stats — Aggregate statistics
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Dashboard"])


# ------------------------------------------------------------------
# MODELS
# ------------------------------------------------------------------
class CallSummary(BaseModel):
    id: str
    call_id: Optional[str]
    agent_name: Optional[str]
    customer_number: Optional[str]
    start_time: Optional[str]
    duration_seconds: Optional[int]
    overall_score: Optional[int]
    customer_sentiment: Optional[str]
    has_warning: Optional[bool]
    analysis_status: Optional[str]
    created_at: Optional[str]


class CallDetail(BaseModel):
    id: str
    call_id: Optional[str]
    agent_name: Optional[str]
    customer_number: Optional[str]
    start_time: Optional[str]
    duration_seconds: Optional[int]
    recording_url: Optional[str]
    overall_score: Optional[int]
    has_warning: Optional[bool]
    warning_reasons_json: Optional[str]
    short_summary: Optional[str]
    customer_sentiment: Optional[str]
    department: Optional[str]
    analysis_status: Optional[str]
    alert_email_status: Optional[str]
    created_at: Optional[str]


class DashboardStats(BaseModel):
    total_calls: int
    avg_score: float
    warning_count: int
    sentiment_breakdown: dict
    calls_today: int
    calls_this_week: int


# ------------------------------------------------------------------
# ENDPOINTS
# ------------------------------------------------------------------
@router.get("/calls", response_model=List[CallSummary])
async def list_calls(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by analysis_status"),
    warning_only: bool = Query(False, description="Only show calls with warnings"),
):
    """Get list of recent calls."""
    try:
        calls = CallRecordsDB.get_recent_calls(limit=limit + offset)

        # Apply filters
        if status:
            calls = [c for c in calls if c.get("analysis_status") == status]

        if warning_only:
            calls = [c for c in calls if c.get("has_warning")]

        # Apply offset
        calls = calls[offset : offset + limit]

        return calls

    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(500, str(e))


@router.get("/calls/{record_id}", response_model=CallDetail)
async def get_call(record_id: str):
    """Get full details for a specific call."""
    try:
        call = CallRecordsDB.get_call_by_id(record_id)

        if not call:
            raise HTTPException(404, "Call not found")

        return call

    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(500, str(e))


@router.get("/stats", response_model=DashboardStats)
async def get_stats():
    """Get aggregate statistics for the dashboard."""
    try:
        # Get all calls for stats
        calls = CallRecordsDB.get_recent_calls(limit=1000)

        if not calls:
            return DashboardStats(
                total_calls=0,
                avg_score=0.0,
                warning_count=0,
                sentiment_breakdown={},
                calls_today=0,
                calls_this_week=0,
            )

        # Calculate stats
        total = len(calls)

        scores = [c["overall_score"] for c in calls if c.get("overall_score")]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        warning_count = sum(1 for c in calls if c.get("has_warning"))

        # Sentiment breakdown
        sentiments = {}
        for c in calls:
            s = c.get("customer_sentiment", "unknown")
            sentiments[s] = sentiments.get(s, 0) + 1

        # Time-based counts
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)

        calls_today = 0
        calls_this_week = 0

        for c in calls:
            created = c.get("created_at")
            if created:
                try:
                    # Parse ISO timestamp
                    if isinstance(created, str):
                        created = datetime.fromisoformat(created.replace("Z", "+00:00"))

                    if created.replace(tzinfo=None) >= today_start:
                        calls_today += 1
                    if created.replace(tzinfo=None) >= week_start:
                        calls_this_week += 1
                except Exception:
                    pass

        return DashboardStats(
            total_calls=total,
            avg_score=round(avg_score, 2),
            warning_count=warning_count,
            sentiment_breakdown=sentiments,
            calls_today=calls_today,
            calls_this_week=calls_this_week,
        )

    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(500, str(e))


@router.post("/calls/{record_id}/reanalyze")
async def reanalyze_call(record_id: str):
    """Reset a call for re-analysis."""
    try:
        CallRecordsDB.update_analysis_status(record_id, "pending")
        return {"status": "success", "message": "Call queued for re-analysis"}

    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        raise HTTPException(500, str(e))

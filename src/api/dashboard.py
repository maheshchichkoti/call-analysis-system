# src/api/dashboard.py
"""
Admin Dashboard API — Production Version
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Header, Depends
from pydantic import BaseModel

from ..config import settings
from ..db.supabase_client import CallRecordsDB, DatabaseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Dashboard"])


# ------------------------------------------------------------------
# AUTHENTICATION
# ------------------------------------------------------------------
def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, alias="key"),
):
    """
    Verify API key from header or query parameter.
    If DASHBOARD_API_KEY is not set, authentication is disabled.
    """
    required_key = settings.DASHBOARD_API_KEY

    # If no key is configured, allow access (development mode)
    if not required_key:
        return True

    # Check header first, then query param
    provided_key = x_api_key or api_key

    if not provided_key:
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header or ?key= parameter",
        )

    if provided_key != required_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    return True


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
# CALL LIST ENDPOINT
# ------------------------------------------------------------------
@router.get("/calls", response_model=List[CallSummary])
async def list_calls(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, description="Filter by analysis_status"),
    warning_only: bool = Query(False, description="Only calls with warnings"),
    search: Optional[str] = Query(
        None, description="Search agent name, customer, or call ID"
    ),
    date_from: Optional[str] = Query(
        None, description="ISO date string for range start"
    ),
    date_to: Optional[str] = Query(None, description="ISO date string for range end"),
    sentiment: Optional[str] = Query(
        None, description="Filter by sentiment (positive, neutral, negative)"
    ),
    _auth: bool = Depends(verify_api_key),
):
    """
    Paginated + filtered list of calls.
    * Uses DB-level filtering for performance
    * Safe pagination
    * Supports search and advanced filters
    """
    try:
        calls = CallRecordsDB.list_calls(
            limit=limit,
            offset=offset,
            analysis_status=status,
            warnings_only=warning_only,
            search=search,
            date_from=date_from,
            date_to=date_to,
            sentiment=sentiment,
        )
        return calls

    except DatabaseError as e:
        logger.error(f"DB Error: {e}")
        raise HTTPException(500, "Database error")


# ------------------------------------------------------------------
# CALL COUNT ENDPOINT (for pagination)
# ------------------------------------------------------------------
@router.get("/calls/count")
async def count_calls(
    status: Optional[str] = Query(None, description="Filter by analysis_status"),
    warning_only: bool = Query(False, description="Only calls with warnings"),
    search: Optional[str] = Query(
        None, description="Search agent name, customer, or call ID"
    ),
    date_from: Optional[str] = Query(
        None, description="ISO date string for range start"
    ),
    date_to: Optional[str] = Query(None, description="ISO date string for range end"),
    sentiment: Optional[str] = Query(None, description="Filter by sentiment"),
    _auth: bool = Depends(verify_api_key),
):
    """
    Get total count of calls matching filters.
    Used by frontend for pagination UI.
    """
    try:
        total = CallRecordsDB.count_calls(
            analysis_status=status,
            warnings_only=warning_only,
            search=search,
            date_from=date_from,
            date_to=date_to,
            sentiment=sentiment,
        )
        return {"total": total}

    except DatabaseError as e:
        logger.error(f"DB Error: {e}")
        raise HTTPException(500, "Database error")


# ------------------------------------------------------------------
# CALL DETAIL ENDPOINT
# ------------------------------------------------------------------
@router.get("/calls/{record_id}", response_model=CallDetail)
async def get_call(record_id: str, _auth: bool = Depends(verify_api_key)):
    try:
        call = CallRecordsDB.get_call_by_id(record_id)
        if not call:
            raise HTTPException(404, "Call not found")
        return call

    except DatabaseError as e:
        logger.error(f"DB Error: {e}")
        raise HTTPException(500, "Database error")


# ------------------------------------------------------------------
# STATS ENDPOINT
# ------------------------------------------------------------------
@router.get("/stats", response_model=DashboardStats)
async def get_stats(_auth: bool = Depends(verify_api_key)):
    """
    Get dashboard statistics using optimized database aggregation.
    Much more efficient than loading all records into memory.
    """
    try:
        stats = CallRecordsDB.get_aggregated_stats()
        return DashboardStats(**stats)

    except DatabaseError as e:
        logger.error(f"DB Error: {e}")
        raise HTTPException(500, "Database error")


# ------------------------------------------------------------------
# RE-ANALYZE A CALL
# ------------------------------------------------------------------
@router.post("/calls/{record_id}/reanalyze")
async def reanalyze_call(record_id: str, _auth: bool = Depends(verify_api_key)):
    try:
        CallRecordsDB.update_analysis_status(record_id, "pending")
        CallRecordsDB.update_alert_status(record_id, status="pending")
        return {"status": "success", "message": "Call queued for re-analysis"}

    except DatabaseError as e:
        logger.error(f"DB Error: {e}")
        raise HTTPException(500, "Database error")

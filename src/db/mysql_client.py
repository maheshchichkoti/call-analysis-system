# src/db/mysql_client.py
"""
MySQL Database Client for Call Records.

Production-ready with connection pooling and retry logic.
"""

import logging
import uuid
import json
from typing import Dict, Any, List
from mysql.connector import pooling

from ..config import settings

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Custom exception for database operations."""

    pass


class CallRecordsDB:
    """
    MySQL client for call_records table.

    Features:
    - Connection pooling
    - Auto-retry on connection loss
    - Type-safe operations
    """

    _pool = None

    @classmethod
    def get_pool(cls):
        """Get or create connection pool."""
        if cls._pool is None:
            try:
                cls._pool = pooling.MySQLConnectionPool(
                    pool_name="call_analysis_pool",
                    pool_size=5,
                    host=settings.MYSQL_HOST,
                    port=settings.MYSQL_PORT,
                    user=settings.MYSQL_USER,
                    password=settings.MYSQL_PASSWORD,
                    database=settings.MYSQL_DATABASE,
                    charset="utf8mb4",
                    collation="utf8mb4_unicode_ci",
                    autocommit=True,
                )
                logger.info("MySQL connection pool created")
            except Exception as e:
                logger.error(f"Failed to create MySQL pool: {e}")
                raise DatabaseError(f"Database connection failed: {e}")
        return cls._pool

    @classmethod
    def get_connection(cls):
        """Get a connection from the pool."""
        return cls.get_pool().get_connection()

    # =========================================================================
    # CREATE Operations
    # =========================================================================

    @classmethod
    def insert_call_record(cls, call_data: Dict[str, Any]) -> str:
        """
        Insert a new call record.

        Args:
            call_data: Dictionary with call metadata

        Returns:
            The generated record ID
        """
        record_id = call_data.get("id") or str(uuid.uuid4())

        conn = cls.get_connection()
        try:
            cursor = conn.cursor()

            query = """
                INSERT INTO call_records (
                    id, call_id, agent_id, agent_name, customer_number,
                    start_time, end_time, duration_seconds, recording_url,
                    transcription_status, analysis_status, alert_email_status
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """

            values = (
                record_id,
                call_data.get("call_id"),
                call_data.get("agent_id"),
                call_data.get("agent_name"),
                call_data.get("customer_number"),
                call_data.get("start_time"),
                call_data.get("end_time"),
                call_data.get("duration_seconds"),
                call_data.get("recording_url"),
                "pending",  # transcription_status
                "pending",  # analysis_status
                "pending",  # alert_email_status
            )

            cursor.execute(query, values)
            logger.info(f"Inserted call record: {record_id}")
            return record_id

        finally:
            cursor.close()
            conn.close()

    # =========================================================================
    # READ Operations (for workers)
    # =========================================================================

    @classmethod
    def find_pending_transcription(cls, limit: int = 5) -> List[Dict[str, Any]]:
        """Find calls pending transcription."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT * FROM call_records 
                WHERE transcription_status = 'pending'
                ORDER BY created_at ASC
                LIMIT %s
            """

            cursor.execute(query, (limit,))
            return cursor.fetchall()

        finally:
            cursor.close()
            conn.close()

    @classmethod
    def find_pending_analysis(cls, limit: int = 5) -> List[Dict[str, Any]]:
        """Find calls with transcription done, pending analysis."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT * FROM call_records 
                WHERE transcription_status = 'success'
                  AND analysis_status = 'pending'
                ORDER BY created_at ASC
                LIMIT %s
            """

            cursor.execute(query, (limit,))
            return cursor.fetchall()

        finally:
            cursor.close()
            conn.close()

    @classmethod
    def find_pending_alerts(cls, limit: int = 5) -> List[Dict[str, Any]]:
        """Find calls with warnings pending email alert."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT * FROM call_records 
                WHERE analysis_status = 'success'
                  AND has_warning = TRUE
                  AND alert_email_status = 'pending'
                ORDER BY created_at ASC
                LIMIT %s
            """

            cursor.execute(query, (limit,))
            return cursor.fetchall()

        finally:
            cursor.close()
            conn.close()

    # =========================================================================
    # UPDATE Operations
    # =========================================================================

    @classmethod
    def update_transcription(
        cls,
        record_id: str,
        transcript: str,
        language: str = None,
        status: str = "success",
        error: str = None,
    ):
        """Update record with transcription result."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()

            if status == "success":
                query = """
                    UPDATE call_records SET
                        transcript_text = %s,
                        language_detected = %s,
                        transcription_status = %s,
                        transcription_completed_at = NOW()
                    WHERE id = %s
                """
                cursor.execute(query, (transcript, language, status, record_id))
            else:
                query = """
                    UPDATE call_records SET
                        transcription_status = %s,
                        transcription_error = %s,
                        transcription_completed_at = NOW()
                    WHERE id = %s
                """
                cursor.execute(query, (status, error, record_id))

            logger.info(f"Updated transcription for {record_id}: {status}")

        finally:
            cursor.close()
            conn.close()

    @classmethod
    def update_analysis(
        cls,
        record_id: str,
        analysis: Dict[str, Any] = None,
        status: str = "success",
        error: str = None,
    ):
        """Update record with analysis result."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()

            if status == "success" and analysis:
                query = """
                    UPDATE call_records SET
                        overall_score = %s,
                        has_warning = %s,
                        warning_reasons_json = %s,
                        short_summary = %s,
                        customer_sentiment = %s,
                        department = %s,
                        analysis_status = %s,
                        analysis_completed_at = NOW(),
                        alert_email_status = %s
                    WHERE id = %s
                """

                # Set alert status based on warning
                alert_status = (
                    "pending" if analysis.get("has_warning") else "not_needed"
                )

                cursor.execute(
                    query,
                    (
                        analysis.get("overall_score"),
                        analysis.get("has_warning", False),
                        json.dumps(analysis.get("warning_reasons", [])),
                        analysis.get("short_summary"),
                        analysis.get("customer_sentiment"),
                        analysis.get("department"),
                        status,
                        alert_status,
                        record_id,
                    ),
                )
            else:
                query = """
                    UPDATE call_records SET
                        analysis_status = %s,
                        analysis_error = %s,
                        analysis_completed_at = NOW()
                    WHERE id = %s
                """
                cursor.execute(query, (status, error, record_id))

            logger.info(f"Updated analysis for {record_id}: {status}")

        finally:
            cursor.close()
            conn.close()

    @classmethod
    def update_alert_status(
        cls, record_id: str, status: str = "sent", error: str = None
    ):
        """Update alert email status."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()

            if status == "sent":
                query = """
                    UPDATE call_records SET
                        alert_email_status = %s,
                        alert_sent_at = NOW()
                    WHERE id = %s
                """
                cursor.execute(query, (status, record_id))
            else:
                query = """
                    UPDATE call_records SET
                        alert_email_status = %s,
                        alert_email_error = %s
                    WHERE id = %s
                """
                cursor.execute(query, (status, error, record_id))

            logger.info(f"Updated alert status for {record_id}: {status}")

        finally:
            cursor.close()
            conn.close()

    @classmethod
    def get_recent_calls(cls, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent calls for admin dashboard."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor(dictionary=True)

            query = """
                SELECT 
                    id, call_id, agent_name, customer_number,
                    start_time, duration_seconds,
                    overall_score, customer_sentiment, has_warning,
                    transcription_status, analysis_status, alert_email_status,
                    created_at
                FROM call_records 
                ORDER BY created_at DESC
                LIMIT %s
            """

            cursor.execute(query, (limit,))
            return cursor.fetchall()

        finally:
            cursor.close()
            conn.close()

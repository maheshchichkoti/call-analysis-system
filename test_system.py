#!/usr/bin/env python
"""
System Test — Quick verification of all services.

Tests:
1. Configuration
2. Database connection
3. Gemini API (audio analysis)
4. Email service
5. API endpoints
"""

import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent))


def test_config():
    """Test configuration loading."""
    print("\n[1/5] Testing Configuration...")

    from src.config import settings

    issues = settings.validate()

    if issues:
        for issue in issues:
            print(f"  ⚠️  {issue}")
        return False

    print(f"  ✅ Environment: {settings.ENVIRONMENT}")
    print(f"  ✅ Gemini Model: {settings.GEMINI_MODEL}")
    print(f"  ✅ All config valid")
    return True


def test_database():
    """Test Supabase connection."""
    print("\n[2/5] Testing Database...")

    try:
        from src.db.supabase_client import CallRecordsDB

        # Try to fetch recent calls
        calls = CallRecordsDB.get_recent_calls(limit=1)
        print(f"  ✅ Supabase connected")
        print(f"  ✅ Found {len(calls)} call(s) in database")
        return True

    except Exception as e:
        print(f"  ❌ Database error: {e}")
        return False


def test_gemini():
    """Test Gemini API connection."""
    print("\n[3/5] Testing Gemini API...")

    try:
        from src.services.call_analyzer import CallAnalyzer

        analyzer = CallAnalyzer()

        # Quick test with short transcript
        test_transcript = """
        Agent: Hello, thank you for calling. How can I help you today?
        Customer: Hi, I have a question about my bill.
        Agent: Of course, I'd be happy to help with that. Let me look up your account.
        Customer: Thank you.
        Agent: I see the charge here. Is there anything specific you'd like to know?
        Customer: No, that explains it. Thanks for your help!
        Agent: You're welcome! Have a great day.
        """

        result = analyzer.analyze(test_transcript)

        print(f"  ✅ Gemini API connected")
        print(
            f"  ✅ Test analysis: score={result['overall_score']}, sentiment={result['customer_sentiment']}"
        )
        return True

    except Exception as e:
        print(f"  ❌ Gemini error: {e}")
        return False


def test_email():
    """Test email service configuration."""
    print("\n[4/5] Testing Email Service...")

    try:
        from src.services.email_service import EmailService
        from src.config import settings

        if not settings.RESEND_API_KEY:
            print("  ⚠️  RESEND_API_KEY not configured")
            return False

        if not settings.CALL_ALERT_TARGET_EMAIL:
            print("  ⚠️  CALL_ALERT_TARGET_EMAIL not configured")
            return False

        service = EmailService()
        print(f"  ✅ Email service configured")
        print(f"  ✅ Target: {settings.CALL_ALERT_TARGET_EMAIL}")
        return True

    except Exception as e:
        print(f"  ❌ Email error: {e}")
        return False


def test_api():
    """Test API module imports."""
    print("\n[5/5] Testing API Module...")

    try:
        from src.api import zoom_router, dashboard_router

        print(f"  ✅ Zoom webhook router loaded")
        print(f"  ✅ Dashboard API router loaded")
        return True

    except Exception as e:
        print(f"  ❌ API error: {e}")
        return False


def main():
    print("=" * 60)
    print("CALL ANALYSIS SYSTEM — System Test")
    print("=" * 60)

    results = []
    results.append(("Config", test_config()))
    results.append(("Database", test_database()))
    results.append(("Gemini", test_gemini()))
    results.append(("Email", test_email()))
    results.append(("API", test_api()))

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    passed = sum(1 for _, ok in results if ok)
    total = len(results)

    for name, ok in results:
        status = "✅ PASS" if ok else "❌ FAIL"
        print(f"  {name}: {status}")

    print(f"\n  {passed}/{total} tests passed")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

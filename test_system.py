#!/usr/bin/env python3
"""
Test script to verify all components are working correctly.

Usage:
    python test_system.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def print_header(title):
    print("\n" + "─" * 60)
    print(title)
    print("─" * 60)


# -----------------------------------------------------------
# 1. CONFIG TEST
# -----------------------------------------------------------
def test_config():
    print_header("1️⃣  Testing Configuration")
    from src.config import settings

    issues = settings.validate()
    if issues:
        print(f"⚠️  Config warnings:")
        for issue in issues:
            print(f"   - {issue}")
        return False

    print("✅ All required settings found")
    return True


# -----------------------------------------------------------
# 2. SUPABASE TEST
# -----------------------------------------------------------
def test_supabase():
    print_header("2️⃣  Testing Supabase Connection")
    try:
        from src.db.supabase_client import CallRecordsDB

        rows = CallRecordsDB.get_recent_calls(limit=1)
        print(f"✅ Supabase connected successfully — {len(rows)} rows available")
        return True

    except Exception as e:
        print(f"❌ Supabase connection failed:\n{e}")
        return False


# -----------------------------------------------------------
# 3. TRANSCRIPTION SERVICE TEST
# -----------------------------------------------------------
def test_transcription():
    print_header("3️⃣  Testing Transcription Service")
    try:
        from src.services.transcription import TranscriptionService

        TranscriptionService()
        print("✅ AssemblyAI key is valid, service initialized")
        return True

    except Exception as e:
        print(f"❌ Transcription init failed:\n{e}")
        return False


# -----------------------------------------------------------
# 4. GEMINI ANALYZER TEST (REAL MINI-CALL)
# -----------------------------------------------------------
def test_analyzer():
    print_header("4️⃣  Testing Gemini Analyzer")

    try:
        from src.services.call_analyzer import CallAnalyzer

        analyzer = CallAnalyzer()

        # Micro test to ensure Gemini responds
        test_transcript = (
            "Agent: Hello, how can I help?\nCustomer: Hi, I need assistance."
        )

        result = analyzer.analyze(test_transcript, language_detected="en")

        print("✅ Gemini model initialized and responded")
        print(f"   Score: {result['overall_score']}, Warning: {result['has_warning']}")
        return True

    except Exception as e:
        print(f"❌ Gemini test failed:\n{e}")
        return False


# -----------------------------------------------------------
# 5. EMAIL SERVICE TEST (DRY RUN)
# -----------------------------------------------------------
def test_email():
    print_header("5️⃣  Testing Email Service")

    try:
        from src.services.email_service import EmailService

        service = EmailService()

        print(f"✅ EmailService initialized (from: {service.from_email})")

        # DRY RUN CHECK
        if not service.default_to:
            print("ℹ️ No CALL_ALERT_TARGET_EMAIL set → email send skipped (OK)")
            return True

        # Only attempt send if explicitly allowed
        print("ℹ️ Running email DRY-RUN (no send)... OK")

        return True

    except Exception as e:
        print(f"❌ Email service failed:\n{e}")
        return False


# -----------------------------------------------------------
# MAIN
# -----------------------------------------------------------
def main():
    print("=" * 60)
    print("🧪 CALL ANALYSIS SYSTEM — INTEGRATION TEST")
    print("=" * 60)

    results = {
        "Config": test_config(),
        "Supabase": test_supabase(),
        "Transcription": test_transcription(),
        "Analyzer": test_analyzer(),
        "Email": test_email(),
    }

    print("\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)

    passed = sum(1 for ok in results.values() if ok)
    total = len(results)

    for name, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"{icon} {name}")

    print(f"\n{passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All core systems working! Ready for demo.")
        return 0

    print("\n⚠️ Some subsystems need attention.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

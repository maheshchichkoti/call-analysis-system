#!/usr/bin/env python3
"""
Test script to verify all components are working correctly.

Usage:
    python test_system.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_config():
    """Test configuration loading."""
    print("1️⃣  Testing Configuration...")
    from src.config import settings

    issues = settings.validate()
    if issues:
        print(f"   ⚠️  Config warnings: {issues}")
    else:
        print("   ✅ All required settings present")

    return len(issues) == 0


def test_supabase():
    """Test Supabase connection."""
    print("\n2️⃣  Testing Supabase Connection...")
    try:
        from src.db.supabase_client import CallRecordsDB

        # Try to get recent calls (should work even if empty)
        calls = CallRecordsDB.get_recent_calls(limit=1)
        print(f"   ✅ Supabase connected! Found {len(calls)} recent calls")
        return True
    except Exception as e:
        print(f"   ❌ Supabase error: {e}")
        return False


def test_transcription():
    """Test AssemblyAI connection."""
    print("\n3️⃣  Testing Transcription Service...")
    try:
        from src.services.transcription import TranscriptionService

        TranscriptionService()
        print("   ✅ TranscriptionService initialized (AssemblyAI key valid)")
        return True
    except Exception as e:
        print(f"   ❌ Transcription error: {e}")
        return False


def test_analyzer():
    """Test Gemini analyzer."""
    print("\n4️⃣  Testing Call Analyzer...")
    try:
        from src.services.call_analyzer import CallAnalyzer

        analyzer = CallAnalyzer()
        print(f"   ✅ CallAnalyzer initialized (model: {analyzer.model_name})")
        return True
    except Exception as e:
        print(f"   ❌ Analyzer error: {e}")
        return False


def test_email():
    """Test Resend email service."""
    print("\n5️⃣  Testing Email Service...")
    try:
        from src.services.email_service import EmailService

        service = EmailService()
        print(f"   ✅ EmailService initialized (from: {service.from_email})")
        return True
    except Exception as e:
        print(f"   ❌ Email error: {e}")
        return False


def main():
    print("=" * 60)
    print("🧪 CALL ANALYSIS SYSTEM - VERIFICATION")
    print("=" * 60)

    results = {
        "Config": test_config(),
        "Supabase": test_supabase(),
        "Transcription": test_transcription(),
        "Analyzer": test_analyzer(),
        "Email": test_email(),
    }

    print("\n" + "=" * 60)
    print("📊 RESULTS")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for name, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"   {status} {name}")

    print(f"\n   {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All systems ready for production!")
        return 0
    else:
        print("\n⚠️  Some issues need to be resolved")
        return 1


if __name__ == "__main__":
    sys.exit(main())

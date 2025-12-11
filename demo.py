#!/usr/bin/env python
"""
Call Analysis Demo — Single Gemini Call

Demonstrates the complete call analysis pipeline:
1. Load audio file
2. Analyze with single Gemini 2.0 Flash call
3. Display results
4. Save to database
5. Send email alert (if warning)
"""

import sys
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import settings
from src.services.call_analyzer import CallAnalyzer, CallAnalysisError
from src.services.email_service import EmailService
from src.db.supabase_client import CallRecordsDB, DatabaseError


def print_banner():
    print("\n" + "=" * 60)
    print("� CALL ANALYSIS SYSTEM — Single Gemini Call Demo")
    print("=" * 60 + "\n")


def validate_audio_file(path: str) -> Path:
    """Validate that the audio file exists."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    if not p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg", ".flac"):
        raise ValueError(f"Unsupported audio format: {p.suffix}")
    return p


def run_demo(audio_path: str, agent_name: str = None, save_to_db: bool = True):
    """Run the complete demo pipeline."""

    print_banner()

    # Step 1: Validate audio file
    print("📂 Step 1: Validating audio file...")
    audio_file = validate_audio_file(audio_path)
    print(f"   ✅ Found: {audio_file.name} ({audio_file.stat().st_size / 1024:.1f} KB)")

    # Step 2: Analyze with Gemini
    print("\n� Step 2: Analyzing with Gemini 2.0 Flash...")
    print("   Uploading audio to Gemini Files API...")

    analyzer = CallAnalyzer()
    analysis = analyzer.analyze_audio(
        audio_path=str(audio_file),
        agent_name=agent_name,
    )

    print("   ✅ Analysis complete!")

    # Step 3: Display results
    print("\n" + "─" * 60)
    print("📊 ANALYSIS RESULTS")
    print("─" * 60)

    score = analysis["overall_score"]
    stars = "⭐" * score + "☆" * (5 - score)
    print(f"   Score: {stars} ({score}/5)")

    sentiment = analysis["customer_sentiment"]
    sentiment_emoji = {"positive": "😊", "neutral": "😐", "negative": "😠"}.get(
        sentiment, "❓"
    )
    print(f"   Sentiment: {sentiment_emoji} {sentiment.title()}")

    print(f"   Department: 🏢 {analysis['department'].title()}")

    if analysis["has_warning"]:
        print(f"\n   🚨 WARNING: {', '.join(analysis['warning_reasons'])}")
    else:
        print("\n   ✅ No warnings detected")

    print(f"\n   📝 Summary: {analysis['short_summary']}")
    print("─" * 60)

    # Step 4: Save to database
    record_id = None
    if save_to_db:
        print("\n💾 Step 3: Saving to database...")
        try:
            # Insert initial record
            record_id = CallRecordsDB.insert_call_record({
                "call_id": f"demo_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "agent_name": agent_name or "Demo Agent",
                "duration_seconds": 0,
                "recording_url": str(audio_file.absolute()),
            })

            # Update with analysis results
            CallRecordsDB.update_analysis(record_id, analysis=analysis, status="success")

            print(f"   ✅ Saved! Record ID: {record_id}")

        except DatabaseError as e:
            print(f"   ⚠️ Database save failed: {e}")

    # Step 5: Send email alert if warning
    if analysis["has_warning"]:
        print("\n📧 Step 4: Sending email alert...")
        try:
            email_service = EmailService()
            email_service.send_call_alert(
                call_data={
                    "id": record_id or "demo",
                    "call_id": f"demo_{datetime.now().strftime('%Y%m%d')}",
                    "agent_name": agent_name or "Demo Agent",
                    "overall_score": analysis["overall_score"],
                    "has_warning": True,
                    "warning_reasons": analysis["warning_reasons"],
                    "short_summary": analysis["short_summary"],
                    "customer_sentiment": analysis["customer_sentiment"],
                }
            )
            print("   ✅ Alert email sent!")
        except Exception as e:
            print(f"   ⚠️ Email failed: {e}")
    else:
        print("\n📧 Step 4: No alert needed (no warning)")

    # Save JSON output
    output_file = Path("demo_output.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)
    print(f"\n💾 JSON saved to: {output_file}")

    print("\n" + "=" * 60)
    print("✅ DEMO COMPLETE!")
    print("=" * 60 + "\n")

    return analysis


def main():
    parser = argparse.ArgumentParser(
        description="Call Analysis Demo — Single Gemini Call",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python demo.py --audio call.mp3
  python demo.py --audio call.mp3 --agent "John Smith"
  python demo.py --audio call.mp3 --no-save
        """,
    )
    parser.add_argument(
        "--audio", "-a",
        required=True,
        help="Path to audio file (MP3, WAV, M4A)",
    )
    parser.add_argument(
        "--agent", "-n",
        default=None,
        help="Agent name for context",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Skip saving to database",
    )

    args = parser.parse_args()

    try:
        run_demo(
            audio_path=args.audio,
            agent_name=args.agent,
            save_to_db=not args.no_save,
        )
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except CallAnalysisError as e:
        print(f"❌ Analysis failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

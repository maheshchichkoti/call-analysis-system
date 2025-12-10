#!/usr/bin/env python3
"""
Call Analysis Demo Script.

End-to-end demo:
1. Transcribes audio (Hebrew/Arabic/English)
2. Normalizes transcript with diarization into Agent/Customer format
3. Analyzes with Gemini
4. Saves results to Supabase
5. Optionally sends email alert
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent))

from src.services.transcription import TranscriptionService, TranscriptionError
from src.services.call_analyzer import CallAnalyzer, CallAnalysisError
from src.services.email_service import EmailService, EmailError
from src.db.supabase_client import CallRecordsDB
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_demo(audio_path: str, send_email_to: str = None) -> dict:
    print("\n" + "=" * 60)
    print("🎯 CALL ANALYSIS DEMO")
    print("=" * 60 + "\n")

    # Validate audio file
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    file_size_mb = Path(audio_path).stat().st_size / (1024 * 1024)
    print(f"📁 Audio file: {audio_path}")
    print(f"📊 File size: {file_size_mb:.2f} MB\n")

    # -------------------------------------------------------------------------
    # STEP 1 — TRANSCRIPTION
    # -------------------------------------------------------------------------
    print("─" * 40)
    print("📝 STEP 1: TRANSCRIBING AUDIO")
    print("─" * 40)

    try:
        transcription_service = TranscriptionService()

        print("⏳ Uploading and transcribing...")
        result = transcription_service.transcribe_file(
            audio_path,
            language_code=None,  # Auto-detect language
            speakers_expected=2,
        )

        # Clean normalized Agent/Customer transcript
        transcript = result["text"]
        language = result.get("language_code", "unknown")
        duration = result.get("audio_duration", 0)
        raw_text = result.get("raw_text", "")
        utterances = result.get("utterances", [])

        print("✅ Transcription complete!")
        print(f"   Language: {language}")
        print(f"   Duration: {duration}s")
        print(f"   Clean transcript length: {len(transcript)} chars")

        # -------- Better formatted preview --------
        print("\n📜 Transcript Preview")
        print("─" * 40)

        clean_lines = transcript.split("\n")

        # Show first 5 lines + last 2 lines
        if len(clean_lines) > 7:
            preview = clean_lines[:5] + ["..."] + clean_lines[-2:]
        else:
            preview = clean_lines

        for line in preview:
            print("🗣️ ", line)

        print("─" * 40 + "\n")

    except TranscriptionError as e:
        print(f"❌ Transcription failed: {e}")
        raise

    # -------------------------------------------------------------------------
    # STEP 2 — GEMINI AI ANALYSIS
    # -------------------------------------------------------------------------
    print("─" * 40)
    print("🤖 STEP 2: ANALYZING WITH GEMINI")
    print("─" * 40)

    try:
        analyzer = CallAnalyzer()
        print("⏳ Sending to Gemini...")

        analysis = analyzer.analyze(
            transcript=transcript,
            language_detected=language,
        )

        print("✅ Analysis complete!\n")

    except CallAnalysisError as e:
        print(f"❌ Analysis failed: {e}")
        raise

    # -------------------------------------------------------------------------
    # STEP 3 — SHOW RESULTS
    # -------------------------------------------------------------------------
    print("─" * 40)
    print("📊 STEP 3: RESULTS")
    print("─" * 40)

    final_result = {
        "overall_score": analysis["overall_score"],
        "has_warning": analysis["has_warning"],
        "warning_reasons": analysis["warning_reasons"],
        "short_summary": analysis["short_summary"],
        "customer_sentiment": analysis["customer_sentiment"],
        "department": analysis["department"],
        # Metadata
        "language_detected": language,
        "audio_duration_seconds": duration,
        "transcript_length": len(transcript),
        "analyzed_at": datetime.now().isoformat(),
    }

    print(json.dumps(final_result, indent=2, ensure_ascii=False))

    # Save outputs
    with open("demo_output.json", "w", encoding="utf-8") as f:
        json.dump(final_result, f, indent=2, ensure_ascii=False)

    with open("demo_output_full.json", "w", encoding="utf-8") as f:
        json.dump(
            {**final_result, "transcript_text": transcript, "raw_text": raw_text},
            f,
            indent=2,
            ensure_ascii=False,
        )

    print("\n💾 Result saved to demo_output.json and demo_output_full.json")

    # -------------------------------------------------------------------------
    # STEP 4 — DATABASE SAVE
    # -------------------------------------------------------------------------
    print("\n" + "─" * 40)
    print("💾 STEP 4: SAVING TO DATABASE")
    print("─" * 40)

    try:
        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            db_data = {
                "call_id": f"demo-{int(datetime.now().timestamp())}",
                "agent_id": "demo-001",
                "agent_name": "Demo Agent",
                "customer_number": "+972-55-123-4567",
                "start_time": datetime.now().isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": duration,
                "recording_url": "https://example.com/demo-recording.m4a",
            }

            print("⏳ Inserting metadata...")

            record_id = CallRecordsDB.insert_call_record(db_data)

            # Update transcription
            CallRecordsDB.update_transcription(
                record_id,
                transcript=transcript,
                language=language,
                status="success",
            )

            # Update analysis
            CallRecordsDB.update_analysis(
                record_id,
                analysis=analysis,
                status="success",
            )

            print(f"✅ Saved to Supabase! Record ID: {record_id}")

        else:
            print("ℹ️ No Supabase credentials — skipping DB save")

    except Exception as e:
        print(f"⚠️ Database save failed: {e}")

    # -------------------------------------------------------------------------
    # STEP 5 — EMAIL ALERT (OPTIONAL)
    # -------------------------------------------------------------------------
    if send_email_to or analysis["has_warning"]:
        print("\n" + "─" * 40)
        print("📧 STEP 5: EMAIL ALERT")
        print("─" * 40)

        if analysis["has_warning"]:
            try:
                email_service = EmailService()
                call_data = {
                    "agent_name": "Demo Agent",
                    "agent_id": "demo-001",
                    "customer_number": "+972-XXX-XXXX",
                    "start_time": datetime.now().isoformat(),
                    "end_time": datetime.now().isoformat(),
                    "duration_seconds": duration,
                    "overall_score": analysis["overall_score"],
                    "has_warning": analysis["has_warning"],
                    "warning_reasons": analysis["warning_reasons"],
                    "short_summary": analysis["short_summary"],
                    "customer_sentiment": analysis["customer_sentiment"],
                    "transcript_text": transcript[:3000],
                }

                if send_email_to:
                    email_service.send_call_alert(call_data, send_email_to)
                    print(f"✅ Alert email sent to: {send_email_to}")
                else:
                    print("⚠️ Warning detected but no email configured")

            except EmailError as e:
                print(f"❌ Email failed: {e}")
        else:
            print("ℹ️ No warnings — skipping email")

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("🎉 DEMO COMPLETE!")
    print("=" * 60)

    score = analysis["overall_score"]
    score_bar = "⭐" * score + "☆" * (5 - score)

    print(
        f"""
📊 Quick Summary:
   Score: {score_bar} ({score}/5)
   Sentiment: {analysis['customer_sentiment'].upper()}
   Warnings: {'YES ⚠️' if analysis['has_warning'] else 'No'}
   Department: {analysis['department']}
   
   Summary: {analysis['short_summary']}
"""
    )

    return final_result


def main():
    parser = argparse.ArgumentParser(description="Call Analysis Demo")
    parser.add_argument("--audio", "-a", required=True)
    parser.add_argument("--email", "-e", required=False)
    args = parser.parse_args()

    try:
        run_demo(args.audio, args.email)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

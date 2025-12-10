#!/usr/bin/env python3
"""
Call Analysis Demo Script.

Simple end-to-end demo that:
1. Transcribes an audio file (Hebrew/Arabic)
2. Analyzes with Gemini AI
3. Outputs JSON result
4. Optionally sends email alert

Usage:
    python demo.py --audio path/to/audio.m4a
    python demo.py --audio path/to/audio.m4a --email alert@company.com
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.services.transcription import TranscriptionService, TranscriptionError
from src.services.call_analyzer import CallAnalyzer, CallAnalysisError
from src.services.email_service import EmailService, EmailError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_demo(audio_path: str, send_email_to: str = None) -> dict:
    """
    Run the full demo pipeline.

    Args:
        audio_path: Path to the audio file
        send_email_to: Optional email address for alert

    Returns:
        Analysis result dictionary
    """
    print("\n" + "=" * 60)
    print("🎯 CALL ANALYSIS DEMO")
    print("=" * 60 + "\n")

    # Validate file exists
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    file_size_mb = Path(audio_path).stat().st_size / (1024 * 1024)
    print(f"📁 Audio file: {audio_path}")
    print(f"📊 File size: {file_size_mb:.2f} MB\n")

    # =========================================================================
    # STEP 1: TRANSCRIPTION
    # =========================================================================
    print("─" * 40)
    print("📝 STEP 1: TRANSCRIBING AUDIO")
    print("─" * 40)

    try:
        transcription_service = TranscriptionService()

        print("⏳ Uploading and transcribing... (this may take a few minutes)")
        result = transcription_service.transcribe_file(
            audio_path,
            language_code=None,  # Auto-detect (supports Hebrew/Arabic)
            speaker_labels=True,
            speakers_expected=2,
        )

        transcript = result["text"]
        language = result.get("language_code", "unknown")
        duration = result.get("audio_duration", 0)

        print("✅ Transcription complete!")
        print(f"   Language detected: {language}")
        print(f"   Duration: {duration}s")
        print(f"   Transcript length: {len(transcript)} characters")

        # Display nicely formatted speaker transcript
        utterances = result.get("utterances", [])
        print("\n📜 Transcript Preview:")
        print("─" * 40)

        if utterances:
            # Show first 5 and last 2 exchanges for preview
            preview_utterances = utterances[:5]
            if len(utterances) > 7:
                preview_utterances.extend([{"speaker": "...", "text": "..."}])
                preview_utterances.extend(utterances[-2:])
            else:
                preview_utterances = utterances

            for utt in preview_utterances:
                speaker = f"Speaker {utt.get('speaker', '?')}"
                text = utt.get("text", "")
                print(f"🗣️  {speaker}: {text}")
        else:
            # Fallback for no diarization
            print(f"{transcript[:500]}...")

        print("─" * 40 + "\n")

    except TranscriptionError as e:
        print(f"❌ Transcription failed: {e}")
        raise

    # =========================================================================
    # STEP 2: AI ANALYSIS
    # =========================================================================
    print("─" * 40)
    print("🤖 STEP 2: ANALYZING WITH GEMINI AI")
    print("─" * 40)

    try:
        analyzer = CallAnalyzer()

        print("⏳ Sending to Gemini...")
        analysis = analyzer.analyze(transcript=transcript, language_detected=language)

        print("✅ Analysis complete!\n")

    except CallAnalysisError as e:
        print(f"❌ Analysis failed: {e}")
        raise

    # =========================================================================
    # STEP 3: RESULTS
    # =========================================================================
    print("─" * 40)
    print("📊 STEP 3: RESULTS")
    print("─" * 40)

    # Build final result
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

    # Pretty print result
    print(json.dumps(final_result, indent=2, ensure_ascii=False))

    # Save to file
    output_file = "demo_output.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_result, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Result saved to: {output_file}")

    # Also save full result with transcript
    full_output_file = "demo_output_full.json"
    full_result = {**final_result, "transcript_text": transcript}
    with open(full_output_file, "w", encoding="utf-8") as f:
        json.dump(full_result, f, indent=2, ensure_ascii=False)

    print(f"💾 Full result (with transcript) saved to: {full_output_file}")

    # =========================================================================
    # STEP 4: DATABASE INTEGRATION
    # =========================================================================
    print("─" * 40)
    print("💾 STEP 4: SAVING TO DATABASE")
    print("─" * 40)

    try:
        from src.db.supabase_client import CallRecordsDB
        from src.config import settings

        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            # Prepare data for DB
            db_record = {
                "call_id": f"demo-{int(datetime.now().timestamp())}",
                "agent_id": "demo-001",
                "agent_name": "Demo Agent",
                "customer_number": "+972-55-123-4567",
                "start_time": datetime.now().isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": duration,
                "recording_url": "https://example.com/demo-recording.m4a",  # Placeholder
                "transcript_text": transcript,
                "language_detected": language,
                # Analysis results
                "overall_score": analysis["overall_score"],
                "has_warning": analysis["has_warning"],
                "warning_reasons": analysis[
                    "warning_reasons"
                ],  # JSON dump handled by client? No, client expects dict for this field if updated separately, but insert expects fields.
                # Actually wait, insert_call_record in supabase_client.py only takes metadata.
                # It sets status to pending. We need a way to insert FULL record or update it immediately.
                # Let's check supabase_client.py again.
            }

            # The current insertion logic in supabase_client.py is designed for the "worker" flow
            # (insert metadata -> pending -> worker updates).
            # For the demo, we want to simulate the whole thing or just insert the final result.

            # Let's just insert the metadata and then immediately update it with the results we already have.
            print("⏳ Inserting record into Supabase...")
            record_id = CallRecordsDB.insert_call_record(db_record)

            # Update transcription
            CallRecordsDB.update_transcription(
                record_id, transcript=transcript, language=language, status="success"
            )

            # Update analysis
            CallRecordsDB.update_analysis(
                record_id, analysis=analysis, status="success"
            )

            print(f"✅ Record saved to database! ID: {record_id}")

        else:
            print("ℹ️ Supabase credentials not found, skipping database save")

    except Exception as e:
        print(f"⚠️ Database save failed: {e}")

    # =========================================================================
    # STEP 5: EMAIL ALERT (Optional)
    # =========================================================================
    if send_email_to or analysis["has_warning"]:
        print("\n" + "─" * 40)
        print("📧 STEP 4: EMAIL ALERT")
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
                    "duration_seconds": duration or 0,
                    "overall_score": analysis["overall_score"],
                    "has_warning": analysis["has_warning"],
                    "warning_reasons": analysis["warning_reasons"],
                    "short_summary": analysis["short_summary"],
                    "customer_sentiment": analysis["customer_sentiment"],
                    "transcript_text": transcript[:3000],  # Limit transcript length
                }

                recipient = send_email_to or "No email configured"
                logger.info(
                    f"Preparing alert for {recipient}"
                )  # Log it to use the variable
                if send_email_to:
                    email_service.send_call_alert(call_data, send_email_to)
                    print(f"✅ Alert email sent to: {send_email_to}")
                else:
                    print("⚠️ Warning detected but no email configured")
                    print("   Use --email flag to send alert")

            except EmailError as e:
                print(f"❌ Email failed: {e}")
        else:
            print("ℹ️ No warnings detected, skipping email alert")

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 60)
    print("🎉 DEMO COMPLETE!")
    print("=" * 60)

    # Score indicator
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
    parser = argparse.ArgumentParser(
        description="Call Analysis Demo - Transcribe and analyze call recordings"
    )
    parser.add_argument(
        "--audio",
        "-a",
        required=True,
        help="Path to the audio file (MP3, M4A, WAV, etc.)",
    )
    parser.add_argument(
        "--email",
        "-e",
        required=False,
        help="Email address to send alert if warnings detected",
    )

    args = parser.parse_args()

    try:
        run_demo(args.audio, args.email)
        sys.exit(0)
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

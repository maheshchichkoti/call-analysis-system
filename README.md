# Call Analysis System

A production-ready system that:

1. Transcribes Zoom Phone call recordings (Hebrew/Arabic)
2. Analyzes transcripts with Gemini AI for scoring and warnings
3. Sends email alerts for warning calls

## Quick Start (Demo)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy .env.example to .env and fill in your keys
cp .env.example .env

# 3. Run the demo with a sample audio file
python demo.py --audio path/to/your/audio.m4a
```

## Features

- **Transcription**: AssemblyAI with Hebrew/Arabic support
- **AI Analysis**: Gemini 1.5 Flash for cost-effective analysis
- **Email Alerts**: Resend API for reliable email delivery
- **Configurable Prompts**: Analysis prompt via environment variable
- **Production Ready**: Error handling, logging, retry logic

## Project Structure

```
call-analysis-system/
├── demo.py                 # Simple demo script
├── run_workers.py          # Background worker runner
├── src/
│   ├── config.py           # Configuration management
│   ├── services/
│   │   ├── transcription.py    # AssemblyAI transcription
│   │   ├── call_analyzer.py    # Gemini AI analysis
│   │   └── email_service.py    # Resend email alerts
│   ├── workers/
│   │   ├── transcription_worker.py
│   │   ├── analysis_worker.py
│   │   └── alert_worker.py
│   ├── db/
│   │   └── mysql_client.py     # Database operations
│   └── api/
│       └── webhooks.py         # Zoom webhook handler
├── schema.sql              # Database schema
├── requirements.txt
└── .env.example
```

## Environment Variables

See `.env.example` for all required configuration.

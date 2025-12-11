# Call Analysis System

AI-powered call quality analysis using **Gemini 2.0 Flash** — Single API call for audio analysis.

## Features

- 🎧 **Single Gemini Call** — Upload audio, get analysis (no separate transcription)
- 📊 **Quality Scoring** — 1-5 score with detailed breakdown
- ⚠️ **Warning Detection** — Automatic flagging of concerning calls
- 📧 **Email Alerts** — SMTP-based notifications for flagged calls
- 🎯 **Zoom Phone Integration** — Webhook support for automatic capture
- 📱 **Admin Dashboard** — Real-time call monitoring UI
- 🐳 **Docker Ready** — One command deployment

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Test system
python test_system.py

# Run demo
python demo.py --audio call.mp3
```

## Production Deployment

```bash
# With Docker
docker-compose up -d

# Or manually
python main.py &          # API server
python run_workers.py &   # Background workers
```

## API Endpoints

| Endpoint          | Method | Description          |
| ----------------- | ------ | -------------------- |
| `/`               | GET    | Dashboard UI         |
| `/health`         | GET    | Health check         |
| `/docs`           | GET    | API documentation    |
| `/webhook/zoom`   | POST   | Zoom Phone webhook   |
| `/api/calls`      | GET    | List recent calls    |
| `/api/calls/{id}` | GET    | Get call details     |
| `/api/stats`      | GET    | Dashboard statistics |

## Architecture

```
Zoom Phone Call → Webhook → Supabase (pending)
                              ↓
                        Analysis Worker
                              ↓
                     Gemini 2.0 Flash (audio → JSON)
                              ↓
                     Supabase (results) → Email Alert (if warning)
                              ↓
                        Dashboard UI
```

## Project Structure

```
call-analysis-system/
├── main.py              # FastAPI server
├── run_workers.py       # Background workers
├── demo.py              # Demo script
├── Dockerfile           # Docker build
├── docker-compose.yml   # Docker orchestration
├── src/
│   ├── api/             # API routes
│   ├── services/        # Business logic
│   ├── workers/         # Background jobs
│   └── db/              # Database client
└── static/              # Dashboard UI
```

## Configuration

See [.env.example](.env.example) for all available settings.

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for cloud deployment instructions.

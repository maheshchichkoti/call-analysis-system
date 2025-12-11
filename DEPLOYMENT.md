# Deployment Guide

## Quick Deploy with Docker

### 1. Build and Run

```bash
# Build the image
docker-compose build

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f
```

### 2. Check Status

```bash
# Check running containers
docker-compose ps

# Check health
curl http://localhost:8000/health
```

### 3. Stop Services

```bash
docker-compose down
```

---

## Deploy to Cloud

### Option A: Railway.app (Easiest)

1. Push to GitHub
2. Go to [railway.app](https://railway.app)
3. Connect GitHub repo
4. Add environment variables
5. Deploy!

### Option B: DigitalOcean App Platform

1. Push to GitHub
2. Create new App in DigitalOcean
3. Select repo → Docker
4. Add environment variables
5. Deploy

### Option C: AWS EC2

```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@your-ec2-ip

# Install Docker
sudo apt update && sudo apt install -y docker.io docker-compose

# Clone repo
git clone https://github.com/your-repo/call-analysis-system.git
cd call-analysis-system

# Copy .env file
nano .env  # paste your config

# Start
sudo docker-compose up -d
```

---

## Environment Variables Required

```env
# Database
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=xxx

# AI
GEMINI_API_KEY=xxx
GEMINI_MODEL=gemini-2.0-flash

# Email (SMTP)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=xxx@gmail.com
SMTP_PASSWORD=xxx
CALL_ALERT_TARGET_EMAIL=manager@company.com

# Zoom
ZOOM_WEBHOOK_SECRET_TOKEN=xxx

# Server
ENVIRONMENT=production
```

---

## Webhook URL

After deployment, update Zoom webhook URL:

```
https://YOUR-DOMAIN/webhook/zoom
```

---

## Monitoring

- **Dashboard**: `https://YOUR-DOMAIN/`
- **API Docs**: `https://YOUR-DOMAIN/docs`
- **Health**: `https://YOUR-DOMAIN/health`

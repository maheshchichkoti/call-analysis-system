"""
Call Analysis System — FastAPI Server (Production Ready)

Responsibilities:
- Register API routers (Zoom Webhooks + Dashboard API)
- Serve static dashboard
- Centralized logging
- CORS policy
- Health + config endpoints
- Startup validation
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.api.zoom_webhook import router as zoom_router
from src.api.dashboard import router as dashboard_router


# -------------------------------------------------------------------
# LOGGING
# -------------------------------------------------------------------
LOG_LEVEL = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("main")


# -------------------------------------------------------------------
# APP FACTORY
# -------------------------------------------------------------------
def create_app() -> FastAPI:
    app = FastAPI(
        title="Call Analysis System",
        description="AI-powered call quality analysis with Gemini 2.0 Flash",
        version="2.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ---------------------------------------------------------------
    # CORS (tighten for production if needed)
    # ---------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.ENVIRONMENT != "production" else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------
    # ROUTERS
    # ---------------------------------------------------------------
    app.include_router(zoom_router)
    app.include_router(dashboard_router)

    # ---------------------------------------------------------------
    # STATIC FILES
    # ---------------------------------------------------------------
    static_dir = Path("static")
    if static_dir.exists():
        logger.info(f"Serving static files from {static_dir.resolve()}")
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ---------------------------------------------------------------
    # ROOT + STATUS ENDPOINTS
    # ---------------------------------------------------------------
    @app.get("/")
    async def root():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {
            "service": "Call Analysis System",
            "version": "2.0.0",
            "docs": "/docs",
        }

    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "version": "2.0.0",
            "env": settings.ENVIRONMENT,
        }

    @app.get("/config")
    async def config_status():
        return {
            "supabase": bool(settings.SUPABASE_URL and settings.SUPABASE_KEY),
            "gemini": bool(settings.GEMINI_API_KEY),
            "smtp": bool(settings.SMTP_HOST and settings.SMTP_USER),
            "zoom_webhook": bool(settings.ZOOM_WEBHOOK_SECRET_TOKEN),
            "model": settings.GEMINI_MODEL,
        }

    # ---------------------------------------------------------------
    # STARTUP VALIDATION
    # ---------------------------------------------------------------
    @app.on_event("startup")
    async def on_startup():
        logger.info("🚀 Starting Call Analysis System...")
        issues = settings.validate()
        if issues:
            for issue in issues:
                logger.warning(f"[CONFIG WARNING] {issue}")
        logger.info("Startup complete")

    @app.on_event("shutdown")
    async def on_shutdown():
        logger.info("🛑 Shutting down Call Analysis System...")

    return app


app = create_app()


# -------------------------------------------------------------------
# RUN SERVER (Local Dev)
# -------------------------------------------------------------------
def run_server():
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.ENVIRONMENT == "development",
        workers=1,
    )


if __name__ == "__main__":
    run_server()

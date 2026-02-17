"""FastAPI application — wallpaper scraper with non-fatal startup."""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from src.utils.paths import data_path, get_data_dir
from src.utils.logging import setup_logging

logger = setup_logging("main")


def _ensure_data_dirs():
    """Try to create data directories using the resolved base. Non-fatal."""
    for sub in ["logs", "config", "temp", "wallpapers", "thumbnails", "config/site_profiles"]:
        try:
            data_path(sub).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create {sub}: {e}")
    logger.info(f"Data directory resolved to: {get_data_dir()}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown — ALL wrapped in try/except."""
    logger.info("Wallpaper Scraper starting up...")

    # Ensure data directories exist (best-effort)
    _ensure_data_dirs()

    # Load config
    try:
        from src.storage.config_store import config_store
        config_store.load()
        logger.info("Configuration loaded")
    except Exception as e:
        logger.warning(f"Config load failed (non-fatal): {e}")

    # Load activity store
    try:
        from src.storage.activity_store import activity_store
        activity_store.load()
        logger.info("Activity store loaded")
    except Exception as e:
        logger.warning(f"Activity store load failed (non-fatal): {e}")

    # Load source manager
    try:
        from src.scheduler.source_manager import source_manager
        source_manager.load()
        logger.info("Source manager loaded")
    except Exception as e:
        logger.warning(f"Source manager load failed (non-fatal): {e}")

    # Initialize scraper engine (browser + AI)
    try:
        from src.scraper.engine import scraper_engine
        await scraper_engine.initialize()
        logger.info("Scraper engine initialized")
    except Exception as e:
        logger.warning(f"Scraper engine init failed (non-fatal): {e}")

    # Initialize seed sources and discovery queries (always, not gated on Baserow)
    try:
        from src.scheduler.source_manager import source_manager
        source_manager.initialize_seeds()
        logger.info("Seeds initialized")
    except Exception as e:
        logger.warning(f"Seed initialization failed (non-fatal): {e}")

    # Start scheduler
    try:
        from src.scheduler.scheduler import scheduler
        from src.storage.config_store import config_store
        if config_store.get("scheduler", "enabled", default=True):
            await scheduler.start()
            logger.info("Scheduler started")
    except Exception as e:
        logger.warning(f"Scheduler start failed (non-fatal): {e}")

    logger.info("Wallpaper Scraper ready on port 1629")

    yield

    # Shutdown
    logger.info("Shutting down...")
    try:
        from src.scheduler.scheduler import scheduler
        await scheduler.stop()
    except Exception:
        pass
    try:
        from src.scraper.browser import browser_manager
        await browser_manager.close()
    except Exception:
        pass
    try:
        from src.scraper.engine import scraper_engine
        await scraper_engine.downloader.close()
    except Exception:
        pass
    logger.info("Shutdown complete")


app = FastAPI(title="Wallpaper Scraper", lifespan=lifespan)

# Include API routes
from src.api.routes import router
app.include_router(router)

# Serve web GUI static files (these are inside /app/src — container-owned, always accessible)
static_dir = Path(__file__).parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/thumbnails/{filename:path}")
async def serve_thumbnail(filename: str):
    """Fallback thumbnail serving — works even if StaticFiles mount failed."""
    thumb_path = data_path("thumbnails") / filename
    if thumb_path.is_file():
        return FileResponse(str(thumb_path), media_type="image/jpeg")
    return Response(status_code=404)


@app.get("/favicon.ico")
async def favicon():
    """Serve custom favicon if uploaded, otherwise return default SVG favicon."""
    for ext in ("ico", "png", "svg"):
        custom = data_path("config") / f"favicon.{ext}"
        if custom.is_file():
            media = {"ico": "image/x-icon", "png": "image/png", "svg": "image/svg+xml"}
            return FileResponse(str(custom), media_type=media.get(ext, "image/x-icon"))
    # Default: painting being scraped — framed canvas with scraper tool
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
      <rect width="32" height="32" rx="6" fill="#1c1c1e"/>
      <!-- Frame -->
      <rect x="3" y="4" width="18" height="14" rx="1.5" fill="#8B6914" stroke="#A67C00" stroke-width="0.8"/>
      <!-- Canvas -->
      <rect x="5" y="6" width="14" height="10" rx="0.5" fill="#4A90D9"/>
      <!-- Painting: sunset landscape -->
      <rect x="5" y="12" width="14" height="4" rx="0.5" fill="#2D6A4F"/>
      <circle cx="16" cy="8" r="2" fill="#FFD166"/>
      <path d="M5 13l4-3 3 2 3-4 4 5v3H5z" fill="#3A8349"/>
      <!-- Scraped/peeling section — top-right of canvas curling away -->
      <path d="M15 6h4v4l-1.5 0.5L15 10z" fill="#4A90D9" opacity="0.4"/>
      <path d="M19 6v4c0 0-0.5 1-2 1.5" stroke="#fff" stroke-width="0.4" fill="none" opacity="0.6"/>
      <!-- Scraper tool (diagonal, pulling paint off) -->
      <rect x="19" y="2" width="3" height="8" rx="0.8" fill="#C0C0C0" transform="rotate(30 20.5 6)"/>
      <rect x="19.4" y="1" width="2.2" height="3" rx="0.5" fill="#888" transform="rotate(30 20.5 6)"/>
      <!-- Paint chips falling -->
      <rect x="21" y="14" width="2" height="1.5" rx="0.3" fill="#4A90D9" opacity="0.7" transform="rotate(-15 22 14.75)"/>
      <rect x="23" y="16" width="1.5" height="1" rx="0.2" fill="#FFD166" opacity="0.6" transform="rotate(10 23.75 16.5)"/>
      <rect x="20" y="17" width="1.8" height="1.2" rx="0.3" fill="#3A8349" opacity="0.5" transform="rotate(-25 20.9 17.6)"/>
      <!-- Download arrow at bottom -->
      <path d="M16 23v5M13.5 26l2.5 2.5 2.5-2.5" stroke="#0a84ff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
    </svg>'''
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/")
async def index():
    """Serve the main HTML page."""
    return FileResponse(str(static_dir / "index.html"))

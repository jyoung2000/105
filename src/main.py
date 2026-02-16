"""FastAPI application — wallpaper scraper with non-fatal startup."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.utils.logging import setup_logging

logger = setup_logging("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown — ALL wrapped in try/except."""
    logger.info("Wallpaper Scraper starting up...")

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

    # Initialize seeds if Baserow is configured and no sources exist
    try:
        from src.storage.config_store import config_store
        from src.scheduler.source_manager import source_manager
        cfg = config_store.get_section("baserow")
        if cfg.get("api_token"):
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

# Serve thumbnails as static files
thumbnail_dir = Path("/app/data/thumbnails")
thumbnail_dir.mkdir(parents=True, exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory=str(thumbnail_dir)), name="thumbnails")

# Serve web GUI static files
static_dir = Path(__file__).parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    """Serve the main HTML page."""
    return FileResponse(str(static_dir / "index.html"))

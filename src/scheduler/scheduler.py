"""Scheduler — background task that scrapes due sources and runs discovery."""
import asyncio
from datetime import datetime, timedelta
from src.scraper.engine import scraper_engine
from src.scraper.discovery import discovery_engine
from src.scheduler.source_manager import source_manager
from src.storage.config_store import config_store
from src.utils.logging import setup_logging

logger = setup_logging("scheduler")


class Scheduler:
    """Background scheduler for automatic scraping and discovery."""

    def __init__(self):
        self._running = False
        self._paused = False
        self._task: asyncio.Task = None
        self._last_check: str = ""
        self._next_discovery: str = ""

    async def start(self):
        """Start the scheduler background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Scheduler started")

    async def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    def pause(self):
        self._paused = True
        logger.info("Scheduler paused")

    def resume(self):
        self._paused = False
        logger.info("Scheduler resumed")

    async def _run_loop(self):
        """Main scheduler loop."""
        # Initial delay to let everything start up
        await asyncio.sleep(10)

        while self._running:
            try:
                if not self._paused:
                    self._last_check = datetime.now().isoformat()
                    await self._check_and_scrape()
                    await self._check_discovery()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            # Check interval from config
            interval = config_store.get("scheduler", "check_interval_minutes", default=5)
            await asyncio.sleep(interval * 60)

    async def _check_and_scrape(self):
        """Check all enabled sources and scrape any that are due."""
        if scraper_engine.is_busy:
            logger.debug("Engine busy, skipping scheduled scrape")
            return

        sources = source_manager.get_enabled_sources()
        now = datetime.now()

        for source in sources:
            if scraper_engine.is_busy:
                break

            # Check if due
            last_scraped = source.get("last_scraped")
            schedule_hours = source.get("schedule_hours", 12)

            if last_scraped:
                try:
                    last_dt = datetime.fromisoformat(last_scraped)
                    if now - last_dt < timedelta(hours=schedule_hours):
                        continue
                except (ValueError, TypeError):
                    pass

            # Auto-disable sources with too many consecutive failures
            if source.get("consecutive_failures", 0) >= 5:
                if source.get("enabled", True):
                    source_manager.update_source(source["id"], enabled=False)
                    logger.info(f"Auto-disabled source {source.get('name')}: too many consecutive failures")
                continue

            if not source.get("enabled", True):
                continue

            logger.info(f"Scheduled scrape: {source.get('name', source.get('url'))}")
            try:
                job = await scraper_engine.scrape_url(
                    url=source["url"],
                    source_id=source["id"],
                    source_name=source.get("name", ""),
                    max_pages=source.get("max_pages", 10),
                )
                # Record results
                source_manager.record_scrape(
                    source["id"],
                    uploaded=job.images_uploaded,
                    dupes=job.duplicates,
                    errors=job.errors,
                )

                # Adaptive scheduling based on source quality
                try:
                    if job.images_uploaded > 0:
                        source_manager.record_source_productive(source["id"])
                        quality = source_manager.compute_source_quality(source["id"])
                        if quality >= 70:
                            new_hours = max(4, source.get("schedule_hours", 12) - 2)
                            source_manager.update_source(source["id"], schedule_hours=new_hours)
                    elif job.images_found == 0:
                        quality = source_manager.compute_source_quality(source["id"])
                        if quality < 20:
                            new_hours = min(72, source.get("schedule_hours", 12) * 2)
                            source_manager.update_source(source["id"], schedule_hours=new_hours)
                except Exception as e:
                    logger.debug(f"Adaptive scheduling error: {e}")

            except Exception as e:
                logger.error(f"Scheduled scrape failed for {source.get('name')}: {e}")
                source_manager.record_scrape(source["id"], 0, 0, 1)

            # Small delay between sources
            await asyncio.sleep(5)

    async def _check_discovery(self):
        """Run discovery if interval has elapsed."""
        disc = source_manager.discovery_state
        if not disc.get("enabled", True):
            return

        interval = disc.get("interval_hours", 6)
        last_run = disc.get("last_discovery_run")

        should_run = False
        if not last_run:
            should_run = True
        else:
            try:
                last_dt = datetime.fromisoformat(last_run)
                if datetime.now() - last_dt >= timedelta(hours=interval):
                    should_run = True
            except (ValueError, TypeError):
                should_run = True

        if should_run:
            logger.info("Running scheduled discovery")
            try:
                await discovery_engine.run_discovery()
            except Exception as e:
                logger.error(f"Discovery failed: {e}")

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "paused": self._paused,
            "last_check": self._last_check,
            "discovery_state": source_manager.discovery_state,
        }


# Singleton
scheduler = Scheduler()

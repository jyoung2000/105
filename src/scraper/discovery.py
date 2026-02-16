"""Source discovery engine — finds new wallpaper sources via web search."""
import asyncio
from datetime import datetime
from urllib.parse import urlparse
from src.scraper.browser import browser_manager
from src.scraper.adapters.generic import GenericAdapter
from src.scheduler.source_manager import source_manager
from src.utils.logging import setup_logging

logger = setup_logging("discovery")

# Domains to never add as sources
BLOCKED_DOMAINS = {
    "google.com", "youtube.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "reddit.com", "pinterest.com", "amazon.com", "ebay.com",
    "wikipedia.org", "tiktok.com", "linkedin.com", "duckduckgo.com",
}
MIN_VALIDATION_SCORE = 3


class DiscoveryEngine:
    """Discovers new wallpaper sources by searching the web."""

    def __init__(self):
        self.adapter = GenericAdapter()
        self._running = False
        self._last_results: list[dict] = []

    async def run_discovery(self) -> list[dict]:
        """Run one discovery cycle: pick query, search, validate, add sources."""
        if self._running:
            logger.info("Discovery already running, skipping")
            return []

        self._running = True
        results = []

        try:
            if not browser_manager.is_available:
                logger.warning("Browser not available for discovery")
                return []

            # Get next query from rotation
            query_data = source_manager.get_next_query()
            if not query_data:
                logger.info("No enabled discovery queries")
                return []

            query_text = query_data["query"]
            query_id = query_data["id"]
            logger.info(f"Discovery using query: '{query_text}'")

            # Search DuckDuckGo
            urls = await browser_manager.search_duckduckgo(query_text)
            logger.info(f"Found {len(urls)} candidate URLs")

            new_sources = 0
            for url in urls:
                try:
                    domain = urlparse(url).netloc
                    # Skip blocked and known domains
                    if any(blocked in domain for blocked in BLOCKED_DOMAINS):
                        continue
                    if source_manager.domain_exists(domain):
                        continue

                    # Validate: load page and count wallpaper images
                    score = await self._validate_source(url)
                    result = {
                        "url": url,
                        "domain": domain,
                        "score": score,
                        "added": False,
                        "query": query_text,
                        "timestamp": datetime.now().isoformat(),
                    }

                    if score >= MIN_VALIDATION_SCORE:
                        source = source_manager.add_source(
                            url=url,
                            name=f"{domain} (discovered)",
                            category="discovered",
                            discovered_by_query=query_text,
                        )
                        result["added"] = True
                        result["source_id"] = source["id"]
                        new_sources += 1
                        logger.info(f"Discovered new source: {domain} (score={score})")

                    results.append(result)

                except Exception as e:
                    logger.warning(f"Error validating {url}: {e}")

                # Be polite between validations
                await asyncio.sleep(3)

            # Record query usage
            source_manager.record_query_use(query_id, new_sources)
            source_manager.update_discovery_state(
                last_discovery_run=datetime.now().isoformat()
            )

            self._last_results = results[-10:]
            logger.info(f"Discovery complete: {new_sources} new sources from '{query_text}'")

        except Exception as e:
            logger.error(f"Discovery error: {e}")
        finally:
            self._running = False

        return results

    async def _validate_source(self, url: str) -> float:
        """Validate a URL as a wallpaper source. Returns score."""
        try:
            html = await browser_manager.get_page_content(url, wait_time=4000)
            images = await self.adapter.scrape(html, url)

            score = len(images)

            # Pagination bonus
            next_page = await self.adapter.get_next_page_url(html, url, 1)
            if next_page:
                score *= 1.5

            return score

        except Exception as e:
            logger.debug(f"Validation failed for {url}: {e}")
            return 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_results(self) -> list[dict]:
        return list(self._last_results)


# Singleton
discovery_engine = DiscoveryEngine()

"""Source discovery engine — finds new wallpaper sources via web search."""
import asyncio
import random
from datetime import datetime
from urllib.parse import urlparse
from src.scraper.browser import browser_manager
from src.scraper.adapters.generic import GenericAdapter
from src.scheduler.source_manager import source_manager
from src.storage.config_store import config_store
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
        self._running = False
        self._last_results: list[dict] = []

    def _get_adapter(self) -> GenericAdapter:
        """Get adapter configured with current settings."""
        min_w = config_store.get("scraping", "min_width", default=800)
        min_h = config_store.get("scraping", "min_height", default=600)
        return GenericAdapter(min_width=min_w, min_height=min_h)

    async def run_discovery(self) -> list[dict]:
        """Run one discovery cycle: pick query, search, validate, add sources."""
        if self._running:
            logger.info("Discovery already running, skipping")
            return []

        self._running = True
        results = []

        try:
            if not browser_manager.is_available:
                logger.info("Browser not available, attempting initialization...")
                success = await browser_manager.initialize()
                if not success:
                    logger.warning("Browser init failed, discovery cannot proceed")
                    return []
                logger.info("Browser initialized successfully for discovery")

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
                            validation_score=score,
                        )
                        result["added"] = True
                        result["source_id"] = source["id"]
                        new_sources += 1
                        logger.info(f"Discovered new source: {domain} (score={score})")

                    results.append(result)

                except Exception as e:
                    logger.warning(f"Error validating {url}: {e}")

                # Be polite between validations (randomized)
                await asyncio.sleep(3 + random.random() * 3)

            # Record query usage
            source_manager.record_query_use(query_id, new_sources)
            # Only stamp discovery as "run" if we actually evaluated URLs
            if results:
                source_manager.update_discovery_state(
                    last_discovery_run=datetime.now().isoformat()
                )
            else:
                logger.info("Discovery produced no results, will retry on next cycle")

            self._last_results = results[-10:]
            logger.info(f"Discovery complete: {new_sources} new sources from '{query_text}'")

            # Auto-generate new queries based on productive discoveries
            if new_sources > 0:
                try:
                    self._generate_new_queries()
                except Exception as e:
                    logger.warning(f"Query generation failed: {e}")

        except Exception as e:
            logger.error(f"Discovery error: {e}")
        finally:
            self._running = False

        return results

    async def _validate_source(self, url: str) -> float:
        """Validate a URL as a wallpaper source. Returns score."""
        try:
            adapter = self._get_adapter()
            html = await browser_manager.get_page_content(url, wait_time=4000)
            images = await adapter.scrape(html, url)

            score = len(images)

            # Pagination bonus
            next_page = await adapter.get_next_page_url(html, url, 1)
            if next_page:
                score *= 1.5

            return score

        except Exception as e:
            logger.debug(f"Validation failed for {url}: {e}")
            return 0

    def _generate_new_queries(self):
        """Generate new search queries based on productive discovered sources."""
        sources = source_manager.get_all_sources()
        discovered = [s for s in sources if s.get("category") == "discovered"
                      and s.get("total_uploaded", 0) > 0]
        if not discovered:
            return

        existing_queries = {q["query"].lower() for q in source_manager.get_all_queries()}

        for source in discovered[:5]:
            domain = source.get("domain", "")
            if not domain:
                continue
            candidates = [
                f"sites like {domain} wallpaper",
                f"wallpaper sites similar to {domain}",
                f"{domain} alternatives free wallpaper",
            ]
            for candidate in candidates:
                if candidate.lower() not in existing_queries:
                    source_manager.add_query(candidate)
                    existing_queries.add(candidate.lower())
                    logger.info(f"Auto-generated query: '{candidate}'")
                    break  # One new query per productive source

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_results(self) -> list[dict]:
        return list(self._last_results)


# Singleton
discovery_engine = DiscoveryEngine()

"""Playwright browser manager — single context, reused."""
import asyncio
from typing import Optional
from src.utils.logging import setup_logging

logger = setup_logging("browser")


class BrowserManager:
    """Manages a single Playwright browser instance and context."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> bool:
        """Launch browser. Returns False on failure (non-fatal)."""
        async with self._lock:
            if self._initialized:
                return True
            try:
                from playwright.async_api import async_playwright
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--no-first-run",
                        "--no-zygote",
                        "--single-process",
                        "--disable-extensions",
                    ],
                )
                self._context = await self._browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                self._initialized = True
                logger.info("Browser initialized successfully")
                return True
            except Exception as e:
                logger.warning(f"Browser initialization failed: {e}")
                self._initialized = False
                return False

    async def get_page(self):
        """Get a new page from the browser context."""
        if not self._initialized:
            success = await self.initialize()
            if not success:
                raise RuntimeError("Browser not available")
        return await self._context.new_page()

    async def get_page_content(self, url: str, wait_time: int = 3000) -> str:
        """Navigate to URL and return page HTML content."""
        page = await self.get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(wait_time)
            # Scroll to trigger lazy loading
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(500)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(500)
            return await page.content()
        finally:
            await page.close()

    async def search_duckduckgo(self, query: str) -> list[str]:
        """Search DuckDuckGo and return result URLs."""
        page = await self.get_page()
        urls = []
        try:
            search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            links = await page.query_selector_all("a[data-testid='result-title-a']")
            if not links:
                links = await page.query_selector_all("article a[href]")
            if not links:
                links = await page.query_selector_all("#links a.result__a")
            for link in links[:15]:
                href = await link.get_attribute("href")
                if href and href.startswith("http") and "duckduckgo" not in href:
                    urls.append(href)
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed for '{query}': {e}")
        finally:
            await page.close()
        return urls

    @property
    def is_available(self) -> bool:
        return self._initialized

    async def close(self):
        """Clean up browser resources."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"Browser cleanup error: {e}")
        finally:
            self._initialized = False
            self._playwright = None
            self._browser = None
            self._context = None


# Singleton
browser_manager = BrowserManager()

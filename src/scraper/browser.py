"""Playwright browser manager — stealth mode with human-like behavior."""
import asyncio
import random
from typing import Optional
from urllib.parse import urlparse, parse_qs, quote_plus
from src.utils.logging import setup_logging

logger = setup_logging("browser")

# Rotate through recent, realistic user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# Viewport variations to avoid fingerprinting
VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]


def jitter(base_ms: int, variance: float = 0.3) -> int:
    """Add random jitter to a millisecond value. variance=0.3 means +/- 30%."""
    low = int(base_ms * (1 - variance))
    high = int(base_ms * (1 + variance))
    return random.randint(max(low, 0), high)


class BrowserManager:
    """Manages a single Playwright browser instance and context with stealth."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._lock = asyncio.Lock()
        self._initialized = False
        self._stealth_fn = None
        self._current_ua = ""

    async def initialize(self) -> bool:
        """Launch browser with stealth patches. Returns False on failure (non-fatal)."""
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
                        "--disable-blink-features=AutomationControlled",
                    ],
                )

                ua = random.choice(USER_AGENTS)
                vp = random.choice(VIEWPORTS)
                self._current_ua = ua

                self._context = await self._browser.new_context(
                    viewport=vp,
                    user_agent=ua,
                    locale="en-US",
                    timezone_id="America/New_York",
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                        "Accept-Encoding": "gzip, deflate, br",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                        "Upgrade-Insecure-Requests": "1",
                    },
                )

                # Apply stealth patches (graceful fallback)
                try:
                    from playwright_stealth import stealth_async
                    self._stealth_fn = stealth_async
                    logger.info("Playwright stealth loaded")
                except ImportError:
                    self._stealth_fn = None
                    logger.warning("playwright-stealth not installed, proceeding without stealth")

                self._initialized = True
                logger.info(f"Browser initialized (UA: {ua[:50]}..., VP: {vp['width']}x{vp['height']})")
                return True
            except Exception as e:
                logger.warning(f"Browser initialization failed: {e}")
                self._initialized = False
                return False

    async def get_page(self):
        """Get a new page from the browser context with stealth applied."""
        if not self._initialized:
            success = await self.initialize()
            if not success:
                raise RuntimeError("Browser not available")
        page = await self._context.new_page()
        if self._stealth_fn:
            await self._stealth_fn(page)
        return page

    async def get_page_content(self, url: str, wait_time: int = 3000,
                               scroll_count: int = 5, scroll_wait_ms: int = 800) -> str:
        """Navigate to URL and return page HTML content with human-like behavior."""
        page = await self.get_page()
        try:
            # Set referer based on the target URL's domain
            parsed = urlparse(url)
            referer = f"{parsed.scheme}://{parsed.netloc}/"

            await page.goto(url, wait_until="domcontentloaded", timeout=30000,
                            referer=referer)
            await page.wait_for_timeout(jitter(wait_time))

            # Human-like scrolling with variable speed
            for i in range(scroll_count):
                # Randomize scroll distance (75%-125% of viewport height)
                vh = page.viewport_size["height"] if page.viewport_size else 900
                scroll_amount = random.randint(int(vh * 0.75), int(vh * 1.25))
                await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                await page.wait_for_timeout(jitter(scroll_wait_ms))

                # Occasional longer pause (simulates reading)
                if random.random() < 0.2:
                    await page.wait_for_timeout(jitter(1500, 0.5))

            # Scroll back to top
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(jitter(500))
            return await page.content()
        finally:
            await page.close()

    async def web_search(self, query: str) -> list[str]:
        """Search the web using multiple engines with fallback.

        Tries DuckDuckGo first, then Bing if DDG fails or is blocked.
        """
        # Try DuckDuckGo first
        urls = await self._search_duckduckgo(query)
        if urls:
            return urls

        # Fallback to Bing
        logger.info(f"DDG returned 0 results for '{query}', trying Bing")
        urls = await self._search_bing(query)
        if urls:
            return urls

        logger.warning(f"All search engines returned 0 results for '{query}'")
        return []

    async def _search_duckduckgo(self, query: str) -> list[str]:
        """Search DuckDuckGo and return result URLs."""
        page = await self.get_page()
        urls = []
        try:
            # Navigate to DuckDuckGo homepage — JS version is more reliable
            # than html.duckduckgo.com which frequently blocks headless browsers
            await page.goto("https://duckduckgo.com/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(jitter(2000))

            # Type the query
            search_input = await page.query_selector('input[name="q"]')
            if not search_input:
                # Try alternative selectors
                search_input = await page.query_selector('textarea[name="q"]')
            if not search_input:
                search_input = await page.query_selector('[role="combobox"]')

            if search_input:
                await search_input.click()
                await page.wait_for_timeout(jitter(300))
                for char in query:
                    await search_input.type(char, delay=random.randint(50, 150))
                await page.wait_for_timeout(jitter(500))
                await page.keyboard.press("Enter")
            else:
                logger.warning("DDG search input not found, using direct URL")
                search_url = f"https://duckduckgo.com/?q={quote_plus(query)}"
                await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # Wait longer for JS-rendered results
            await page.wait_for_timeout(jitter(5000))

            # Extract result URLs from the page
            urls = await self._extract_search_results(page, "ddg")

            logger.info(f"DDG search '{query}': {len(urls)} URLs")

            if len(urls) == 0:
                try:
                    page_text = await page.inner_text("body")
                    text_len = len(page_text.strip())
                    if "captcha" in page_text.lower() or "unusual traffic" in page_text.lower():
                        logger.warning("DDG may be blocking: captcha/unusual traffic detected")
                    elif text_len < 200:
                        logger.warning(f"DDG returned very short page ({text_len} chars), possible block")
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"DuckDuckGo search failed for '{query}': {e}")
        finally:
            await page.close()
        return urls

    async def _search_bing(self, query: str) -> list[str]:
        """Search Bing and return result URLs."""
        page = await self.get_page()
        urls = []
        try:
            search_url = f"https://www.bing.com/search?q={quote_plus(query)}"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(jitter(3000))

            # Bing result selectors (stable across layouts)
            selectors = [
                ("li.b_algo h2 a[href]", "bing-algo"),
                (".b_algo a[href^='http']", "bing-algo-link"),
                ("h2 a[href^='http']", "bing-h2"),
                ("cite", "bing-cite"),
            ]

            links = []
            matched_selector = "none"
            for selector, name in selectors:
                links = await page.query_selector_all(selector)
                if links:
                    matched_selector = name
                    break

            if not links:
                links = await page.query_selector_all("a[href^='http']")
                matched_selector = "bing-all-links"

            skip_domains = {"bing.com", "microsoft.com", "msn.com", "live.com",
                            "microsoftonline.com", "office.com",
                            "google.com", "facebook.com", "twitter.com", "x.com",
                            "youtube.com", "instagram.com", "linkedin.com", "tiktok.com",
                            "reddit.com", "wikipedia.org", "amazon.com"}

            for link in links[:30]:
                href = await link.get_attribute("href")
                if href and href.startswith("http"):
                    try:
                        domain = urlparse(href).netloc.lower()
                        if not any(skip in domain for skip in skip_domains):
                            if href not in urls:
                                urls.append(href)
                    except Exception:
                        pass
                if len(urls) >= 15:
                    break

            logger.info(f"Bing search '{query}': {len(urls)} URLs via '{matched_selector}'")

            if len(urls) == 0:
                try:
                    page_text = await page.inner_text("body")
                    if len(page_text.strip()) < 200:
                        logger.warning(f"Bing returned very short page ({len(page_text)} chars)")
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Bing search failed for '{query}': {e}")
        finally:
            await page.close()
        return urls

    async def _extract_search_results(self, page, engine: str) -> list[str]:
        """Extract search result URLs from a search results page."""
        urls = []

        # Try multiple selector strategies
        selectors = [
            ("a[data-testid='result-title-a']", "modern"),
            ("article a[href^='http']", "article"),
            ("#links a.result__a", "classic"),
            ("ol.react-results--main a[href]", "react"),
            ("a[rel='noopener'][href^='http']", "noopener"),
            ("h2 a[href^='http']", "h2-links"),
            ("a.result__a", "html-result"),
        ]

        links = []
        matched_selector = "none"
        for selector, name in selectors:
            links = await page.query_selector_all(selector)
            if links:
                matched_selector = name
                break

        if not links:
            links = await page.query_selector_all("a[href^='http']")
            matched_selector = "all-links-fallback"

        skip_domains = {"duckduckgo.com", "html.duckduckgo.com", "duck.co",
                        "spreadprivacy.com",
                        "google.com", "facebook.com", "twitter.com", "x.com",
                        "youtube.com", "instagram.com", "linkedin.com", "tiktok.com",
                        "reddit.com", "wikipedia.org", "amazon.com"}

        for link in links[:30]:
            href = await link.get_attribute("href")
            if href and href.startswith("http"):
                try:
                    parsed = urlparse(href)
                    domain = parsed.netloc.lower()
                    # DDG wraps URLs in redirect links
                    if "duckduckgo.com" in domain:
                        params = parse_qs(parsed.query)
                        if "uddg" in params:
                            href = params["uddg"][0]
                            domain = urlparse(href).netloc.lower()
                        else:
                            continue
                    if not any(skip in domain for skip in skip_domains):
                        if href not in urls:
                            urls.append(href)
                except Exception:
                    pass
            if len(urls) >= 15:
                break

        logger.debug(f"{engine} extracted {len(urls)} URLs via '{matched_selector}'")
        return urls

    # Keep old name for backward compatibility
    async def search_duckduckgo(self, query: str) -> list[str]:
        """Search the web. Delegates to web_search() with multi-engine fallback."""
        return await self.web_search(query)

    @property
    def is_available(self) -> bool:
        return self._initialized

    @property
    def current_user_agent(self) -> str:
        """Current user agent string, shared with downloader for consistency."""
        return self._current_ua or USER_AGENTS[0]

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
            self._stealth_fn = None
            self._current_ua = ""
            self._playwright = None
            self._browser = None
            self._context = None


# Singleton
browser_manager = BrowserManager()

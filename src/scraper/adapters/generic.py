"""Generic wallpaper adapter — works on any wallpaper site without site-specific code.

Understands the gallery→detail→download flow:
- Gallery/listing pages have thumbnails linking to detail pages
- Detail pages have one main wallpaper image + optional download buttons
- The scraper should follow thumbnails to detail pages, not download thumbnails
"""
import re
from typing import Optional
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from .base import BaseAdapter, ScrapedImage
from src.utils.logging import setup_logging

logger = setup_logging("generic_adapter")

# Minimum dimensions to consider an image a wallpaper
MIN_WIDTH = 800
MIN_HEIGHT = 600

# URL patterns that suggest high-resolution images
HIGHRES_PATTERNS = [
    r"original", r"/full/", r"download", r"highres", r"large",
    r"(\d{3,4})x(\d{3,4})", r"4k", r"uhd", r"2160", r"1440", r"1080",
    r"wallpaper", r"wp-content/uploads",
    r"raw", r"source", r"/max/",
    r"hires", r"retina", r"[_-]2x", r"[_-]3x", r"[_-]xl",
    r"full[_-]size", r"[_-]large", r"[_-]big", r"/orig/", r"[_-]orig\b",
]

# Patterns to exclude (thumbnails, icons, UI elements, ads, e-commerce CDNs)
EXCLUDE_PATTERNS = [
    r"logo", r"icon", r"avatar", r"banner", r"sprite",
    r"placeholder", r"loading", r"spinner", r"ad[_-]",
    r"facebook", r"twitter", r"instagram", r"pinterest",
    r"google", r"analytics", r"tracking", r"pixel",
    r"btn", r"button", r"arrow", r"close", r"menu",
    r"1x1", r"spacer", r"blank", r"transparent",
    r"/thumb[s]?/", r"/small/", r"/preview/", r"/mini/",
    r"[_-]t\.", r"[_-]sq\.", r"[_-]sm\.", r"[_-]xs\.",
    r"\.th\.", r"/tiny/", r"/micro/",
    r"/compressed/", r"/optimized/", r"/resized/",
    # Stock photo watermarked thumbnails
    r"istockphoto\.com", r"gettyimages\.", r"shutterstock\.com",
    r"stock\.adobe\.com", r"depositphotos\.com", r"dreamstime\.com",
    r"123rf\.com", r"alamy\.com",
    # Ad/e-commerce CDN domains (appear as ads on wallpaper sites)
    r"alicdn\.com", r"aliexpress\.com", r"alibaba\.com", r"taobao\.com",
    r"amazon\.com/images", r"ebay\.com", r"shopify\.com",
    r"doubleclick\.net", r"googlesyndication", r"adnxs\.com",
    r"adsrvr\.org", r"adservice", r"pagead",
]

# URL patterns for navigation/non-detail pages to skip in detail page detection
NAV_EXCLUDE_PATTERNS = [
    r"/categor(y|ies)/", r"/tags?/", r"/search", r"/sort", r"/filter",
    r"/login", r"/register", r"/sign[_-]?up", r"/sign[_-]?in",
    r"/about", r"/contact", r"/terms", r"/privacy", r"/faq", r"/help",
    r"/cart", r"/checkout", r"/account", r"/settings", r"/profile",
    r"/feed", r"/trending", r"/popular", r"/latest", r"/top/?$",
    r"^/?$", r"/index\.html?$",
    r"^/@",                # User profile pages (/@username)
    r"^/user/", r"^/u/",  # Other user page patterns
    r"^/author/", r"^/photographer/", r"^/contributor/",
    r"/collections?/?$",   # Collection listing pages
]

# Image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}

# Known wallpaper image selectors on detail pages (site-specific but common)
DETAIL_IMAGE_SELECTORS = [
    "img#wallpaper",              # Wallhaven
    "img#show_img",               # WallpaperFlare
    "img.wallpaper__image",       # WallpapersCraft
    ".wallpaper__image",          # WallpapersCraft (may be div with bg)
    "img.main-wallpaper",
    "img.wallpaper-image",
    "img[itemprop='contentUrl']",
    "img[itemprop='image']",
    "img.detail-image",
    "img.full-image",
]

# Selectors for download buttons/links on detail pages
DOWNLOAD_SELECTORS = [
    "a[href*='/download']",
    "a[download]",
    "a.download",
    "a.btn-download",
    "a.download-btn",
    "a.download-button",
    "a[data-action='download']",
    "a[title*='Download']",
    "a[title*='download']",
]


class GenericAdapter(BaseAdapter):
    """Universal wallpaper adapter using heuristics to find wallpaper images on any site.

    Understands two page types:
    - Listing/gallery pages: have many thumbnails, each linking to a detail page
    - Detail pages: have one main image + optional download button
    """

    def __init__(self, min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT):
        self.min_width = min_width
        self.min_height = min_height

    async def scrape(self, html: str, page_url: str) -> list[ScrapedImage]:
        """Parse HTML and find wallpaper-quality images.

        On detail pages: looks for the main wallpaper image via known selectors,
        download buttons, and the single largest image.
        On listing pages: finds direct high-res image links (but the engine should
        prefer detail page links over these).
        """
        soup = BeautifulSoup(html, "lxml")
        images = []
        seen_urls = set()

        # FIRST: Try detail-page-specific strategies (targeted, high confidence)
        detail_images = self._find_detail_page_images(soup, page_url, seen_urls)
        if detail_images:
            logger.info(f"Found {len(detail_images)} wallpaper images via detail-page detection on {page_url}")
            return detail_images

        # SECOND: Try download buttons/links (common on wallpaper sites)
        download_images = self._find_download_links(soup, page_url, seen_urls)
        if download_images:
            logger.info(f"Found {len(download_images)} wallpaper images via download links on {page_url}")
            return download_images

        # THIRD: General image extraction (for pages without specific selectors)

        # Strategy 1: Find direct high-res image links (<a> pointing to image files)
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            abs_url = urljoin(page_url, href)
            if self._is_image_url(abs_url) and abs_url not in seen_urls:
                if not self._is_excluded(abs_url):
                    score = self._score_url(abs_url)
                    if score > 0:
                        seen_urls.add(abs_url)
                        img_tag = link.find("img")
                        alt = ""
                        title = ""
                        thumb = ""
                        if img_tag:
                            alt = img_tag.get("alt", "") or ""
                            title = img_tag.get("title", "") or alt
                            thumb = urljoin(page_url, img_tag.get("src", ""))
                        images.append(self._make_image(abs_url, thumb, alt, title, page_url, link, score))

        # Strategy 2: Find img tags with large dimensions or high-res src
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "") or img.get("data-original", "") or ""
            if not src or src.startswith("data:"):
                src = img.get("data-src", "") or img.get("data-original", "") or ""
            if not src:
                continue
            abs_url = urljoin(page_url, src)
            if abs_url in seen_urls:
                continue

            # Check for high-res sources in srcset, picture, or data attributes
            highres_src = self._find_highres_source(img, page_url)
            if highres_src:
                abs_url = highres_src

            if abs_url in seen_urls or not self._is_image_url(abs_url):
                continue
            if self._is_excluded(abs_url):
                continue

            width = self._parse_dim(img.get("width", ""))
            height = self._parse_dim(img.get("height", ""))
            score = self._score_url(abs_url)

            # Accept if dimensions are large enough, or URL suggests high-res
            if (width >= self.min_width and height >= self.min_height) or score >= 2:
                seen_urls.add(abs_url)
                alt = img.get("alt", "") or ""
                title = img.get("title", "") or alt
                images.append(self._make_image(abs_url, "", alt, title, page_url, img, score, width, height))

        # Strategy 3: CSS background images in style attributes
        for elem in soup.find_all(style=True):
            style = elem.get("style", "")
            urls = re.findall(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', style)
            for url in urls:
                if url not in seen_urls and self._is_image_url(url) and not self._is_excluded(url):
                    score = self._score_url(url)
                    if score > 0:
                        seen_urls.add(url)
                        images.append(self._make_image(url, "", "", "", page_url, elem, score))

        # Strategy 4: data-download, data-wallpaper, and other site-specific data attributes
        for attr_name in ["data-download", "data-wallpaper", "data-full-src", "data-image", "data-href"]:
            for elem in soup.find_all(attrs={attr_name: True}):
                url = elem.get(attr_name, "")
                if not url:
                    continue
                abs_url = urljoin(page_url, url)
                if abs_url in seen_urls or not self._is_image_url(abs_url):
                    continue
                if self._is_excluded(abs_url):
                    continue
                seen_urls.add(abs_url)
                score = self._score_url(abs_url) + 2
                images.append(self._make_image(abs_url, "", "", "", page_url, elem, score))

        # Sort by score (highest first) and return
        images.sort(key=lambda x: x.width * x.height if x.width and x.height else 0, reverse=True)
        logger.info(f"Found {len(images)} potential wallpapers on {page_url}")

        if not images:
            # Debug: log page diagnostics
            total_imgs = len(soup.find_all("img"))
            total_links = len(soup.find_all("a", href=True))
            html_len = len(html)
            title_tag = soup.find("title")
            page_title = title_tag.get_text(strip=True)[:100] if title_tag else "(no title)"
            logger.debug(
                f"Empty result diagnostics for {page_url}: "
                f"html={html_len} chars, imgs={total_imgs}, links={total_links}, "
                f"title='{page_title}'"
            )
            body_text = soup.get_text()[:500].lower()
            if any(w in body_text for w in ["captcha", "challenge", "verify you are human", "access denied", "blocked"]):
                logger.warning(f"Page may be blocked/captcha'd: {page_url}")

        return images

    def _find_detail_page_images(self, soup: BeautifulSoup, page_url: str,
                                  seen_urls: set) -> list[ScrapedImage]:
        """Find wallpaper images using detail-page-specific selectors.

        These selectors target known wallpaper site patterns where the main
        image has a specific ID or class (e.g., img#wallpaper on Wallhaven).
        """
        images = []
        for selector in DETAIL_IMAGE_SELECTORS:
            try:
                elem = soup.select_one(selector)
                if not elem:
                    continue

                # Could be an img tag or a div with background
                if elem.name == "img":
                    src = (elem.get("src", "") or elem.get("data-src", "")
                           or elem.get("data-original", "") or "")
                    if src and not src.startswith("data:"):
                        abs_url = urljoin(page_url, src)
                        if abs_url not in seen_urls and not self._is_excluded(abs_url):
                            seen_urls.add(abs_url)
                            alt = elem.get("alt", "") or ""
                            title = elem.get("title", "") or alt
                            width = self._parse_dim(elem.get("width", ""))
                            height = self._parse_dim(elem.get("height", ""))
                            images.append(self._make_image(
                                abs_url, "", alt, title, page_url, elem,
                                score=5, width=width, height=height
                            ))
                else:
                    # Div/element — check background-image
                    style = elem.get("style", "")
                    bg_urls = re.findall(r'url\(["\']?(https?://[^"\')\s]+)["\']?\)', style)
                    for url in bg_urls:
                        if url not in seen_urls and not self._is_excluded(url):
                            seen_urls.add(url)
                            images.append(self._make_image(url, "", "", "", page_url, elem, score=5))
            except Exception:
                continue
        return images

    def _find_download_links(self, soup: BeautifulSoup, page_url: str,
                              seen_urls: set) -> list[ScrapedImage]:
        """Find wallpaper download links/buttons on detail pages."""
        images = []
        for selector in DOWNLOAD_SELECTORS:
            try:
                links = soup.select(selector)
                for link in links[:5]:
                    href = link.get("href", "")
                    if not href:
                        continue
                    abs_url = urljoin(page_url, href)
                    if abs_url in seen_urls:
                        continue
                    # Download links may point to image files or download endpoints
                    if self._is_image_url(abs_url) and not self._is_excluded(abs_url):
                        seen_urls.add(abs_url)
                        text = link.get_text(strip=True)
                        images.append(self._make_image(
                            abs_url, "", "", text, page_url, link, score=6
                        ))
                    elif "/download" in abs_url.lower():
                        # Download endpoint — may redirect to image
                        # Only include if it's on the same domain
                        link_root = self._root_domain(urlparse(abs_url).netloc)
                        page_root = self._root_domain(urlparse(page_url).netloc)
                        if link_root == page_root:
                            seen_urls.add(abs_url)
                            text = link.get_text(strip=True)
                            images.append(self._make_image(
                                abs_url, "", "", text, page_url, link, score=6
                            ))
            except Exception:
                continue

        # Also look for links with download-related text
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True).lower()
            if any(w in text for w in ["download original", "download full", "full size",
                                        "original size", "download wallpaper"]):
                href = link.get("href", "")
                abs_url = urljoin(page_url, href)
                if abs_url not in seen_urls:
                    link_root = self._root_domain(urlparse(abs_url).netloc)
                    page_root = self._root_domain(urlparse(page_url).netloc)
                    if link_root == page_root:
                        seen_urls.add(abs_url)
                        images.append(self._make_image(
                            abs_url, "", "", text, page_url, link, score=7
                        ))

        return images

    def get_detail_page_links(self, html: str, page_url: str) -> list[dict]:
        """Find links to detail/individual wallpaper pages (not image files).

        On gallery/listing pages, thumbnails are wrapped in <a> tags linking
        to individual pages where full-size images live.

        Uses TWO approaches:
        1. Links containing/near an <img> tag (thumbnail → detail page)
        2. Links with URL patterns that suggest detail pages (/w/xxx, /wallpaper-, etc.)
        """
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()
        page_parsed = urlparse(page_url)
        page_root = self._root_domain(page_parsed.netloc)

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            abs_url = urljoin(page_url, href)

            # Skip if it's an image file URL (we want page links, not images)
            if self._is_image_url(abs_url):
                continue

            # Skip external links (different root domain)
            link_parsed = urlparse(abs_url)
            link_root = self._root_domain(link_parsed.netloc)
            if link_root and page_root and link_root != page_root:
                continue

            # Skip if same as current page
            if abs_url.rstrip("/") == page_url.rstrip("/"):
                continue

            if abs_url in seen:
                continue

            # Skip navigation/category/utility pages
            path = link_parsed.path.lower()
            if any(re.search(p, path) for p in NAV_EXCLUDE_PATTERNS):
                continue

            # Try to find associated thumbnail image
            img = link.find("img")
            if not img:
                # Check sibling/parent layouts (Wallhaven's <figure><img/><a/></figure>)
                parent = link.parent
                if parent and parent.name in ("figure", "li", "article"):
                    img = parent.find("img")
                elif parent and parent.name == "div":
                    classes = " ".join(parent.get("class", [])).lower()
                    if any(k in classes for k in ("thumb", "card", "item", "wallpaper",
                                                   "preview", "grid", "pic")):
                        img = parent.find("img")

            # Get thumbnail info
            thumb_src = ""
            alt = ""
            title = link.get("title", "") or ""
            if img:
                thumb_src = img.get("data-src", "") or img.get("src", "") or ""
                if thumb_src.startswith("data:"):
                    thumb_src = img.get("data-src", "") or img.get("data-original", "") or ""
                alt = img.get("alt", "") or ""
                if not title:
                    title = img.get("title", "") or ""

            # Accept link if it has an associated image OR has a detail-page URL pattern
            has_img = bool(img and thumb_src)
            has_detail_pattern = self._looks_like_detail_url(path)

            if not has_img and not has_detail_pattern:
                continue

            seen.add(abs_url)
            links.append({
                "url": abs_url,
                "thumbnail_url": urljoin(page_url, thumb_src) if thumb_src else "",
                "alt": alt,
                "title": title,
            })

        logger.info(f"Found {len(links)} detail page links on {page_url}")
        return links

    @staticmethod
    def _looks_like_detail_url(path: str) -> bool:
        """Check if a URL path looks like a single-wallpaper detail page.

        Matches patterns like: /w/abc123, /wallpaper-name-123,
        /photo/123, /image/123, /pic/123, etc.
        """
        detail_patterns = [
            r"^/w/[a-z0-9]+$",                  # Wallhaven: /w/abc123
            r"/wallpaper[/-]",                    # Generic: /wallpaper/... or /wallpaper-...
            r"/photo/\d+",                         # Photo detail pages
            r"/image/\d+",                         # Image detail pages
            r"/pic/\d+",                           # Pic detail pages
            r"^/[^/]+-\d+\.html$",                # 4KWallpapers: /name-123.html
            r"/download/\d+",                      # Download pages
            r"^/[^/]+/[^/]+-\d+$",                # Category/slug-id pattern
        ]
        return any(re.search(p, path, re.I) for p in detail_patterns)

    @staticmethod
    def _root_domain(netloc: str) -> str:
        """Extract root domain from netloc (e.g. 'th.wallhaven.cc' -> 'wallhaven.cc')."""
        parts = netloc.lower().split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return netloc.lower()

    async def get_next_page_url(self, html: str, current_url: str, page_num: int) -> Optional[str]:
        """Find pagination link for next page."""
        soup = BeautifulSoup(html, "lxml")

        # Strategy 1: Look for explicit "next" links
        for link in soup.find_all("a", href=True):
            text = link.get_text(strip=True).lower()
            classes = " ".join(link.get("class", []))
            rel = link.get("rel", [])

            if (
                "next" in text
                or "next" in classes
                or "next" in rel
                or "\u00bb" in text
                or "\u203a" in text
                or ">" == text
            ):
                href = link.get("href", "")
                if href:
                    return urljoin(current_url, href)

        # Strategy 2: Look for page number links
        current_page_match = re.search(r"[?&]page=(\d+)", current_url)
        if current_page_match:
            next_num = int(current_page_match.group(1)) + 1
            return re.sub(r"([?&]page=)\d+", f"\\g<1>{next_num}", current_url)

        # Strategy 3: Path-based pagination (e.g., /page/2/)
        path_match = re.search(r"/page/(\d+)", current_url)
        if path_match:
            next_num = int(path_match.group(1)) + 1
            return re.sub(r"/page/\d+", f"/page/{next_num}", current_url)

        return None

    def _is_image_url(self, url: str) -> bool:
        """Check if URL looks like an image file."""
        parsed = urlparse(url.split("?")[0])
        ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""
        return f".{ext}" in IMAGE_EXTENSIONS

    def _is_excluded(self, url: str) -> bool:
        """Check if URL matches exclusion patterns."""
        url_lower = url.lower()
        return any(re.search(p, url_lower) for p in EXCLUDE_PATTERNS)

    def _score_url(self, url: str) -> int:
        """Score a URL based on how likely it is to be a high-res wallpaper."""
        score = 1  # Base score for being an image
        url_lower = url.lower()
        for pattern in HIGHRES_PATTERNS:
            if re.search(pattern, url_lower):
                score += 1
        # Penalize very short paths (likely thumbnails)
        path = urlparse(url).path
        if len(path) < 10:
            score -= 1
        return max(0, score)

    def _find_highres_source(self, img, page_url: str) -> Optional[str]:
        """Look for higher-resolution versions in srcset, picture, or data attributes."""
        if img.parent and img.parent.name == "picture":
            for source_elem in img.parent.find_all("source"):
                srcset = source_elem.get("srcset", "")
                best = self._parse_srcset(srcset, page_url)
                if best:
                    return best

        srcset = img.get("srcset", "")
        if srcset:
            best = self._parse_srcset(srcset, page_url)
            if best:
                return best

        for attr in ["data-src", "data-original", "data-full", "data-large",
                     "data-zoom", "data-hires", "data-raw-src", "data-2x"]:
            val = img.get(attr, "")
            if val and not val.startswith("data:"):
                return urljoin(page_url, val)

        return None

    def _parse_srcset(self, srcset: str, page_url: str) -> Optional[str]:
        """Parse srcset attribute and return the highest-resolution URL."""
        if not srcset:
            return None
        candidates = []
        for entry in srcset.split(","):
            parts = entry.strip().split()
            if not parts:
                continue
            url = urljoin(page_url, parts[0])
            sort_val = 0
            if len(parts) >= 2:
                descriptor = parts[1]
                if descriptor.endswith("w"):
                    try:
                        sort_val = int(descriptor[:-1])
                    except ValueError:
                        pass
                elif descriptor.endswith("x"):
                    try:
                        sort_val = int(float(descriptor[:-1]) * 1000)
                    except ValueError:
                        pass
            candidates.append((url, sort_val))
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return candidates[0][0]
        return None

    def _parse_dim(self, val: str) -> int:
        """Parse dimension value from HTML attribute."""
        if not val:
            return 0
        try:
            return int(re.sub(r"[^\d]", "", str(val)))
        except (ValueError, TypeError):
            return 0

    def _make_image(
        self, url: str, thumb: str, alt: str, title: str,
        page_url: str, element=None, score: int = 0,
        width: int = 0, height: int = 0,
    ) -> ScrapedImage:
        """Create a ScrapedImage from parsed data."""
        artist = ""
        artist_link = ""
        tags = ""

        if element is not None:
            parent = element.parent if hasattr(element, 'parent') else None
            for _ in range(3):
                if parent is None:
                    break
                for link in parent.find_all("a", limit=5) if hasattr(parent, 'find_all') else []:
                    href = link.get("href", "") or ""
                    text = link.get_text(strip=True)
                    if any(k in href.lower() for k in ["user", "artist", "profile", "author", "photographer"]):
                        artist = text
                        artist_link = href
                        break
                if artist:
                    break
                parent = getattr(parent, 'parent', None)

            if hasattr(element, 'parent') and element.parent:
                tag_elems = element.parent.find_all("a", class_=re.compile(r"tag", re.I), limit=20)
                if tag_elems:
                    tags = ", ".join(t.get_text(strip=True) for t in tag_elems if t.get_text(strip=True))

        return ScrapedImage(
            url=url,
            thumbnail_url=thumb,
            alt=alt,
            title=title,
            artist=artist,
            artist_link=artist_link,
            tags=tags,
            width=width,
            height=height,
            page_url=page_url,
        )

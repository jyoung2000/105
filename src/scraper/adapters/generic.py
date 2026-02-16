"""Generic wallpaper adapter — works on any wallpaper site without site-specific code."""
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
MIN_AREA = MIN_WIDTH * MIN_HEIGHT

# URL patterns that suggest high-resolution images
HIGHRES_PATTERNS = [
    r"original", r"full", r"download", r"highres", r"large",
    r"(\d{3,4})x(\d{3,4})", r"4k", r"uhd", r"2160", r"1440", r"1080",
]

# Patterns to exclude (thumbnails, icons, UI elements)
EXCLUDE_PATTERNS = [
    r"logo", r"icon", r"avatar", r"banner", r"sprite",
    r"placeholder", r"loading", r"spinner", r"ad[_-]",
    r"facebook", r"twitter", r"instagram", r"pinterest",
    r"google", r"analytics", r"tracking", r"pixel",
    r"btn", r"button", r"arrow", r"close", r"menu",
    r"1x1", r"spacer", r"blank", r"transparent",
]

# Image extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


class GenericAdapter(BaseAdapter):
    """Universal wallpaper adapter using heuristics to find wallpaper images on any site."""

    def __init__(self, min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT):
        self.min_width = min_width
        self.min_height = min_height

    async def scrape(self, html: str, page_url: str) -> list[ScrapedImage]:
        """Parse HTML and find wallpaper-quality images."""
        soup = BeautifulSoup(html, "lxml")
        images = []
        seen_urls = set()
        base_domain = urlparse(page_url).netloc

        # Strategy 1: Find direct high-res image links
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
            if not src:
                continue
            abs_url = urljoin(page_url, src)
            if abs_url in seen_urls:
                continue

            # Check for high-res sources in srcset or data attributes
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

        # Sort by score (highest first) and return
        images.sort(key=lambda x: x.width * x.height if x.width and x.height else 0, reverse=True)
        logger.info(f"Found {len(images)} potential wallpapers on {page_url}")
        return images

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
                or "»" in text
                or "›" in text
                or ">" == text
            ):
                href = link.get("href", "")
                if href:
                    return urljoin(current_url, href)

        # Strategy 2: Look for page number links
        parsed = urlparse(current_url)
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
        if len(path) < 15:
            score -= 1
        return max(0, score)

    def _find_highres_source(self, img, page_url: str) -> Optional[str]:
        """Look for higher-resolution versions in srcset or data attributes."""
        srcset = img.get("srcset", "")
        if srcset:
            candidates = []
            for entry in srcset.split(","):
                parts = entry.strip().split()
                if len(parts) >= 1:
                    url = urljoin(page_url, parts[0])
                    width = 0
                    if len(parts) >= 2 and parts[1].endswith("w"):
                        try:
                            width = int(parts[1][:-1])
                        except ValueError:
                            pass
                    candidates.append((url, width))
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                return candidates[0][0]

        # Check data attributes for high-res
        for attr in ["data-src", "data-original", "data-full", "data-large", "data-zoom"]:
            val = img.get(attr, "")
            if val:
                return urljoin(page_url, val)

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
            # Try to find artist info from nearby elements
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

            # Try to extract tags from nearby elements
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

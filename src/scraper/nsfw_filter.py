"""NSFW/adult content filter for the wallpaper scraper.

Detects adult content via URL patterns, HTML meta tags, page text,
and image tags/metadata. Used to skip NSFW images when allow_nsfw is False.
"""
import re
from urllib.parse import urlparse
from src.utils.logging import setup_logging

logger = setup_logging("nsfw_filter")

# URL path/query keywords that strongly indicate NSFW content
NSFW_URL_KEYWORDS = [
    "nsfw", "adult", "xxx", "porn", "hentai", "nude", "naked",
    "erotic", "sexy", "lewd", "ecchi", "r18", "r-18",
    "explicit", "mature-content", "not-safe-for-work",
    "/nsfw/", "/adult/", "/18+/", "/xxx/",
]

# Words in page text, titles, or tags that indicate NSFW content
NSFW_TEXT_KEYWORDS = [
    "nsfw", "nude", "naked", "porn", "hentai", "xxx",
    "erotic", "topless", "explicit content", "adult content",
    "18+", "r18", "r-18", "lewd", "ecchi",
    "not safe for work", "sexually explicit",
]

# HTML meta tag values indicating adult/NSFW ratings
NSFW_META_RATINGS = [
    "adult", "mature", "rta-5042-1996-1400-1577-",
    "restricted", "18+",
]

# Compiled patterns for efficiency
_URL_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in NSFW_URL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)
_TEXT_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in NSFW_TEXT_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_nsfw_url(url: str) -> bool:
    """Check if a URL contains NSFW indicators."""
    url_lower = url.lower()
    return bool(_URL_PATTERN.search(url_lower))


def is_nsfw_page(html: str, page_url: str) -> bool:
    """Check if a page's HTML contains NSFW indicators.

    Checks meta tags (rating, classification), page title, and body text.
    """
    if not html:
        return False

    html_lower = html[:10000].lower()  # Only check first 10KB for speed

    # Check meta tags for adult ratings
    # <meta name="rating" content="adult">
    meta_patterns = [
        r'<meta\s+[^>]*name\s*=\s*["\']rating["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
        r'<meta\s+[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*name\s*=\s*["\']rating["\']',
        r'<meta\s+[^>]*property\s*=\s*["\']rating["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
    ]
    for pattern in meta_patterns:
        match = re.search(pattern, html_lower)
        if match:
            rating = match.group(1).strip().lower()
            if any(r in rating for r in NSFW_META_RATINGS):
                logger.debug(f"NSFW meta rating detected: {rating} on {page_url}")
                return True

    # Check page title
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html_lower)
    if title_match:
        title = title_match.group(1)
        if _TEXT_PATTERN.search(title):
            logger.debug(f"NSFW keyword in page title on {page_url}")
            return True

    # Check URL
    if is_nsfw_url(page_url):
        return True

    return False


def is_nsfw_image(url: str, alt: str = "", title: str = "",
                  tags: str = "", page_url: str = "") -> bool:
    """Check if an image's metadata suggests NSFW content.

    Checks the image URL, alt text, title, tags, and source page URL.
    """
    # Check image URL
    if is_nsfw_url(url):
        return True

    # Check text metadata
    combined_text = f"{alt} {title} {tags}".strip()
    if combined_text and _TEXT_PATTERN.search(combined_text):
        return True

    # Check source page URL
    if page_url and is_nsfw_url(page_url):
        return True

    return False

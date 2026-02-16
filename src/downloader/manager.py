"""Download manager — streams images to disk, respects rate limits."""
import hashlib
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
import httpx
from src.utils.paths import data_path
from src.utils.logging import setup_logging
from src.utils.rate_limiter import RateLimiter

logger = setup_logging("downloader")

TEMP_DIR = data_path("temp")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class DownloadManager:
    """Manages image downloads with streaming to disk."""

    def __init__(self, max_concurrent: int = 3, min_delay: float = 1.0):
        self.rate_limiter = RateLimiter(max_concurrent=max_concurrent, min_delay=min_delay)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                http2=True,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
        return self._client

    async def download(self, url: str) -> Optional[Path]:
        """Download image to temp dir, streaming to disk. Returns file path or None."""
        domain = urlparse(url).netloc
        try:
            await self.rate_limiter.acquire(domain)
            try:
                return await self._stream_download(url)
            finally:
                self.rate_limiter.release()
        except Exception as e:
            logger.error(f"Download failed for {url}: {e}")
            return None

    async def _stream_download(self, url: str) -> Optional[Path]:
        """Stream download to a temp file."""
        client = await self._get_client()
        url_hash = hashlib.md5(url.encode()).hexdigest()[:16]
        ext = self._get_extension(url)
        temp_path = TEMP_DIR / f"dl_{url_hash}{ext}"

        try:
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_length = int(response.headers.get("content-length", 0))
                if content_length > MAX_FILE_SIZE:
                    logger.warning(f"File too large ({content_length} bytes): {url}")
                    return None

                total = 0
                with open(temp_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        total += len(chunk)
                        if total > MAX_FILE_SIZE:
                            logger.warning(f"File exceeded max size during download: {url}")
                            temp_path.unlink(missing_ok=True)
                            return None
                        f.write(chunk)

            if total < 5000:
                logger.debug(f"File too small ({total} bytes), likely not a wallpaper: {url}")
                temp_path.unlink(missing_ok=True)
                return None

            logger.debug(f"Downloaded {total} bytes to {temp_path}")
            return temp_path

        except httpx.HTTPStatusError as e:
            logger.warning(f"HTTP {e.response.status_code} for {url}")
            temp_path.unlink(missing_ok=True)
            return None
        except Exception as e:
            logger.error(f"Stream download error for {url}: {e}")
            temp_path.unlink(missing_ok=True)
            return None

    def _get_extension(self, url: str) -> str:
        """Get file extension from URL."""
        path = urlparse(url).path.split("?")[0]
        if "." in path:
            ext = "." + path.rsplit(".", 1)[-1].lower()
            if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}:
                return ext
        return ".jpg"

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

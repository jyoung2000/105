"""Scraper engine — full pipeline from URL to Baserow."""
import re
import uuid
import asyncio
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from src.scraper.browser import browser_manager
from src.scraper.adapters.generic import GenericAdapter
from src.downloader.manager import DownloadManager
from src.downloader.compressor import ImageCompressor
from src.downloader.validator import ImageValidator
from src.ai.captioner import AICaptioner
from src.storage.baserow import BaserowClient
from src.storage.config_store import config_store
from src.storage.activity_store import ActivityStore, ActivityEntry, activity_store
from src.storage.site_profiles import site_profiles
from src.scraper.discovery import discovery_engine
from src.metadata.schemas import WallpaperMetadata
from src.utils.aspect_ratio import calculate_aspect_ratio, is_mobile
from src.utils.paths import data_path
from src.utils.logging import setup_logging

logger = setup_logging("engine")

TEMP_DIR = data_path("temp")


class ScrapeResult:
    """Result of a single image scrape."""
    def __init__(self):
        self.success = False
        self.status = "error"
        self.error = ""
        self.img_hash = ""
        self.baserow_row_id = None


class ScrapeJob:
    """Represents a scrape job with progress tracking."""
    def __init__(self, job_id: str, url: str, source_id: str = "", source_name: str = "", max_pages: int = 10):
        self.id = job_id
        self.url = url
        self.source_id = source_id
        self.source_name = source_name
        self.max_pages = max_pages
        self.status = "pending"
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.pages_scraped = 0
        self.images_found = 0
        self.images_downloaded = 0
        self.images_uploaded = 0
        self.duplicates = 0
        self.errors = 0
        self.error_log: list[str] = []
        self.progress = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "pages_scraped": self.pages_scraped,
            "images_found": self.images_found,
            "images_downloaded": self.images_downloaded,
            "images_uploaded": self.images_uploaded,
            "duplicates": self.duplicates,
            "errors": self.errors,
            "error_log": self.error_log[-20:],
            "progress": self.progress,
            "max_pages": self.max_pages,
        }


class ScraperEngine:
    """Main scraper engine orchestrating the full pipeline."""

    def __init__(self):
        self.downloader = DownloadManager()
        self.compressor = ImageCompressor()
        self.captioner = AICaptioner()
        self.baserow = BaserowClient()
        self._job_lock = asyncio.Lock()
        self._current_job: Optional[ScrapeJob] = None
        self._job_history: list[dict] = []

    def _get_adapter(self) -> GenericAdapter:
        """Get adapter configured with current scraping settings."""
        min_w = config_store.get("scraping", "min_width", default=800)
        min_h = config_store.get("scraping", "min_height", default=600)
        return GenericAdapter(min_width=min_w, min_height=min_h)

    def _get_validator(self) -> ImageValidator:
        """Get validator configured with current scraping settings."""
        min_w = config_store.get("scraping", "min_width", default=800)
        min_h = config_store.get("scraping", "min_height", default=600)
        allowed_aspects = config_store.get("scraping", "allowed_aspects", default=[])
        allow_mobile = config_store.get("scraping", "allow_mobile", default=True)
        watermark_detection = config_store.get("scraping", "watermark_detection", default=True)
        return ImageValidator(
            min_width=min_w, min_height=min_h,
            allowed_aspects=allowed_aspects, allow_mobile=allow_mobile,
            watermark_detection=watermark_detection,
        )

    async def initialize(self):
        """Initialize engine components (non-fatal)."""
        try:
            await browser_manager.initialize()
        except Exception as e:
            logger.warning(f"Browser init failed (non-fatal): {e}")

        try:
            await self.captioner.initialize()
        except Exception as e:
            logger.warning(f"AI captioner init failed (non-fatal): {e}")

        # Load Baserow config
        try:
            cfg = config_store.get_section("baserow")
            self.baserow = BaserowClient(
                api_url=cfg.get("api_url", ""),
                api_token=cfg.get("api_token", ""),
                table_id=cfg.get("table_id", 0),
            )
            self.baserow.field_mapping = cfg.get("field_mapping", {})
        except Exception as e:
            logger.warning(f"Baserow config load failed: {e}")

    def update_baserow_config(self):
        """Reload Baserow config from store."""
        cfg = config_store.get_section("baserow")
        self.baserow = BaserowClient(
            api_url=cfg.get("api_url", ""),
            api_token=cfg.get("api_token", ""),
            table_id=cfg.get("table_id", 0),
        )
        self.baserow.field_mapping = cfg.get("field_mapping", {})

    async def scrape_url(self, url: str, source_id: str = "", source_name: str = "", max_pages: int = 10) -> ScrapeJob:
        """Scrape a URL and process all found wallpapers."""
        job_id = uuid.uuid4().hex[:12]
        job = ScrapeJob(job_id, url, source_id, source_name or urlparse(url).netloc, max_pages)

        async with self._job_lock:
            if self._current_job and self._current_job.status == "running":
                job.status = "queued"
                return job

        job.status = "running"
        job.started_at = datetime.now().isoformat()
        self._current_job = job

        try:
            await self._run_pipeline(job)
        except Exception as e:
            logger.error(f"Pipeline error for {url}: {e}")
            job.error_log.append(str(e))
            job.errors += 1
        finally:
            job.status = "completed"
            job.completed_at = datetime.now().isoformat()
            job.progress = 100.0
            self._job_history.append(job.to_dict())
            if len(self._job_history) > 100:
                self._job_history = self._job_history[-100:]
            self._current_job = None

        return job

    async def _run_pipeline(self, job: ScrapeJob):
        """Execute the full scrape pipeline."""
        if not browser_manager.is_available:
            logger.warning("Browser not available, attempting to initialize...")
            success = await browser_manager.initialize()
            if not success:
                job.error_log.append("Browser not available")
                return

        # Create adapter/validator from current config each run
        adapter = self._get_adapter()
        validator = self._get_validator()
        scroll_count = config_store.get("scraping", "scroll_count", default=5)
        scroll_wait = config_store.get("scraping", "scroll_wait_ms", default=800)

        # Load site profile for this domain — remembers site structure
        profile = site_profiles.get(job.url)

        current_url = job.url
        consecutive_blocked = 0
        for page_num in range(1, job.max_pages + 1):
            logger.info(f"Scraping page {page_num}: {current_url}")
            job.pages_scraped = page_num

            try:
                html = await browser_manager.get_page_content(
                    current_url, scroll_count=scroll_count, scroll_wait_ms=scroll_wait
                )
            except Exception as e:
                logger.error(f"Failed to load page {current_url}: {e}")
                job.error_log.append(f"Page load failed: {e}")
                break

            # Check if the gallery page itself is blocked
            if self._page_is_blocked(html):
                consecutive_blocked += 1
                logger.warning(
                    f"Gallery page {page_num} appears blocked ({consecutive_blocked} in a row): {current_url}"
                )
                if consecutive_blocked >= 2:
                    logger.warning("Site is blocking gallery pages — stopping")
                    break
                # Wait longer before trying next page
                await asyncio.sleep(5 + random.random() * 5)
                # Try to continue to next page anyway
                try:
                    next_url = await adapter.get_next_page_url(html, current_url, page_num)
                    if next_url:
                        current_url = next_url
                        continue
                except Exception:
                    pass
                break
            else:
                consecutive_blocked = 0

            # Discover categories/collections on the page for future variety
            try:
                cats = adapter.discover_categories(html, current_url)
                if cats:
                    profile.add_categories(cats)
                    # Also register category URLs as gallery URLs for future visits
                    for cat in cats:
                        profile.add_gallery_url(cat["url"], cat.get("label", ""))
                    logger.info(f"Discovered {len(cats)} category/collection links on {current_url}")
            except Exception as e:
                logger.debug(f"Category discovery error: {e}")

            # Discover outbound links to other wallpaper sites (passive discovery)
            try:
                outbound = discovery_engine.discover_outbound_links(html, current_url)
                for ob in outbound[:3]:  # Limit to 3 per page to avoid spam
                    from src.scheduler.source_manager import source_manager as sm
                    if not sm.domain_exists(ob["domain"]):
                        sm.add_source(
                            url=ob["url"],
                            name=f"{ob['domain']} (outbound)",
                            category="discovered",
                            discovered_by_query="(outbound-link)",
                            validation_score=0,  # Will be validated on first scrape
                        )
                        logger.info(f"Auto-added outbound wallpaper site: {ob['domain']}")
            except Exception as e:
                logger.debug(f"Outbound link discovery error: {e}")

            # Check for detail page links FIRST — listing pages have thumbnails
            # linking to detail pages where full-size images live.
            detail_links = adapter.get_detail_page_links(html, current_url)
            if detail_links:
                # Filter out already-visited detail pages (save time on revisits)
                fresh_links = [
                    dl for dl in detail_links
                    if not profile.is_visited(dl["url"])
                ]
                skipped = len(detail_links) - len(fresh_links)
                if skipped > 0:
                    logger.info(f"Skipping {skipped} already-visited detail pages")

                if fresh_links:
                    logger.info(f"Found {len(fresh_links)} fresh detail page links on page {page_num} — following for full-res images")
                    images = await self._scrape_detail_pages(
                        fresh_links, adapter, job, scroll_count, scroll_wait,
                        profile, gallery_url=current_url
                    )
                    logger.info(f"Got {len(images)} full-res images from detail pages")
                else:
                    logger.info(f"All {len(detail_links)} detail links already visited — skipping")
                    images = []
            else:
                # No detail links — this might be a detail page itself
                images = await adapter.scrape(html, current_url)
                logger.info(f"Found {len(images)} direct images on page {page_num} (no detail links)")

            job.images_found += len(images)

            # Process images
            for i, img in enumerate(images):
                try:
                    result = await self._process_image(img, job, validator)
                    if result.status == "uploaded":
                        job.images_uploaded += 1
                    elif result.status == "duplicate":
                        job.duplicates += 1
                    elif result.status == "error":
                        job.errors += 1
                        if result.error:
                            logger.debug(f"Image skip: {result.error} - {img.url[:80]}")
                except Exception as e:
                    logger.error(f"Image processing error: {e}")
                    job.errors += 1
                    job.error_log.append(f"Image error: {e}")

                # Update progress
                total_expected = job.images_found
                done = job.images_uploaded + job.duplicates + job.errors
                job.progress = min(95.0, (done / max(total_expected, 1)) * 100)

            # Try to find next page
            try:
                next_url = await adapter.get_next_page_url(html, current_url, page_num)
                if not next_url:
                    logger.info("No more pages found")
                    # Update hints about pagination
                    if page_num == 1:
                        profile.update_hints(has_pagination=False)
                    break
                else:
                    profile.update_hints(has_pagination=True)
                current_url = next_url
            except Exception:
                break

            # Human-like delay between gallery pages (4-7s)
            await asyncio.sleep(4 + random.random() * 3)

        # Release the persistent browser page for this site
        await browser_manager.release_site_page()

        # Record gallery URL scrape stats and overall stats
        profile.record_gallery_scrape(job.url, job.images_found)
        profile.record_scrape_stats(job.images_found, job.images_uploaded)
        profile.save()

    @staticmethod
    def _page_is_blocked(html: str) -> bool:
        """Check if the returned HTML is a challenge/block page, not real content."""
        if not html or len(html) < 500:
            return True
        text = html[:2000].lower()
        signals = [
            "checking your browser", "just a moment", "verify you are human",
            "attention required", "enable javascript and cookies",
            "ddos protection", "access denied", "cf-browser-verification",
            "_cf_chl", "challenge-platform",
        ]
        # If challenge signals are present AND there are very few images, it's blocked
        has_challenge = any(s in text for s in signals)
        if has_challenge:
            return True
        # Also check for very sparse pages (captcha pages have almost no <img> tags)
        img_count = html.lower().count("<img")
        if img_count == 0 and len(html) < 5000:
            return True
        return False

    async def _scrape_detail_pages(self, detail_links: list[dict], adapter, job: ScrapeJob,
                                    scroll_count: int, scroll_wait: int,
                                    profile=None, gallery_url: str = "") -> list:
        """Visit individual detail/wallpaper pages to find full-size images.

        Uses the gallery URL as referer (like clicking a thumbnail on the listing page).
        Includes adaptive back-off: if consecutive pages return 0 images (likely
        blocked), the delay between requests increases to avoid triggering anti-bot.
        """
        all_images = []
        max_details = config_store.get("scraping", "max_pages", default=10)
        # Limit detail pages per listing page to avoid runaway scraping
        links_to_visit = detail_links[:min(len(detail_links), max_details * 3)]

        consecutive_failures = 0
        base_delay = 3.0  # seconds — starts at 3-5s, increases on failures

        for i, link_info in enumerate(links_to_visit):
            detail_url = link_info["url"]
            try:
                logger.info(f"Visiting detail page {i+1}/{len(links_to_visit)}: {detail_url}")
                # Use more scrolls on detail pages to trigger lazy-loading
                # (collection pages can have many images below the fold)
                html = await browser_manager.get_page_content(
                    detail_url, scroll_count=max(scroll_count, 8),
                    scroll_wait_ms=scroll_wait,
                    referer=gallery_url,
                )

                # Detect blocked/challenge pages before parsing
                if self._page_is_blocked(html):
                    consecutive_failures += 1
                    logger.warning(
                        f"Detail page appears blocked ({consecutive_failures} in a row): {detail_url}"
                    )
                    if consecutive_failures >= 3:
                        logger.warning(
                            f"Site is blocking requests — stopping detail page crawl after "
                            f"{consecutive_failures} consecutive blocked pages"
                        )
                        break
                    # Back off significantly before trying next page
                    backoff = base_delay * (2 ** consecutive_failures) + random.random() * 3
                    logger.info(f"Backing off {backoff:.1f}s before next detail page")
                    await asyncio.sleep(backoff)
                    continue

                images = await adapter.scrape(html, detail_url)

                # Mark page as visited in site profile
                if profile:
                    profile.mark_visited(detail_url)

                if images:
                    consecutive_failures = 0  # Reset on success
                    # Carry forward metadata from the thumbnail link
                    for img in images:
                        if not img.alt and link_info.get("alt"):
                            img.alt = link_info["alt"]
                        if not img.title and link_info.get("title"):
                            img.title = link_info["title"]
                    all_images.extend(images)
                    logger.info(f"Found {len(images)} images on detail page {detail_url}")

                    # Record hints about what worked on this site
                    if profile:
                        profile.update_hints(has_download_buttons=True)
                else:
                    consecutive_failures += 1
                    logger.debug(f"No images found on detail page {detail_url} ({consecutive_failures} in a row)")
                    if consecutive_failures >= 5:
                        logger.warning(
                            f"Stopping detail crawl — {consecutive_failures} consecutive pages "
                            f"with no images (adapter may not match this site's layout)"
                        )
                        break
            except Exception as e:
                consecutive_failures += 1
                logger.warning(f"Failed to scrape detail page {detail_url}: {e}")
                job.error_log.append(f"Detail page error: {e}")

            # Adaptive delay: longer when failures are accumulating
            delay = base_delay + random.random() * 2
            if consecutive_failures > 0:
                delay += consecutive_failures * 1.5  # Extra 1.5s per consecutive failure
            await asyncio.sleep(delay)

        # Batch save visited pages
        if profile:
            profile.save()

        return all_images

    async def _process_image(self, img, job: ScrapeJob, validator: ImageValidator = None) -> ScrapeResult:
        """Process a single image through the full pipeline."""
        result = ScrapeResult()
        temp_files = []
        if validator is None:
            validator = self._get_validator()

        try:
            # Download (with referer for hotlink protection)
            logger.info(f"Downloading: {img.url[:100]}")
            dl_path = await self.downloader.download(img.url, referer=img.page_url)
            if dl_path is None:
                result.error = "Download failed"
                logger.warning(f"Download failed: {img.url[:100]}")
                return result
            temp_files.append(dl_path)
            job.images_downloaded += 1

            # Validate
            is_valid, reason = validator.validate(dl_path)
            if not is_valid:
                result.error = f"Validation failed: {reason}"
                logger.info(f"Validation failed ({reason}): {img.url[:80]}")
                return result

            # Compress
            compress_result = self.compressor.compress(dl_path, job.source_name)
            if compress_result is None:
                result.error = "Compression failed"
                return result
            compressed_path, img_hash, width, height, file_size_kb = compress_result
            temp_files.append(compressed_path)
            result.img_hash = img_hash

            # Generate thumbnail
            thumb_path = self.compressor.generate_thumbnail(compressed_path, img_hash)

            # Dedup check
            if self.baserow.is_configured:
                is_dupe = await self.baserow.check_duplicate(img_hash)
                if is_dupe:
                    result.status = "duplicate"
                    self._log_activity(job, img, img_hash, width, height, file_size_kb,
                                       thumb_path or "", None, "duplicate")
                    return result

            # AI captioning
            title, alt_text, tags = await self.captioner.caption(compressed_path)

            # Use scraped metadata as fallback, but clean it first
            # (HTML alt/title often contain site names, dimensions, junk)
            if img.title and not title:
                title = self._clean_scraped_text(img.title)
            if img.alt and not alt_text:
                alt_text = self._clean_scraped_text(img.alt)
            if img.tags and not tags:
                tags = self._clean_scraped_tags(img.tags)

            # Build metadata
            aspect = calculate_aspect_ratio(width, height)
            mobile = is_mobile(width, height)

            metadata = WallpaperMetadata(
                wallpaperTitle=title,
                Width=width,
                Height=height,
                imgUrl=img.url,
                altText=alt_text,
                artistText=img.artist,
                artistLink=img.artist_link,
                isMobile=mobile,
                isReported=False,
                isVip=False,
                categoryTags=tags,
                imgHash=img_hash,
                aspect_ratio=aspect,
            )

            # Upload to Baserow
            row_id = None
            if self.baserow.is_configured:
                # Upload file first
                file_obj = await self.baserow.upload_file(compressed_path)
                if file_obj:
                    metadata.imageFile = [{"name": file_obj.get("name", ""), "visible_name": file_obj.get("visible_name", "")}]

                # Create row with mapped fields
                row_data = metadata.to_baserow_dict(self.baserow.field_mapping)
                row = await self.baserow.create_row(row_data)
                if row:
                    row_id = row.get("id")
                    result.baserow_row_id = row_id
                    logger.info(f"Uploaded to Baserow: row {row_id}")

            result.success = True
            result.status = "uploaded"
            logger.info(f"Processed {width}x{height} wallpaper: {title or img.url[:60]}")

            # Log activity
            self._log_activity(job, img, img_hash, width, height, file_size_kb,
                               thumb_path or "", row_id, "uploaded",
                               title=title, alt_text=alt_text, tags=tags, aspect=aspect, mobile=mobile)

            return result

        except Exception as e:
            result.error = str(e)
            result.status = "error"
            self._log_activity(job, img, result.img_hash, 0, 0, 0, "", None, "error", error=str(e))
            return result

        finally:
            # Clean up temp files (NOT thumbnails)
            for tf in temp_files:
                try:
                    if tf.exists():
                        tf.unlink()
                except Exception:
                    pass

    # Regex for stripping site names and junk from scraped HTML metadata
    _SITE_NAME_RE = re.compile(
        r"\b(wallpaper[s]?|background[s]?|desktop|hd|4k|uhd|1080p|2k|"
        r"free download|download|stock photo|royalty.?free|"
        r"wallhaven|unsplash|pexels|pixabay|wallpaperscraft|wallpaperflare|"
        r"wallpaperaccess|wallpaperbat|wallpapercave|wallpaperbetter|"
        r"hdwallpapers|getwallpapers|peakpx|setaswall|pixel4k|"
        r"4kwallpapers|uhdpaper|goodfon|fonwall|rawpixel|freepik)\b",
        re.I,
    )
    _JUNK_RE = re.compile(
        r"^\d+x\d+$|^[\w-]{20,}$|^\d+$|^IMG_|^DSC_|^DSCN|"
        r"^photo-\d|\.jpe?g$|\.png$|\.webp$",
        re.I,
    )
    _DIMENSION_RE = re.compile(r"\b\d{3,5}\s*[x×]\s*\d{3,5}\b")
    _PREFIX_RE = re.compile(
        r"^(a\s+)?(photo|image|picture|wallpaper|background)\s+(of|from)\s+",
        re.I,
    )

    def _clean_scraped_text(self, text: str) -> str:
        """Clean scraped title/alt text — remove site names, dimensions, junk."""
        if not text:
            return ""
        # Skip pure junk
        if self._JUNK_RE.search(text.strip()):
            return ""
        # Remove dimensions like "1920x1080"
        text = self._DIMENSION_RE.sub("", text)
        # Remove site names
        text = self._SITE_NAME_RE.sub("", text)
        # Remove generic prefixes
        text = self._PREFIX_RE.sub("", text)
        # Remove separators commonly used in page titles: " | SiteName", " - SiteName"
        text = re.sub(r"\s*[|–—-]\s*$", "", text)
        text = re.sub(r"\s*[|–—-]\s*\S+\.(com|net|org|io|cc)\b.*$", "", text, flags=re.I)
        # Clean whitespace
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^[,.\-–—:;|]+\s*", "", text).strip()
        text = re.sub(r"[,.\-–—:;|]+\s*$", "", text).strip()
        if not text or len(text) < 3:
            return ""
        # Capitalize first letter
        return text[0].upper() + text[1:]

    def _clean_scraped_tags(self, tags: str) -> str:
        """Clean scraped tags — remove site names and junk tags."""
        if not tags:
            return ""
        cleaned = []
        for tag in tags.split(","):
            tag = tag.strip().lower()
            tag = self._SITE_NAME_RE.sub("", tag).strip()
            if tag and len(tag) > 1 and not self._JUNK_RE.search(tag):
                cleaned.append(tag)
        return ", ".join(cleaned[:20])

    def _log_activity(self, job, img, img_hash, width, height, file_size_kb,
                      thumb_path, row_id, status, title="", alt_text="", tags="",
                      aspect="", mobile=False, error=""):
        """Log an activity entry."""
        try:
            entry = ActivityEntry(
                id=uuid.uuid4().hex[:12],
                timestamp=datetime.now().isoformat(),
                source_id=job.source_id,
                source_name=job.source_name,
                job_id=job.id,
                thumbnail_path=thumb_path,
                title=title,
                alt_text=alt_text,
                tags=tags,
                width=width,
                height=height,
                aspect_ratio=aspect,
                is_mobile=mobile,
                img_url=img.url if img else "",
                img_hash=img_hash,
                baserow_row_id=row_id,
                file_size_kb=file_size_kb,
                status=status,
                error_message=error,
            )
            activity_store.add_entry(entry)
        except Exception as e:
            logger.warning(f"Failed to log activity: {e}")

    @property
    def current_job(self) -> Optional[dict]:
        if self._current_job:
            return self._current_job.to_dict()
        return None

    @property
    def job_history(self) -> list[dict]:
        return list(self._job_history)

    @property
    def is_busy(self) -> bool:
        return self._current_job is not None and self._current_job.status == "running"


# Singleton
scraper_engine = ScraperEngine()

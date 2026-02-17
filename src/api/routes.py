"""REST API routes for the wallpaper scraper."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query, UploadFile, File
from fastapi.responses import StreamingResponse
import httpx
from src.api.models import (
    ScrapeRequest, SourceCreate, SourceUpdate, SourceReorder,
    QueryCreate, QueryUpdate, BaserowConfig,
    FieldMappingUpdate, SettingsUpdate,
)
from src.api.jobs import job_queue
from src.scraper.engine import scraper_engine
from src.scraper.discovery import discovery_engine
from src.scheduler.scheduler import scheduler
from src.scheduler.source_manager import source_manager
from src.storage.config_store import config_store
from src.storage.activity_store import activity_store
from src.storage.baserow import BaserowClient
from src.metadata.schemas import DEFAULT_FIELD_MAPPING
from src.utils.paths import data_path
from src.utils.logging import setup_logging

logger = setup_logging("api")
router = APIRouter(prefix="/api")

STATS_PATH = data_path("config", "stats.json")


# === Health ===

@router.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "browser_available": True,  # Will be checked properly
        "ai_available": scraper_engine.captioner.is_available,
        "baserow_configured": scraper_engine.baserow.is_configured,
    }


# === Manual Scraping ===

@router.post("/scrape")
async def start_scrape(req: ScrapeRequest, background_tasks: BackgroundTasks):
    if scraper_engine.is_busy:
        raise HTTPException(400, "A scrape job is already running")

    async def run_job():
        job = await scraper_engine.scrape_url(
            url=req.url,
            source_id=req.source_id,
            source_name=req.source_name,
            max_pages=req.max_pages,
        )
        job_queue.add_job(job.to_dict() if hasattr(job, 'to_dict') else job)
        if req.source_id:
            source_manager.record_scrape(
                req.source_id,
                uploaded=job.images_uploaded,
                dupes=job.duplicates,
                errors=job.errors,
            )

    background_tasks.add_task(run_job)
    return {"status": "started", "message": "Scrape job queued"}


@router.get("/jobs")
async def list_jobs():
    current = scraper_engine.current_job
    history = scraper_engine.job_history
    return {
        "current": current,
        "history": history,
        "saved": job_queue.get_all(),
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    current = scraper_engine.current_job
    if current and current.get("id") == job_id:
        return current
    for j in scraper_engine.job_history:
        if j.get("id") == job_id:
            return j
    saved = job_queue.get_job(job_id)
    if saved:
        return saved
    raise HTTPException(404, "Job not found")


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    if job_queue.delete_job(job_id):
        return {"status": "deleted"}
    raise HTTPException(404, "Job not found")


# === Gallery + Activity ===

@router.get("/gallery")
async def gallery(limit: int = 50, offset: int = 0, source_id: str = "",
                  status: str = "", search: str = ""):
    if search:
        entries = activity_store.search(search, limit=limit)
    elif source_id:
        entries = activity_store.get_by_source(source_id, limit=limit)
    elif status:
        entries = activity_store.get_by_status(status, limit=limit)
    else:
        entries = activity_store.get_recent(limit=limit, offset=offset)
    return {
        "entries": entries,
        "total": activity_store.count,
        "limit": limit,
        "offset": offset,
    }


@router.get("/gallery/summary")
async def gallery_summary():
    return activity_store.get_summary()


@router.get("/gallery/{entry_id}")
async def gallery_entry(entry_id: str):
    for e in activity_store.get_recent(limit=5000):
        if e.get("id") == entry_id:
            return e
    raise HTTPException(404, "Entry not found")


# === Sources ===

@router.get("/sources")
async def list_sources():
    return {"sources": source_manager.get_all_sources()}


@router.post("/sources")
async def create_source(data: SourceCreate):
    source = source_manager.add_source(
        url=data.url,
        name=data.name,
        schedule_hours=data.schedule_hours,
    )
    return source


@router.put("/sources/reorder")
async def reorder_sources(data: SourceReorder):
    source_manager.reorder_sources(data.source_ids)
    return {"status": "reordered"}


@router.put("/sources/{source_id}")
async def update_source(source_id: str, data: SourceUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    source = source_manager.update_source(source_id, **updates)
    if source:
        return source
    raise HTTPException(404, "Source not found")


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    if source_manager.remove_source(source_id):
        return {"status": "deleted"}
    raise HTTPException(404, "Source not found")


@router.post("/sources/{source_id}/scrape")
async def scrape_source(source_id: str, background_tasks: BackgroundTasks):
    source = source_manager.get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if scraper_engine.is_busy:
        raise HTTPException(400, "A scrape job is already running")

    async def run_job():
        job = await scraper_engine.scrape_url(
            url=source["url"],
            source_id=source["id"],
            source_name=source.get("name", ""),
            max_pages=source.get("max_pages", 10),
        )
        job_queue.add_job(job.to_dict() if hasattr(job, 'to_dict') else job)
        source_manager.record_scrape(
            source_id,
            uploaded=job.images_uploaded,
            dupes=job.duplicates,
            errors=job.errors,
        )

    background_tasks.add_task(run_job)
    return {"status": "started", "source": source["name"]}


@router.post("/sources/{source_id}/toggle")
async def toggle_source(source_id: str):
    source = source_manager.toggle_source(source_id)
    if source:
        return source
    raise HTTPException(404, "Source not found")


# === Discovery Queries ===

@router.get("/discovery/queries")
async def list_queries():
    return {"queries": source_manager.get_all_queries()}


@router.post("/discovery/queries")
async def create_query(data: QueryCreate):
    query = source_manager.add_query(data.query)
    return query


@router.put("/discovery/queries/{query_id}")
async def update_query(query_id: str, data: QueryUpdate):
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    query = source_manager.update_query(query_id, **updates)
    if query:
        return query
    raise HTTPException(404, "Query not found")


@router.delete("/discovery/queries/{query_id}")
async def delete_query(query_id: str):
    if source_manager.remove_query(query_id):
        return {"status": "deleted"}
    raise HTTPException(400, "Cannot delete query (builtin or not found)")


# === Scheduler + Discovery ===

@router.get("/scheduler/status")
async def scheduler_status():
    from src.scraper.browser import browser_manager
    status = scheduler.status
    status["browser_available"] = browser_manager.is_available
    return status


@router.post("/scheduler/pause")
async def scheduler_pause():
    scheduler.pause()
    return {"status": "paused"}


@router.post("/scheduler/resume")
async def scheduler_resume():
    scheduler.resume()
    return {"status": "resumed"}


@router.get("/discovery/status")
async def discovery_status():
    return {
        "running": discovery_engine.is_running,
        "last_results": discovery_engine.last_results,
        "state": source_manager.discovery_state,
    }


@router.post("/discovery/run")
async def run_discovery(background_tasks: BackgroundTasks):
    if discovery_engine.is_running:
        raise HTTPException(400, "Discovery already running")

    background_tasks.add_task(discovery_engine.run_discovery)
    return {"status": "started"}


@router.get("/status/live")
async def live_status():
    """Comprehensive live status for the GUI — current job, discovery, per-source status."""
    from src.scraper.browser import browser_manager
    from datetime import timedelta

    current_job = scraper_engine.current_job
    disc_state = source_manager.discovery_state

    # Compute next discovery time
    next_discovery = None
    last_run = disc_state.get("last_discovery_run")
    interval_hours = disc_state.get("interval_hours", 6)
    if last_run:
        try:
            last_dt = datetime.fromisoformat(last_run)
            next_dt = last_dt + timedelta(hours=interval_hours)
            next_discovery = next_dt.isoformat()
        except (ValueError, TypeError):
            pass

    # Compute per-source status and next scrape time
    sources_status = []
    now = datetime.now()
    for s in source_manager.get_all_sources():
        status = "idle"
        if current_job and current_job.get("source_id") == s["id"]:
            status = "scraping"
        elif not s.get("enabled", True):
            status = "disabled"
        elif s.get("consecutive_failures", 0) >= 5:
            status = "error"

        next_scrape = None
        if s.get("last_scraped") and s.get("enabled", True):
            try:
                last_dt = datetime.fromisoformat(s["last_scraped"])
                next_dt = last_dt + timedelta(hours=s.get("schedule_hours", 12))
                next_scrape = next_dt.isoformat()
            except (ValueError, TypeError):
                pass

        sources_status.append({
            "id": s["id"],
            "name": s.get("name", ""),
            "status": status,
            "next_scrape": next_scrape,
        })

    return {
        "current_job": current_job,
        "discovery_running": discovery_engine.is_running,
        "discovery_last_results": discovery_engine.last_results,
        "next_discovery": next_discovery,
        "browser_available": browser_manager.is_available,
        "scheduler": scheduler.status,
        "sources_status": sources_status,
    }


# === Baserow + Field Mapping ===

@router.get("/baserow/status")
async def baserow_status():
    cfg = config_store.get_section("baserow")
    return {
        "configured": bool(cfg.get("api_url") and cfg.get("api_token") and cfg.get("table_id")),
        "api_url": cfg.get("api_url", ""),
        "table_id": cfg.get("table_id", 0),
        "field_mapping_verified": cfg.get("field_mapping_verified", False),
    }


@router.put("/baserow/config")
async def update_baserow_config(data: BaserowConfig):
    config_store.set("baserow", "api_url", data.api_url)
    config_store.set("baserow", "api_token", data.api_token)
    config_store.set("baserow", "table_id", data.table_id)
    config_store.save()
    scraper_engine.update_baserow_config()
    return {"status": "saved"}


@router.post("/baserow/test")
async def test_baserow():
    cfg = config_store.get_section("baserow")
    client = BaserowClient(
        api_url=cfg.get("api_url", ""),
        api_token=cfg.get("api_token", ""),
        table_id=cfg.get("table_id", 0),
    )
    result = await client.test_connection()
    await client.close()
    return result


@router.get("/baserow/fields")
async def get_baserow_fields():
    cfg = config_store.get_section("baserow")
    client = BaserowClient(
        api_url=cfg.get("api_url", ""),
        api_token=cfg.get("api_token", ""),
        table_id=cfg.get("table_id", 0),
    )
    try:
        match_result = await client.auto_match_fields()
        # Cache table fields
        config_store.set("baserow", "table_fields_cache", match_result.get("table_fields", []))
        config_store.save()
        return match_result
    except Exception as e:
        raise HTTPException(400, f"Failed to fetch fields: {e}")
    finally:
        await client.close()


@router.get("/baserow/field-mapping")
async def get_field_mapping():
    mapping = config_store.get("baserow", "field_mapping", default=DEFAULT_FIELD_MAPPING)
    return {
        "field_mapping": mapping,
        "defaults": DEFAULT_FIELD_MAPPING,
        "verified": config_store.get("baserow", "field_mapping_verified", default=False),
    }


@router.put("/baserow/field-mapping")
async def update_field_mapping(data: FieldMappingUpdate):
    config_store.set("baserow", "field_mapping", data.field_mapping)
    config_store.set("baserow", "field_mapping_verified", True)
    config_store.save()
    scraper_engine.update_baserow_config()
    return {"status": "saved", "field_mapping": data.field_mapping}


@router.get("/baserow/image-proxy")
async def baserow_image_proxy(url: str = Query(..., description="Baserow file URL to proxy")):
    """Proxy Baserow-hosted images to avoid CORS/auth issues."""
    cfg = config_store.get_section("baserow")
    api_url = cfg.get("api_url", "")
    api_token = cfg.get("api_token", "")
    if not api_url or not api_token:
        raise HTTPException(400, "Baserow not configured")

    from urllib.parse import urlparse
    parsed = urlparse(url)

    # Resolve relative URLs against the Baserow API URL
    if url.startswith("/"):
        url = api_url.rstrip("/") + url
        parsed = urlparse(url)

    # For any /media/ or /api/user-files/ path, always rewrite to use
    # the configured API URL.  Self-hosted Baserow in Docker frequently
    # returns internal hostnames (e.g. http://baserow:8080/media/...) that
    # are unreachable from the scraper container's perspective.
    is_media_path = (
        parsed.path.startswith("/media/")
        or parsed.path.startswith("/api/user-files/")
    )
    if is_media_path:
        url = api_url.rstrip("/") + parsed.path
    else:
        # Not a media path — verify it belongs to the configured Baserow
        api_parsed = urlparse(api_url)
        if parsed.netloc and parsed.netloc != api_parsed.netloc:
            raise HTTPException(400, "URL does not belong to configured Baserow instance")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        ) as client:
            # Try with auth header first, then without (Baserow media is often public)
            for headers in [
                {"Authorization": f"Token {api_token}"},
                {},
            ]:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code < 400:
                        content_type = resp.headers.get("content-type", "image/jpeg")
                        return StreamingResponse(
                            iter([resp.content]),
                            media_type=content_type,
                            headers={"Cache-Control": "public, max-age=86400"},
                        )
                except httpx.HTTPStatusError:
                    continue
            # Both attempts failed — raise error
            raise HTTPException(502, f"Baserow returned error for {parsed.path}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch image: {e}")


@router.get("/baserow/file/{file_path:path}")
async def baserow_file(file_path: str):
    """Serve a Baserow media file directly by its path.

    Usage: /api/baserow/file/user_files/abc123.jpg
    This constructs {api_url}/media/{file_path} and proxies it.
    """
    cfg = config_store.get_section("baserow")
    api_url = cfg.get("api_url", "")
    api_token = cfg.get("api_token", "")
    if not api_url or not api_token:
        raise HTTPException(400, "Baserow not configured")

    url = f"{api_url.rstrip('/')}/media/{file_path}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        ) as client:
            for headers in [
                {"Authorization": f"Token {api_token}"},
                {},
            ]:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code < 400:
                        content_type = resp.headers.get("content-type", "image/jpeg")
                        return StreamingResponse(
                            iter([resp.content]),
                            media_type=content_type,
                            headers={"Cache-Control": "public, max-age=86400"},
                        )
                except httpx.HTTPStatusError:
                    continue
            raise HTTPException(502, f"Baserow returned error for /media/{file_path}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch file: {e}")


@router.get("/baserow/rows")
async def list_baserow_rows(page: int = 1, size: int = 50, search: str = "",
                             order_by: str = ""):
    """Browse wallpapers stored in Baserow."""
    cfg = config_store.get_section("baserow")
    if not (cfg.get("api_url") and cfg.get("api_token") and cfg.get("table_id")):
        raise HTTPException(400, "Baserow not configured")
    client = BaserowClient(
        api_url=cfg.get("api_url", ""),
        api_token=cfg.get("api_token", ""),
        table_id=cfg.get("table_id", 0),
    )
    client.field_mapping = cfg.get("field_mapping", {})
    try:
        data = await client.list_rows(
            page=page, size=size, search=search, order_by=order_by,
        )
        data["field_mapping"] = client.field_mapping
        data["api_url"] = cfg.get("api_url", "")
        return data
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch rows: {e}")
    finally:
        await client.close()


@router.get("/baserow/rows/{row_id}")
async def get_baserow_row(row_id: int):
    """Get a single Baserow row by ID."""
    cfg = config_store.get_section("baserow")
    if not (cfg.get("api_url") and cfg.get("api_token") and cfg.get("table_id")):
        raise HTTPException(400, "Baserow not configured")
    client = BaserowClient(
        api_url=cfg.get("api_url", ""),
        api_token=cfg.get("api_token", ""),
        table_id=cfg.get("table_id", 0),
    )
    client.field_mapping = cfg.get("field_mapping", {})
    try:
        row = await client.get_row(row_id)
        if not row:
            raise HTTPException(404, "Row not found")
        row["field_mapping"] = client.field_mapping
        row["api_url"] = cfg.get("api_url", "")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch row: {e}")
    finally:
        await client.close()


@router.post("/baserow/field-mapping/reset")
async def reset_field_mapping():
    config_store.set("baserow", "field_mapping", dict(DEFAULT_FIELD_MAPPING))
    config_store.set("baserow", "field_mapping_verified", False)
    config_store.save()
    scraper_engine.update_baserow_config()
    return {"status": "reset", "field_mapping": DEFAULT_FIELD_MAPPING}


# === Settings ===

@router.get("/settings")
async def get_settings():
    return {
        "scraping": config_store.get_section("scraping"),
        "jpeg": config_store.get_section("jpeg"),
        "scheduler": config_store.get_section("scheduler"),
        "gallery": config_store.get_section("gallery"),
        "ai": config_store.get_section("ai"),
    }


@router.put("/settings")
async def update_settings(data: SettingsUpdate):
    if data.scraping:
        config_store.update_section("scraping", data.scraping)
    if data.jpeg:
        config_store.update_section("jpeg", data.jpeg)
    if data.scheduler:
        config_store.update_section("scheduler", data.scheduler)
    if data.gallery:
        config_store.update_section("gallery", data.gallery)
    if data.ai:
        config_store.update_section("ai", data.ai)
    config_store.save()
    return {"status": "saved"}


# === Stats ===

@router.get("/stats")
async def get_stats():
    summary = activity_store.get_summary()
    sources = source_manager.get_all_sources()
    queries = source_manager.get_all_queries()

    source_stats = []
    for s in sources:
        source_stats.append({
            "name": s.get("name", ""),
            "category": s.get("category", ""),
            "total_uploaded": s.get("total_uploaded", 0),
            "total_dupes": s.get("total_dupes", 0),
            "total_errors": s.get("total_errors", 0),
            "last_scraped": s.get("last_scraped"),
            "consecutive_failures": s.get("consecutive_failures", 0),
        })

    discovery_stats = {
        "total_queries": len(queries),
        "builtin_queries": len([q for q in queries if q.get("builtin")]),
        "user_queries": len([q for q in queries if not q.get("builtin")]),
        "total_sources_discovered": len([s for s in sources if s.get("category") == "discovered"]),
        "discovery_state": source_manager.discovery_state,
    }

    return {
        "summary": summary,
        "sources": source_stats,
        "discovery": discovery_stats,
        "total_sources": len(sources),
        "enabled_sources": len([s for s in sources if s.get("enabled")]),
    }


# === Logs ===

@router.get("/logs")
async def get_logs(lines: int = 200, level: str = ""):
    """Return recent log lines from the scraper log file."""
    log_file = data_path("logs") / "scraper.log"
    if not log_file.exists():
        return {"lines": [], "total": 0, "file": str(log_file)}
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        # Filter by level if specified
        if level:
            level_upper = level.upper()
            all_lines = [l for l in all_lines if f"| {level_upper}" in l]
        # Return last N lines
        recent = all_lines[-lines:]
        return {
            "lines": [l.rstrip("\n") for l in recent],
            "total": len(all_lines),
            "file": str(log_file),
        }
    except Exception as e:
        return {"lines": [f"Error reading logs: {e}"], "total": 0, "file": str(log_file)}


# === Favicon ===

FAVICON_DIR = data_path("config")


@router.post("/favicon")
async def upload_favicon(file: UploadFile = File(...)):
    """Upload a custom favicon (PNG, ICO, or SVG)."""
    if not file.content_type or not any(
        t in file.content_type for t in ["image/png", "image/x-icon", "image/svg", "image/vnd.microsoft.icon"]
    ):
        raise HTTPException(400, "Favicon must be PNG, ICO, or SVG")
    contents = await file.read()
    if len(contents) > 512_000:  # 500KB limit
        raise HTTPException(400, "Favicon too large (max 500KB)")
    FAVICON_DIR.mkdir(parents=True, exist_ok=True)
    ext = "ico" if "icon" in (file.content_type or "") else "png"
    if "svg" in (file.content_type or ""):
        ext = "svg"
    favicon_path = FAVICON_DIR / f"favicon.{ext}"
    # Remove old favicons
    for old in FAVICON_DIR.glob("favicon.*"):
        if old.suffix in (".png", ".ico", ".svg"):
            old.unlink(missing_ok=True)
    favicon_path.write_bytes(contents)
    return {"status": "saved", "path": str(favicon_path)}


@router.delete("/favicon")
async def delete_favicon():
    """Remove custom favicon and revert to default."""
    for old in FAVICON_DIR.glob("favicon.*"):
        if old.suffix in (".png", ".ico", ".svg"):
            old.unlink(missing_ok=True)
    return {"status": "deleted"}


@router.get("/favicon")
async def get_favicon_info():
    """Return favicon status."""
    for ext in ("png", "ico", "svg"):
        if (FAVICON_DIR / f"favicon.{ext}").is_file():
            return {"has_custom": True, "ext": ext}
    return {"has_custom": False}

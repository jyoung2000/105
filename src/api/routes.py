"""REST API routes for the wallpaper scraper."""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from fastapi.responses import StreamingResponse
import httpx
from src.api.models import (
    ScrapeRequest, SourceCreate, SourceUpdate,
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

    # Resolve relative URLs against the Baserow API URL
    if url.startswith("/"):
        url = api_url.rstrip("/") + url
    # Only proxy URLs from the configured Baserow host
    if not url.startswith(api_url.rstrip("/")):
        raise HTTPException(400, "URL does not belong to configured Baserow instance")

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"Authorization": f"Token {api_token}"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return StreamingResponse(
                iter([resp.content]),
                media_type=content_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Baserow returned {e.response.status_code}")
    except Exception as e:
        raise HTTPException(502, f"Failed to fetch image: {e}")


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

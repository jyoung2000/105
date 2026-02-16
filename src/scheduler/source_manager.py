"""Source and query management — CRUD for wallpaper sources and discovery queries."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from src.utils.paths import data_path
from src.utils.logging import setup_logging

logger = setup_logging("source_manager")

SOURCES_PATH = data_path("config", "sources.json")

SEED_SOURCES = [
    {"url": "https://wallhaven.cc/search?sorting=views&order=desc", "name": "Wallhaven - Top Views", "schedule_hours": 6},
    {"url": "https://wallhaven.cc/search?sorting=date_added&order=desc", "name": "Wallhaven - Latest", "schedule_hours": 4},
    {"url": "https://www.wallpaperflare.com/search?wallpaper=landscape", "name": "WallpaperFlare - Landscape", "schedule_hours": 12},
    {"url": "https://www.wallpaperflare.com/search?wallpaper=nature", "name": "WallpaperFlare - Nature", "schedule_hours": 12},
    {"url": "https://hdqwalls.com/latest-wallpapers", "name": "HDQWalls - Latest", "schedule_hours": 8},
    {"url": "https://www.pexels.com/search/wallpaper/", "name": "Pexels - Wallpaper", "schedule_hours": 12},
    {"url": "https://unsplash.com/s/photos/wallpaper", "name": "Unsplash - Wallpaper", "schedule_hours": 12},
]

DEFAULT_DISCOVERY_QUERIES = [
    {"query": "free 4k wallpaper download site", "builtin": True},
    {"query": "HD desktop wallpaper website", "builtin": True},
    {"query": "best wallpaper sites 2024 2025", "builtin": True},
    {"query": "free phone wallpaper download", "builtin": True},
    {"query": "nature landscape wallpaper site", "builtin": True},
    {"query": "anime wallpaper download site", "builtin": True},
    {"query": "abstract wallpaper HD free", "builtin": True},
    {"query": "minimalist wallpaper site", "builtin": True},
    {"query": "dark wallpaper AMOLED site", "builtin": True},
    {"query": "ultrawide wallpaper 3440x1440", "builtin": True},
    {"query": "wallpaper download no watermark", "builtin": True},
    {"query": "gaming wallpaper 4k site", "builtin": True},
    {"query": "aesthetic wallpaper HD download", "builtin": True},
    {"query": "space wallpaper 4k free", "builtin": True},
    {"query": "car wallpaper HD download site", "builtin": True},
]


class WallpaperSource(BaseModel):
    id: str
    url: str
    name: str
    domain: str
    category: str = "curated"  # curated | discovered | user
    enabled: bool = True
    schedule_hours: int = 12
    last_scraped: Optional[str] = None
    last_scrape_count: int = 0
    total_scraped: int = 0
    total_uploaded: int = 0
    total_dupes: int = 0
    total_errors: int = 0
    consecutive_failures: int = 0
    validation_score: float = 0.0
    discovered_at: str = ""
    discovered_by_query: str = ""
    max_pages: int = 10
    notes: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < 5


class DiscoveryQuery(BaseModel):
    id: str
    query: str
    enabled: bool = True
    builtin: bool = False
    times_used: int = 0
    sources_found: int = 0
    last_used: Optional[str] = None
    added_at: str = ""


class SourceManager:
    """Manages wallpaper sources and discovery queries."""

    def __init__(self):
        self._sources: list[dict] = []
        self._queries: list[dict] = []
        self._discovery: dict = {
            "enabled": True,
            "interval_hours": 24,
            "last_discovery_run": None,
            "known_domains": [],
            "query_index": 0,
        }
        self._loaded = False

    def load(self):
        """Load sources and queries from disk."""
        try:
            if SOURCES_PATH.exists():
                with open(SOURCES_PATH, "r") as f:
                    data = json.load(f)
                self._sources = data.get("sources", [])
                self._queries = data.get("queries", [])
                self._discovery = data.get("discovery", self._discovery)
            self._loaded = True
            logger.info(f"Loaded {len(self._sources)} sources, {len(self._queries)} queries")
        except Exception as e:
            logger.warning(f"Failed to load sources: {e}")
            self._loaded = True

    def save(self):
        """Save sources and queries to disk."""
        try:
            SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "sources": self._sources,
                "queries": self._queries,
                "discovery": self._discovery,
            }
            with open(SOURCES_PATH, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save sources: {e}")

    def initialize_seeds(self):
        """Add seed sources and default queries on first launch."""
        if not self._loaded:
            self.load()

        # Only seed if no sources exist
        if not self._sources:
            from urllib.parse import urlparse
            for seed in SEED_SOURCES:
                domain = urlparse(seed["url"]).netloc
                source = WallpaperSource(
                    id=uuid.uuid4().hex[:12],
                    url=seed["url"],
                    name=seed["name"],
                    domain=domain,
                    category="curated",
                    schedule_hours=seed["schedule_hours"],
                    discovered_at=datetime.now().isoformat(),
                )
                self._sources.append(source.model_dump())
                if domain not in self._discovery["known_domains"]:
                    self._discovery["known_domains"].append(domain)
            logger.info(f"Seeded {len(SEED_SOURCES)} sources")

        # Only seed queries if none exist
        if not self._queries:
            for dq in DEFAULT_DISCOVERY_QUERIES:
                query = DiscoveryQuery(
                    id=f"b_{uuid.uuid4().hex[:8]}",
                    query=dq["query"],
                    enabled=True,
                    builtin=True,
                    added_at=datetime.now().isoformat(),
                )
                self._queries.append(query.model_dump())
            logger.info(f"Seeded {len(DEFAULT_DISCOVERY_QUERIES)} discovery queries")

        self.save()

    # === Source CRUD ===

    def get_all_sources(self) -> list[dict]:
        if not self._loaded:
            self.load()
        return list(self._sources)

    def get_enabled_sources(self) -> list[dict]:
        if not self._loaded:
            self.load()
        return [s for s in self._sources if s.get("enabled", True)]

    def get_source(self, source_id: str) -> Optional[dict]:
        if not self._loaded:
            self.load()
        for s in self._sources:
            if s["id"] == source_id:
                return s
        return None

    def add_source(self, url: str, name: str = "", category: str = "user",
                   schedule_hours: int = 12, discovered_by_query: str = "") -> dict:
        """Add a new source."""
        if not self._loaded:
            self.load()
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        source = WallpaperSource(
            id=uuid.uuid4().hex[:12],
            url=url,
            name=name or domain,
            domain=domain,
            category=category,
            schedule_hours=schedule_hours,
            discovered_at=datetime.now().isoformat(),
            discovered_by_query=discovered_by_query,
        )
        d = source.model_dump()
        self._sources.append(d)
        if domain not in self._discovery["known_domains"]:
            self._discovery["known_domains"].append(domain)
        self.save()
        return d

    def update_source(self, source_id: str, **kwargs) -> Optional[dict]:
        """Update a source's fields."""
        if not self._loaded:
            self.load()
        for i, s in enumerate(self._sources):
            if s["id"] == source_id:
                for k, v in kwargs.items():
                    if k in s:
                        s[k] = v
                self.save()
                return s
        return None

    def remove_source(self, source_id: str) -> bool:
        if not self._loaded:
            self.load()
        initial = len(self._sources)
        self._sources = [s for s in self._sources if s["id"] != source_id]
        if len(self._sources) < initial:
            self.save()
            return True
        return False

    def toggle_source(self, source_id: str) -> Optional[dict]:
        for s in self._sources:
            if s["id"] == source_id:
                s["enabled"] = not s.get("enabled", True)
                self.save()
                return s
        return None

    def domain_exists(self, domain: str) -> bool:
        if not self._loaded:
            self.load()
        return domain in self._discovery.get("known_domains", [])

    def record_scrape(self, source_id: str, uploaded: int, dupes: int, errors: int):
        """Record scrape results for a source."""
        for s in self._sources:
            if s["id"] == source_id:
                s["last_scraped"] = datetime.now().isoformat()
                s["last_scrape_count"] = uploaded
                s["total_scraped"] = s.get("total_scraped", 0) + uploaded + dupes
                s["total_uploaded"] = s.get("total_uploaded", 0) + uploaded
                s["total_dupes"] = s.get("total_dupes", 0) + dupes
                s["total_errors"] = s.get("total_errors", 0) + errors
                if errors > 0 and uploaded == 0:
                    s["consecutive_failures"] = s.get("consecutive_failures", 0) + 1
                else:
                    s["consecutive_failures"] = 0
                self.save()
                return

    # === Query CRUD ===

    def get_all_queries(self) -> list[dict]:
        if not self._loaded:
            self.load()
        return list(self._queries)

    def add_query(self, query_text: str) -> dict:
        """Add a user query."""
        if not self._loaded:
            self.load()
        query = DiscoveryQuery(
            id=f"u_{uuid.uuid4().hex[:8]}",
            query=query_text,
            enabled=True,
            builtin=False,
            added_at=datetime.now().isoformat(),
        )
        d = query.model_dump()
        self._queries.append(d)
        self.save()
        return d

    def remove_query(self, query_id: str) -> bool:
        """Remove a query. Fails for builtin queries."""
        if not self._loaded:
            self.load()
        for q in self._queries:
            if q["id"] == query_id:
                if q.get("builtin", False):
                    return False
                self._queries = [q2 for q2 in self._queries if q2["id"] != query_id]
                self.save()
                return True
        return False

    def update_query(self, query_id: str, **kwargs) -> Optional[dict]:
        """Update a query. Builtin queries can only toggle enabled."""
        if not self._loaded:
            self.load()
        for q in self._queries:
            if q["id"] == query_id:
                is_builtin = q.get("builtin", False)
                for k, v in kwargs.items():
                    if is_builtin and k not in ("enabled",):
                        continue
                    if k in q:
                        q[k] = v
                self.save()
                return q
        return None

    def get_next_query(self) -> Optional[dict]:
        """Get next enabled query using rotation."""
        if not self._loaded:
            self.load()
        enabled = [q for q in self._queries if q.get("enabled", True)]
        if not enabled:
            return None
        idx = self._discovery.get("query_index", 0) % len(enabled)
        query = enabled[idx]
        self._discovery["query_index"] = (idx + 1) % len(enabled)
        self.save()
        return query

    def record_query_use(self, query_id: str, sources_found: int = 0):
        """Record that a query was used in discovery."""
        for q in self._queries:
            if q["id"] == query_id:
                q["times_used"] = q.get("times_used", 0) + 1
                q["sources_found"] = q.get("sources_found", 0) + sources_found
                q["last_used"] = datetime.now().isoformat()
                self.save()
                return

    # === Discovery state ===

    @property
    def discovery_state(self) -> dict:
        if not self._loaded:
            self.load()
        return dict(self._discovery)

    def update_discovery_state(self, **kwargs):
        for k, v in kwargs.items():
            if k in self._discovery:
                self._discovery[k] = v
        self.save()


# Singleton
source_manager = SourceManager()

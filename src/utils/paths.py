"""Central data path resolver with fallback for permission-restricted mounts."""
import os
from pathlib import Path

# Primary data directory (volume mount)
_PRIMARY = "/app/data"
# Fallback (always writable inside container)
_FALLBACK = "/tmp/scraper-data"

_resolved_base: str = ""


def _check_writable(path: str) -> bool:
    """Check if a directory is writable."""
    try:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        test = p / ".write_test"
        test.write_text("ok")
        test.unlink()
        return True
    except Exception:
        return False


def get_data_dir() -> Path:
    """Get the base data directory, using fallback if primary isn't writable."""
    global _resolved_base
    if _resolved_base:
        return Path(_resolved_base)

    if _check_writable(_PRIMARY):
        _resolved_base = _PRIMARY
    else:
        _resolved_base = _FALLBACK
        # Ensure fallback subdirs exist
        for sub in ["logs", "config", "temp", "wallpapers", "thumbnails"]:
            Path(_FALLBACK, sub).mkdir(parents=True, exist_ok=True)

    return Path(_resolved_base)


def data_path(*parts: str) -> Path:
    """Get a path under the data directory. E.g., data_path('config', 'config.json')."""
    base = get_data_dir()
    result = base.joinpath(*parts)
    # Ensure parent directory exists
    try:
        result.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return result

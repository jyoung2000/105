"""Aspect ratio utilities for wallpaper classification."""
from math import gcd


def calculate_aspect_ratio(width: int, height: int) -> str:
    """Return simplified aspect ratio string like '16:9'."""
    if width <= 0 or height <= 0:
        return "unknown"
    divisor = gcd(width, height)
    w = width // divisor
    h = height // divisor
    # Simplify common ratios
    common = {
        (16, 9): "16:9",
        (16, 10): "16:10",
        (4, 3): "4:3",
        (21, 9): "21:9",
        (32, 9): "32:9",
        (3, 2): "3:2",
        (5, 4): "5:4",
        (9, 16): "9:16",
        (9, 19): "9:19",
        (9, 20): "9:20",
        (1, 1): "1:1",
    }
    return common.get((w, h), f"{w}:{h}")


def is_mobile(width: int, height: int) -> bool:
    """Return True if dimensions suggest a mobile wallpaper (portrait, height > width)."""
    return height > width


def classify_resolution(width: int, height: int) -> str:
    """Classify resolution into human-readable category."""
    pixels = width * height
    if pixels >= 3840 * 2160:
        return "4K+"
    elif pixels >= 2560 * 1440:
        return "1440p"
    elif pixels >= 1920 * 1080:
        return "1080p"
    elif pixels >= 1280 * 720:
        return "720p"
    else:
        return "SD"

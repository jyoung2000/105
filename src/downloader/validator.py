"""Image validation — checks dimensions, aspect ratio, and file integrity."""
from pathlib import Path
from typing import List, Tuple
from PIL import Image
from src.utils.aspect_ratio import calculate_aspect_ratio
from src.utils.logging import setup_logging

logger = setup_logging("validator")

MIN_WIDTH = 800
MIN_HEIGHT = 600


class ImageValidator:
    """Validate downloaded images meet wallpaper criteria."""

    def __init__(self, min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT,
                 allowed_aspects: List[str] = None, allow_mobile: bool = True):
        self.min_width = min_width
        self.min_height = min_height
        self.allowed_aspects = allowed_aspects or []
        self.allow_mobile = allow_mobile

    def validate(self, file_path: Path) -> Tuple[bool, str]:
        """Validate an image file. Returns (is_valid, reason)."""
        try:
            if not file_path.exists():
                return False, "File does not exist"

            file_size = file_path.stat().st_size
            if file_size < 5000:
                return False, f"File too small ({file_size} bytes)"
            if file_size > 50 * 1024 * 1024:
                return False, f"File too large ({file_size} bytes)"

            img = Image.open(file_path)
            img.verify()

            # Reopen after verify
            img = Image.open(file_path)
            width, height = img.size

            if width < self.min_width or height < self.min_height:
                return False, f"Too small ({width}x{height})"

            # Mobile/portrait check
            if not self.allow_mobile and height > width:
                return False, f"Mobile/portrait not allowed ({width}x{height})"

            # Aspect ratio filter
            if self.allowed_aspects:
                aspect = calculate_aspect_ratio(width, height)
                if aspect != "unknown" and aspect not in self.allowed_aspects:
                    return False, f"Aspect ratio {aspect} not in allowed list"

            return True, "OK"

        except Exception as e:
            return False, f"Invalid image: {e}"

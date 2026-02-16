"""Image validation — checks dimensions and file integrity."""
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image
from src.utils.logging import setup_logging

logger = setup_logging("validator")

MIN_WIDTH = 800
MIN_HEIGHT = 600


class ImageValidator:
    """Validate downloaded images meet wallpaper criteria."""

    def __init__(self, min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT):
        self.min_width = min_width
        self.min_height = min_height

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

            if width < self.min_width and height < self.min_height:
                return False, f"Too small ({width}x{height})"

            return True, "OK"

        except Exception as e:
            return False, f"Invalid image: {e}"

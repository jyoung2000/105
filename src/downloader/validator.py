"""Image validation — checks dimensions, aspect ratio, and file integrity."""
import numpy as np
from pathlib import Path
from typing import List, Tuple
from PIL import Image, ImageFilter
from src.utils.aspect_ratio import calculate_aspect_ratio
from src.utils.logging import setup_logging

logger = setup_logging("validator")

MIN_WIDTH = 800
MIN_HEIGHT = 600


class ImageValidator:
    """Validate downloaded images meet wallpaper criteria."""

    def __init__(self, min_width: int = MIN_WIDTH, min_height: int = MIN_HEIGHT,
                 allowed_aspects: List[str] = None, allow_mobile: bool = True,
                 watermark_detection: bool = True):
        self.min_width = min_width
        self.min_height = min_height
        self.allowed_aspects = allowed_aspects or []
        self.allow_mobile = allow_mobile
        self.watermark_detection = watermark_detection

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

            # Watermark detection (can be disabled via settings)
            if self.watermark_detection:
                has_watermark, wm_reason = self._detect_watermark(img)
                if has_watermark:
                    return False, f"Watermark detected: {wm_reason}"

            return True, "OK"

        except Exception as e:
            return False, f"Invalid image: {e}"

    def _detect_watermark(self, img: Image.Image) -> Tuple[bool, str]:
        """Detect blatant stock-photo watermarks using pixel analysis.

        Only flags images with very obvious, large watermarks that clearly
        degrade the image (e.g. Shutterstock, iStock, Getty tiled overlays).
        Tuned for high precision — prefers letting a subtle watermark through
        over rejecting a clean wallpaper.

        Checks for:
        1. Semi-transparent overlay covering the center (shutterstock-style)
        2. Repeating tiled pattern across the image (depositphotos-style)
        Both checks must exceed strict thresholds to trigger.
        """
        try:
            # Work on a smaller version for speed
            w, h = img.size
            scale = min(1.0, 600 / max(w, h))
            if scale < 1.0:
                small = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            else:
                small = img.copy()

            if small.mode != "RGB":
                small = small.convert("RGB")

            arr = np.array(small, dtype=np.float32)
            gray = np.mean(arr, axis=2)

            # Extract center region (watermarks are typically centered)
            cy, cx = gray.shape[0] // 2, gray.shape[1] // 2
            crop_h, crop_w = min(200, gray.shape[0] // 2), min(200, gray.shape[1] // 2)
            center = gray[cy - crop_h:cy + crop_h, cx - crop_w:cx + crop_w]

            if center.size == 0:
                return False, ""

            # --- Check 1: Semi-transparent overlay detection ---
            # Blatant stock watermarks apply a large white/grey overlay that
            # noticeably flattens the center contrast.  Compare center vs
            # edge variance.  Only trigger on extreme differences — natural
            # images (fog, sky, snow) can have low center variance too, so
            # we require a very low ratio AND high border variance AND a
            # large absolute difference to avoid false positives.
            edge_band = 50
            if gray.shape[0] > edge_band * 4 and gray.shape[1] > edge_band * 4:
                border_top = gray[:edge_band, :]
                border_bottom = gray[-edge_band:, :]
                border_left = gray[:, :edge_band]
                border_right = gray[:, -edge_band:]

                border_var = np.mean([
                    np.var(border_top), np.var(border_bottom),
                    np.var(border_left), np.var(border_right),
                ])
                center_var = np.var(center)

                if border_var > 0 and center_var > 0:
                    ratio = center_var / border_var
                    # Only flag truly extreme cases: ratio < 0.12 (was 0.25)
                    # with high border variance (> 800, was 500) and a large
                    # absolute variance drop.  This combination is rare in
                    # natural photos but common in watermarked stock images.
                    if (ratio < 0.12
                            and border_var > 800
                            and (border_var - center_var) > 600):
                        logger.debug(
                            f"Watermark detected: center/border variance "
                            f"ratio={ratio:.2f}, border_var={border_var:.0f}, "
                            f"center_var={center_var:.0f}"
                        )
                        return True, "semi-transparent overlay (low center contrast)"

            # --- Check 2: Repeating tiled pattern via autocorrelation ---
            # Tiled watermarks (e.g. "depositphotos" repeated 20+ times)
            # produce strong periodic correlations.  We sample MULTIPLE
            # horizontal stripes and require the pattern to appear
            # consistently across them — this eliminates false positives
            # from natural repeating textures (waves, fences, blinds) which
            # tend to be localized or axis-aligned rather than tiled.
            if center.shape[0] >= 100 and center.shape[1] >= 100:
                stripe_rows = [
                    center.shape[0] // 4,
                    center.shape[0] // 2,
                    3 * center.shape[0] // 4,
                ]
                stripes_with_pattern = 0
                for row in stripe_rows:
                    stripe = center[row, :]
                    stripe = stripe - np.mean(stripe)
                    norm = np.sum(stripe ** 2)
                    if norm == 0:
                        continue
                    high_corr = 0
                    for lag in range(30, min(150, len(stripe) // 2), 10):
                        corr = np.sum(stripe[:-lag] * stripe[lag:]) / norm
                        if corr > 0.55:  # was 0.4 — require stronger correlation
                            high_corr += 1
                    if high_corr >= 4:  # was 3 — require more correlated lags
                        stripes_with_pattern += 1

                # Only flag if the repeating pattern is consistent across
                # at least 2 out of 3 sampled stripes (tiled watermarks
                # cover the whole center, not just one stripe)
                if stripes_with_pattern >= 2:
                    logger.debug(
                        f"Watermark detected: repeating tiled pattern "
                        f"({stripes_with_pattern}/3 stripes matched)"
                    )
                    return True, "repeating tiled watermark pattern"

        except Exception as e:
            logger.debug(f"Watermark detection error: {e}")

        return False, ""

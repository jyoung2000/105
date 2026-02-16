"""AI captioner using BLIP-base for title, alt text, and tag generation."""
import asyncio
from typing import Optional, Tuple
from pathlib import Path
from PIL import Image
from src.utils.logging import setup_logging

logger = setup_logging("captioner")


class AICaptioner:
    """Generate captions, alt text, and tags using BLIP-base model."""

    def __init__(self):
        self._model = None
        self._processor = None
        self._device = "cpu"
        self._initialized = False

    async def initialize(self) -> bool:
        """Load BLIP model. Returns False on failure (non-fatal)."""
        try:
            return await asyncio.get_event_loop().run_in_executor(None, self._load_model)
        except Exception as e:
            logger.warning(f"AI model initialization failed: {e}")
            return False

    def _load_model(self) -> bool:
        """Load model synchronously."""
        try:
            import torch
            from transformers import BlipProcessor, BlipForConditionalGeneration

            logger.info("Loading BLIP-base model...")
            self._processor = BlipProcessor.from_pretrained(
                "Salesforce/blip-image-captioning-base"
            )
            self._model = BlipForConditionalGeneration.from_pretrained(
                "Salesforce/blip-image-captioning-base"
            ).to(self._device)
            self._model.eval()
            self._initialized = True
            logger.info("BLIP-base model loaded successfully")
            return True
        except Exception as e:
            logger.warning(f"Failed to load BLIP model: {e}")
            return False

    async def caption(self, image_path: Path) -> Tuple[str, str, str]:
        """Generate title, alt_text, tags for an image.
        Returns (title, alt_text, tags) or fallback values on failure."""
        if not self._initialized:
            return self._fallback_caption(image_path)

        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._generate_caption, image_path
            )
        except Exception as e:
            logger.warning(f"Caption generation failed: {e}")
            return self._fallback_caption(image_path)

    def _generate_caption(self, image_path: Path) -> Tuple[str, str, str]:
        """Generate captions synchronously."""
        import torch

        img = Image.open(image_path).convert("RGB")
        img_resized = img.resize((384, 384), Image.LANCZOS)

        # Generate title (short caption)
        with torch.no_grad():
            inputs = self._processor(img_resized, "a wallpaper of", return_tensors="pt").to(self._device)
            title_ids = self._model.generate(
                **inputs,
                max_new_tokens=20,
                num_beams=3,
                early_stopping=True,
            )
            title = self._processor.decode(title_ids[0], skip_special_tokens=True).strip()

        # Generate alt text (longer description)
        with torch.no_grad():
            inputs = self._processor(img_resized, return_tensors="pt").to(self._device)
            alt_ids = self._model.generate(
                **inputs,
                max_new_tokens=50,
                num_beams=5,
                early_stopping=True,
            )
            alt_text = self._processor.decode(alt_ids[0], skip_special_tokens=True).strip()

        # Generate tags from multiple prompts
        tag_prompts = [
            "this image contains",
            "the scene shows",
            "the colors are",
        ]
        all_tags = set()
        for prompt in tag_prompts:
            with torch.no_grad():
                inputs = self._processor(img_resized, prompt, return_tensors="pt").to(self._device)
                tag_ids = self._model.generate(
                    **inputs,
                    max_new_tokens=30,
                    num_beams=3,
                    early_stopping=True,
                )
                result = self._processor.decode(tag_ids[0], skip_special_tokens=True).strip()
                words = result.lower().split()
                for word in words:
                    clean = word.strip(".,!?;:'\"()[]")
                    if len(clean) > 2 and clean not in {"the", "and", "this", "that", "with", "from", "are", "was", "for", "image", "contains", "scene", "shows", "colors"}:
                        all_tags.add(clean)

        # Add color-based tags
        color_tags = self._extract_color_tags(img)
        all_tags.update(color_tags)

        tags_str = ", ".join(sorted(all_tags)[:20])

        # Clean up title
        title = self._clean_title(title)

        return title, alt_text, tags_str

    def _clean_title(self, title: str) -> str:
        """Clean and format the title."""
        # Remove common prefixes
        prefixes = ["a wallpaper of ", "a photo of ", "an image of ", "a picture of "]
        lower = title.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                title = title[len(prefix):]
                break
        # Capitalize first letter
        if title:
            title = title[0].upper() + title[1:]
        # Limit length
        words = title.split()
        if len(words) > 8:
            title = " ".join(words[:8])
        return title

    def _extract_color_tags(self, img: Image.Image) -> set:
        """Extract dominant color names from image."""
        try:
            small = img.resize((50, 50), Image.LANCZOS)
            pixels = list(small.getdata())
            color_counts = {}
            for r, g, b in pixels:
                name = self._classify_color(r, g, b)
                color_counts[name] = color_counts.get(name, 0) + 1

            total = len(pixels)
            tags = set()
            for color, count in sorted(color_counts.items(), key=lambda x: -x[1]):
                if count / total > 0.1:
                    tags.add(color)
                if len(tags) >= 3:
                    break
            return tags
        except Exception:
            return set()

    def _classify_color(self, r: int, g: int, b: int) -> str:
        """Classify RGB into color name."""
        if r > 200 and g > 200 and b > 200:
            return "white"
        if r < 50 and g < 50 and b < 50:
            return "black"
        if r > 150 and g < 100 and b < 100:
            return "red"
        if r < 100 and g > 150 and b < 100:
            return "green"
        if r < 100 and g < 100 and b > 150:
            return "blue"
        if r > 200 and g > 200 and b < 100:
            return "yellow"
        if r > 200 and g > 100 and b < 50:
            return "orange"
        if r > 100 and g < 80 and b > 100:
            return "purple"
        if r > 150 and g > 150 and b > 150:
            return "gray"
        if r < 80 and g > 100 and b > 100:
            return "teal"
        return "mixed"

    def _fallback_caption(self, image_path: Path) -> Tuple[str, str, str]:
        """Generate basic fallback captions from image properties."""
        try:
            img = Image.open(image_path).convert("RGB")
            color_tags = self._extract_color_tags(img)
            w, h = img.size
            orientation = "landscape" if w > h else "portrait" if h > w else "square"
            tags = color_tags | {orientation, "wallpaper"}
            return (
                f"{orientation.capitalize()} Wallpaper",
                f"A {orientation} wallpaper image at {w}x{h} resolution",
                ", ".join(sorted(tags)),
            )
        except Exception:
            return ("Wallpaper", "A wallpaper image", "wallpaper")

    @property
    def is_available(self) -> bool:
        return self._initialized

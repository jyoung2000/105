"""AI captioner using BLIP-base for title, alt text, and tag generation.

Produces natural, human-like captions — the kind a person would write when
posting a wallpaper to Instagram or Tumblr. No site names, no robotic
descriptions, no "wallpaper of" prefixes.
"""
import asyncio
import random
import re
from typing import Optional, Tuple
from pathlib import Path
from PIL import Image
from src.utils.logging import setup_logging

logger = setup_logging("captioner")

# Words to strip from titles/alt — site names, generic labels, junk
STRIP_WORDS = re.compile(
    r"\b(wallpaper[s]?|background[s]?|desktop|hd|4k|uhd|1080p|2k|"
    r"free download|download|stock photo|royalty.?free|"
    r"image|photo|picture|pic|img|"
    r"wallhaven|unsplash|pexels|pixabay|wallpaperscraft|wallpaperflare|"
    r"wallpaperaccess|wallpaperbat|wallpapercave|wallpaperbetter|"
    r"hdwallpapers|getwallpapers|peakpx|setaswall|pixel4k|"
    r"4kwallpapers|uhdpaper|goodfon|fonwall|rawpixel|freepik)\b",
    re.I,
)

# Patterns that indicate junk metadata (dimensions, IDs, filenames)
JUNK_PATTERN = re.compile(
    r"^\d+x\d+$|"              # "1920x1080"
    r"^[\w-]{20,}$|"           # Long hash/ID strings
    r"^\d+$|"                  # Pure numbers
    r"^IMG_|^DSC_|^DSCN|"     # Camera filenames
    r"^photo-\d|"              # stock photo IDs
    r"\.jpe?g$|\.png$|\.webp$", # File extensions
    re.I,
)


class AICaptioner:
    """Generate captions, alt text, and tags using BLIP-base model.

    Produces natural, social-media-style text — like an Instagram or
    Tumblr user would write for a beautiful image.
    """

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

        # Generate a natural description (no "wallpaper" prompting)
        with torch.no_grad():
            inputs = self._processor(img_resized, return_tensors="pt").to(self._device)
            desc_ids = self._model.generate(
                **inputs,
                max_new_tokens=40,
                num_beams=5,
                early_stopping=True,
            )
            raw_desc = self._processor.decode(desc_ids[0], skip_special_tokens=True).strip()

        # Generate a shorter version for title
        with torch.no_grad():
            inputs = self._processor(img_resized, return_tensors="pt").to(self._device)
            short_ids = self._model.generate(
                **inputs,
                max_new_tokens=15,
                num_beams=3,
                early_stopping=True,
            )
            raw_short = self._processor.decode(short_ids[0], skip_special_tokens=True).strip()

        # Generate content-focused tags
        tag_prompts = [
            "this is a photo of",
            "the scene shows",
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
                skip = {"the", "and", "this", "that", "with", "from", "are", "was",
                        "for", "has", "its", "is", "of", "in", "on", "at", "to",
                        "image", "contains", "scene", "shows", "photo", "picture"}
                for word in words:
                    clean = word.strip(".,!?;:'\"()[]")
                    if len(clean) > 2 and clean not in skip:
                        all_tags.add(clean)

        # Add color tags
        color_tags = self._extract_color_tags(img)
        all_tags.update(color_tags)

        # Add mood/vibe tags based on colors
        mood_tags = self._mood_from_colors(color_tags)
        all_tags.update(mood_tags)

        tags_str = ", ".join(sorted(all_tags)[:15])

        # Clean and humanize the title and alt text
        title = self._humanize_title(raw_short)
        alt_text = self._humanize_alt(raw_desc)

        return title, alt_text, tags_str

    def _humanize_title(self, raw: str) -> str:
        """Turn a model caption into a natural, human-like title.

        Think Instagram caption / Tumblr post title — short, evocative,
        lowercase-friendly, no junk words.
        """
        # Strip generic prefixes
        prefixes = [
            "a photo of ", "a photograph of ", "an image of ", "a picture of ",
            "a painting of ", "a view of ", "a close up of ", "a closeup of ",
            "a wallpaper of ", "a stock photo of ", "a screenshot of ",
            "there is ", "this is ",
        ]
        text = raw.strip()
        lower = text.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                text = text[len(prefix):]
                lower = text.lower()
                break

        # Remove site names and junk words
        text = STRIP_WORDS.sub("", text).strip()

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^[,.\-–—:;]+\s*", "", text).strip()

        if not text:
            return ""

        # Title case, but keep it natural
        text = text[0].upper() + text[1:]

        # Keep it concise (6-8 words max)
        words = text.split()
        if len(words) > 8:
            text = " ".join(words[:8])

        # Remove trailing articles/prepositions left from truncation
        text = re.sub(r"\s+(a|an|the|in|on|at|of|with|and|or|for|to)\s*$", "", text, flags=re.I)

        return text.strip()

    def _humanize_alt(self, raw: str) -> str:
        """Make alt text descriptive but natural, like a person would write it."""
        text = raw.strip()

        # Strip generic prefixes
        prefixes = [
            "a photo of ", "a photograph of ", "an image of ", "a picture of ",
            "a wallpaper of ", "a stock photo of ",
        ]
        lower = text.lower()
        for prefix in prefixes:
            if lower.startswith(prefix):
                text = text[len(prefix):]
                break

        # Remove site names
        text = STRIP_WORDS.sub("", text).strip()
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(r"^[,.\-–—:;]+\s*", "", text).strip()

        if not text:
            return ""

        # Capitalize naturally
        text = text[0].upper() + text[1:]

        # Cap at ~15 words for concise alt text
        words = text.split()
        if len(words) > 15:
            text = " ".join(words[:15])

        return text.strip()

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

    def _mood_from_colors(self, color_tags: set) -> set:
        """Generate aesthetic/mood tags from dominant colors."""
        mood = set()
        if "black" in color_tags or "gray" in color_tags:
            mood.add("moody")
        if "blue" in color_tags and "white" in color_tags:
            mood.add("serene")
        if "green" in color_tags:
            mood.add("nature")
        if "orange" in color_tags or "red" in color_tags:
            mood.add("warm")
        if "purple" in color_tags or "teal" in color_tags:
            mood.add("dreamy")
        if "white" in color_tags and len(color_tags) <= 2:
            mood.add("minimal")
        return mood

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
            mood_tags = self._mood_from_colors(color_tags)
            w, h = img.size

            all_tags = color_tags | mood_tags
            orientation = "landscape" if w > h else "portrait" if h > w else "square"

            # Pick a natural-sounding fallback title based on colors/mood
            if "nature" in mood_tags:
                title = random.choice(["Into the wild", "Nature's palette", "Green vibes"])
            elif "moody" in mood_tags:
                title = random.choice(["Dark aesthetics", "After dark", "Midnight tones"])
            elif "serene" in mood_tags:
                title = random.choice(["Clear skies", "Blue hour", "Calm waters"])
            elif "warm" in mood_tags:
                title = random.choice(["Golden hour", "Warm light", "Sunset vibes"])
            elif "dreamy" in mood_tags:
                title = random.choice(["Dreamscape", "Fading light", "Soft tones"])
            elif "minimal" in mood_tags:
                title = random.choice(["Less is more", "Clean lines", "Simplicity"])
            else:
                title = random.choice([
                    "Untitled",
                    f"{orientation.capitalize()} view",
                    "Found this gem",
                ])

            alt_text = f"{orientation.capitalize()} scene with {' and '.join(sorted(color_tags)[:2]) or 'mixed'} tones"

            return title, alt_text, ", ".join(sorted(all_tags))
        except Exception:
            return ("Untitled", "A beautiful scene", "")

    @property
    def is_available(self) -> bool:
        return self._initialized

"""Pillow-based image preprocessing for rasterized PDF pages.

Optimizes page images BEFORE sending to the vision LLM to improve
extraction accuracy and reduce token costs.
"""
import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageStat

from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PreprocessingResult:
    """Result of image preprocessing."""
    base64_jpeg: str
    was_enhanced: bool
    enhancement_applied: list[str]
    original_size: tuple[int, int]
    final_size: tuple[int, int]


class ImagePreprocessor:
    """Preprocess rasterized page images for optimal LLM extraction."""

    # Maximum dimension before downscaling.
    MAX_DIMENSION = 2048
    LOW_CONTRAST_THRESHOLD = 40.0
    BLUR_THRESHOLD = 15.0

    def preprocess(self, base64_jpeg: str) -> PreprocessingResult:
        """Preprocess a base64-encoded JPEG image."""
        enhancements: list[str] = []

        img_bytes = base64.b64decode(base64_jpeg)
        img = Image.open(io.BytesIO(img_bytes))
        original_size = img.size

        if img.mode != "RGB":
            img = img.convert("RGB")
            enhancements.append("rgb_conversion")

        # --- NEW: Margin Cropping ---
        # Cropping white margins reduces tokens by ~15% for vector PDFs
        cropped_img = self._crop_white_margins(img)
        if cropped_img.size != img.size:
            img = cropped_img
            enhancements.append("margin_crop")

        needs_sharpening = self._is_blurry(img)
        needs_contrast = self._is_low_contrast(img)

        if needs_sharpening:
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.8)
            enhancements.append("sharpening")

        if needs_contrast:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.4)
            enhancements.append("contrast_boost")

        if max(img.size) > self.MAX_DIMENSION:
            img = self._resize_maintaining_aspect(img, self.MAX_DIMENSION)
            enhancements.append(f"resize_to_{img.size[0]}x{img.size[1]}")

        output_b64 = self._to_base64_jpeg(img, quality=85)
        was_enhanced = len(enhancements) > 0

        if was_enhanced:
            logger.debug(
                "image_preprocessed",
                enhancements=enhancements,
                original=f"{original_size[0]}x{original_size[1]}",
                final=f"{img.size[0]}x{img.size[1]}",
            )

        return PreprocessingResult(
            base64_jpeg=output_b64,
            was_enhanced=was_enhanced,
            enhancement_applied=enhancements,
            original_size=original_size,
            final_size=img.size,
        )

    def _crop_white_margins(self, img: Image.Image, padding: int = 10) -> Image.Image:
        """Crop pure white margins from the image to save tokens."""
        # Create a pure white image of the same size
        bg = Image.new(img.mode, img.size, (255, 255, 255))
        # Find difference between image and pure white
        diff = ImageChops.difference(img, bg)
        # Get the bounding box of non-white pixels
        bbox = diff.getbbox()
        
        if bbox:
            # Add padding back so text isn't flush against the edge
            left = max(0, bbox[0] - padding)
            upper = max(0, bbox[1] - padding)
            right = min(img.size[0], bbox[2] + padding)
            lower = min(img.size[1], bbox[3] + padding)
            return img.crop((left, upper, right, lower))
        
        # If image is entirely white, return original
        return img

    def _is_blurry(self, img: Image.Image) -> bool:
        try:
            gray = img.convert("L")
            edges = gray.filter(ImageFilter.FIND_EDGES)
            stat = ImageStat.Stat(edges)
            return stat.mean[0] < self.BLUR_THRESHOLD
        except Exception:
            return False

    def _is_low_contrast(self, img: Image.Image) -> bool:
        try:
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            return stat.stddev[0] < self.LOW_CONTRAST_THRESHOLD
        except Exception:
            return False

    def _resize_maintaining_aspect(self, img: Image.Image, max_dim: int) -> Image.Image:
        w, h = img.size
        if w >= h:
            new_w = max_dim
            new_h = int(h * (max_dim / w))
        else:
            new_h = max_dim
            new_w = int(w * (max_dim / h))
        return img.resize((new_w, new_h), Image.LANCZOS)

    def _to_base64_jpeg(self, img: Image.Image, quality: int = 85) -> str:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

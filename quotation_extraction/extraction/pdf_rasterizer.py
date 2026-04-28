"""PDF → image rasterization via PyMuPDF (fitz).

Converts each page of a PDF to a base64-encoded JPEG for vision-based LLM
extraction.  Uses PyMuPDF's built-in rendering engine — no external system
dependencies required (unlike pdftoppm/poppler).

Install:  poetry add pymupdf
"""
import base64
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PageImage:
    """A single rasterized PDF page."""

    page_number: int       # 1-based
    base64_jpeg: str       # base64-encoded JPEG data
    width: int = 0
    height: int = 0


class PDFRasterizerError(Exception):
    """Raised when PDF rasterization fails."""


class PDFRasterizer:
    """Convert PDF pages to JPEG images using PyMuPDF.

    Uses fitz.Page.get_pixmap() for rendering — pure Python, zero system
    dependencies, works on any platform (Render, Heroku, AWS, etc.).
    """

    def __init__(self, dpi: int | None = None) -> None:
        self.dpi = dpi or settings.vision_dpi

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rasterize(
        self,
        file_path: str | Path,
        page_numbers: list[int] | None = None,
    ) -> list[PageImage]:
        """
        Rasterize pages of *file_path* into JPEG images.

        Args:
            file_path: Path to the PDF file.
            page_numbers: Optional list of 1-based page numbers to rasterize.
                          If None, all pages are rasterized.

        Returns a list of ``PageImage`` objects sorted by page number.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")

        logger.info("rasterize_started", file=str(file_path), dpi=self.dpi)

        try:
            doc = fitz.open(str(file_path))
            pages: list[PageImage] = []

            # Determine which pages to rasterize
            if page_numbers:
                indices = [p - 1 for p in page_numbers if 0 <= p - 1 < doc.page_count]
            else:
                indices = list(range(doc.page_count))

            for page_idx in indices:
                page = doc.load_page(page_idx)

                # Render at the configured DPI (default 200)
                # fitz default is 72 dpi; zoom = target_dpi / 72
                zoom = self.dpi / 72.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)

                # Convert to JPEG bytes in-memory
                jpeg_bytes = pix.tobytes("jpeg")
                b64 = base64.b64encode(jpeg_bytes).decode("utf-8")

                pages.append(
                    PageImage(
                        page_number=page_idx + 1,  # 1-based
                        base64_jpeg=b64,
                        width=pix.width,
                        height=pix.height,
                    )
                )

            doc.close()

            logger.info(
                "rasterize_completed",
                file=str(file_path),
                pages=len(pages),
                dpi=self.dpi,
            )
            return pages

        except Exception as e:
            logger.error("rasterize_error", error=str(e), exc_info=True)
            raise PDFRasterizerError(f"Failed to rasterize PDF: {e}") from e

    def get_page_count(self, file_path: str | Path) -> int:
        """Return the number of pages in the PDF."""
        try:
            doc = fitz.open(str(file_path))
            count = doc.page_count
            doc.close()
            return count
        except Exception as e:
            logger.warning("page_count_error", error=str(e))
            return 0

    def get_metadata(self, file_path: str | Path) -> dict:
        """Extract PDF metadata."""
        try:
            doc = fitz.open(str(file_path))
            meta = doc.metadata or {}
            page_count = doc.page_count
            doc.close()
            return {
                "page_count": page_count,
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "creator": meta.get("creator", ""),
                "producer": meta.get("producer", ""),
            }
        except Exception as e:
            logger.warning("metadata_extraction_failed", error=str(e))
            return {"page_count": 0, "error": str(e)}

"""PDF text and table extraction using pymupdf4llm (markdown-aware)."""
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF — used for metadata & OCR fallback
import pymupdf4llm
import pytesseract
from PIL import Image

from quotation_core.core.config import settings
from quotation_core.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ExtractedTable:
    """Represents an extracted table from a PDF (kept for interface compatibility)."""

    page_number: int
    table_index: int
    headers: list[str]
    rows: list[list[str]]
    bbox: tuple[float, float, float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "page_number": self.page_number,
            "table_index": self.table_index,
            "headers": self.headers,
            "rows": self.rows,
            "bbox": self.bbox,
        }


@dataclass
class ExtractedPage:
    """Represents text and tables extracted from a single page."""

    page_number: int
    text: str                          # Markdown text from pymupdf4llm
    tables: list[ExtractedTable] = field(default_factory=list)
    has_ocr_text: bool = False

    def get_table_rows(self) -> list[dict[str, str]]:
        """Get all table rows as dictionaries."""
        rows: list[dict[str, str]] = []
        for table in self.tables:
            for row in table.rows:
                row_dict = dict(zip(table.headers, row))
                rows.append(row_dict)
        return rows


class PDFParser:
    """Parse PDFs and extract markdown-rich text via pymupdf4llm."""

    def __init__(
        self,
        ocr_enabled: bool | None = None,
        ocr_dpi: int = 300,
    ) -> None:
        self.ocr_enabled = ocr_enabled if ocr_enabled is not None else settings.enable_ocr_fallback
        self.ocr_dpi = ocr_dpi
        self.logger = get_logger(__name__)

    # ------------------------------------------------------------------
    # Public interface (unchanged — pipeline.py calls these)
    # ------------------------------------------------------------------

    def parse(
        self,
        file_path: str | Path,
        data_pages: list[int] | None = None,
    ) -> list[ExtractedPage]:
        """
        Parse PDF and return one ExtractedPage per page.

        Args:
            file_path: Path to the PDF file.
            data_pages: Optional 0-based page indices to restrict extraction.
                        If None, all pages are extracted.

        Returns:
            List of ExtractedPage objects whose ``.text`` is markdown.
        """
        file_path = Path(file_path)
        self.logger.info("pdf_parsing_started", file_path=str(file_path))

        pages = self._extract_with_pymupdf4llm(file_path, data_pages)

        # OCR fallback for pages with very little extracted text
        needs_ocr = any(len(p.text.strip()) < 50 for p in pages)
        if needs_ocr and self.ocr_enabled:
            self.logger.info("ocr_fallback_triggered", file_path=str(file_path))
            pages = self._apply_ocr(file_path, pages)

        self.logger.info(
            "pdf_parsing_completed",
            file_path=str(file_path),
            page_count=len(pages),
        )
        return pages

    def get_full_text(self, pages: list[ExtractedPage]) -> str:
        """
        Concatenate all page texts into a single LLM-ready string.

        Each page is prefixed with ``=== PAGE N ===`` so the LLM knows
        where page boundaries are.
        """
        return "\n\n".join(
            f"=== PAGE {p.page_number} ===\n{p.text}" for p in pages
        )

    def extract_metadata(self, file_path: str | Path) -> dict[str, Any]:
        """Extract PDF metadata using fitz."""
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
            self.logger.warning("metadata_extraction_failed", error=str(e))
            return {"page_count": 0, "error": str(e)}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_with_pymupdf4llm(
        self,
        file_path: Path,
        data_pages: list[int] | None,
    ) -> list[ExtractedPage]:
        """Use pymupdf4llm to produce markdown-aware page chunks."""
        doc = fitz.open(str(file_path))
        total_pages = doc.page_count
        doc.close()

        target_pages = data_pages if data_pages is not None else list(range(total_pages))

        try:
            chunks = pymupdf4llm.to_markdown(
                str(file_path),
                page_chunks=True,
                pages=target_pages,
            )
        except Exception as e:
            self.logger.error("pymupdf4llm_error", error=str(e))
            raise

        extracted: list[ExtractedPage] = []
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            # pymupdf4llm uses 1-based page_number in metadata
            page_num = meta.get("page_number", len(extracted) + 1)
            text = chunk.get("text", "")

            extracted.append(
                ExtractedPage(
                    page_number=page_num,
                    text=text,
                )
            )

        return extracted

    def _apply_ocr(
        self,
        file_path: Path,
        existing_pages: list[ExtractedPage],
    ) -> list[ExtractedPage]:
        """Apply OCR to pages with low text content (fitz + pytesseract)."""
        try:
            doc = fitz.open(str(file_path))

            for page in existing_pages:
                if len(page.text.strip()) < 50:
                    # page_number is 1-based; fitz index is 0-based
                    pdf_page = doc[page.page_number - 1]
                    pix = pdf_page.get_pixmap(dpi=self.ocr_dpi)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))

                    ocr_text = pytesseract.image_to_string(img)
                    if ocr_text.strip():
                        page.text = ocr_text
                        page.has_ocr_text = True
                        self.logger.info("ocr_applied", page=page.page_number)

            doc.close()
        except Exception as e:
            self.logger.error("ocr_error", error=str(e))

        return existing_pages

    # ------------------------------------------------------------------
    # Convenience helpers (kept for any direct callers)
    # ------------------------------------------------------------------

    def get_all_tables(self, pages: list[ExtractedPage]) -> list[ExtractedTable]:
        """Get all tables from all pages."""
        tables: list[ExtractedTable] = []
        for page in pages:
            tables.extend(page.tables)
        return tables

"""Page classification — Pure LLM Flash pre-filtering based on images.

Classifies each rasterized page image using the fast/cheap Flash model before 
sending to the expensive vision model (Pro). We strictly rely on image classification
rather than PyMuPDF text extraction, because text extraction flattens visual 
indentation and layout (which encodes crucial meaning in complex quotations).
"""
import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import get_logger
from quotation_extraction.extraction.pdf_rasterizer import PageImage

logger = get_logger(__name__)


class PageType(str, Enum):
    """Classification result for a PDF page."""
    PRICING = "pricing"          # Contains line items, prices, quantities
    HEADER = "header"            # Cover page with quotation header info
    APPENDIX = "appendix"        # Appendix or supplementary info
    LEGAL = "legal"              # Terms & conditions, legal text
    DRAWING = "drawing"          # Technical drawings, diagrams
    BLANK = "blank"              # Empty or near-empty page
    CERTIFICATE = "certificate"  # Quality certs, compliance docs
    UNKNOWN = "unknown"          # Could not classify


@dataclass
class PageClassification:
    """Classification result for a single page."""
    page_number: int        # 1-based
    page_type: PageType
    confidence: float       # 0.0 - 1.0
    should_extract: bool    # Whether to send to Pro model
    reason: str             # Human-readable reason


class PageClassifier:
    """Classifies PDF page images using Gemini Flash to filter irrelevant content."""

    def __init__(self) -> None:
        self._flash_available = bool(settings.flash_model)

    async def classify_pages(
        self,
        pages: list[PageImage],
    ) -> list[PageClassification]:
        """
        Classify all page images using the Flash model in a single batch call.

        Returns a list of PageClassification objects.
        Pages with should_extract=True will be forwarded to the Pro model.
        """
        if not self._flash_available or not pages:
            logger.warning("flash_model_not_configured_skipping_classification")
            return [
                PageClassification(
                    page_number=p.page_number,
                    page_type=PageType.UNKNOWN,
                    confidence=0.0,
                    should_extract=True,
                    reason="Flash disabled"
                ) for p in pages
            ]

        logger.info("page_classification_started", pages=len(pages), flash_model=settings.flash_model)

        try:
            from litellm import acompletion
            
            # Construct the content array with all images
            content_array: list[dict[str, Any]] = [
                {"type": "text", "text": "Classify the following pages. I will provide the images in order."}
            ]
            
            for page in pages:
                content_array.append({"type": "text", "text": f"Page {page.page_number}:"})
                content_array.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{page.base64_jpeg}",
                        },
                    }
                )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a fast document sorter. Look at the images of the quotation document pages "
                        "and classify each one into exactly one category based purely on its visual layout.\n"
                        "Return ONLY a JSON array of objects, where each object has:\n"
                        '[{"page_number": int, "type": "pricing"|"header"|"legal"|"drawing"|"certificate"|"blank"|"appendix", '
                        '"confidence": 0.0-1.0, "reason": "brief explanation"}]\n\n'
                        "Definitions:\n"
                        "- pricing: Contains tables of products, prices, quantities. (Keep these)\n"
                        "- header: Cover page with company names, dates, references. (Keep these)\n"
                        "- legal: Dense blocks of tiny text, Terms and Conditions. (Discard)\n"
                        "- drawing: Schematics, blueprints. (Discard)\n"
                        "- certificate: ISO certificates, stamps of compliance. (Discard)\n"
                        "- appendix: Spec sheets without prices. (Discard)\n"
                        "- blank: Empty or nearly empty pages. (Discard)"
                    ),
                },
                {
                    "role": "user",
                    "content": content_array,
                },
            ]
            
            # Use FREE key if configured and model is gemini
            kwargs = {
                "model": settings.flash_model,
                "messages": messages,
                "temperature": 0.0,
                "timeout": max(settings.flash_timeout_seconds, 60.0),
            }
            if "gemini" in settings.flash_model.lower() and settings.gemini_api_key_free:
                kwargs["api_key"] = settings.gemini_api_key_free

            try:
                response = await acompletion(**kwargs)
            except Exception as e:
                try:
                    response = await acompletion(**kwargs)
                except Exception as e:
                    # If the FREE tier fails (rate limit, etc.), fallback to the PAID key
                    if settings.gemini_api_key_paid and kwargs.get("api_key") == settings.gemini_api_key_free:
                        logger.warning("flash_free_tier_failed_falling_back_to_paid", error=str(e))
                        kwargs["api_key"] = settings.gemini_api_key_paid
                        response = await acompletion(**kwargs)
                    else:
                        raise e

            content = response.choices[0].message.content or "[]"
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif content.startswith("```"):
                content = content[content.find("\n") + 1 : content.rfind("```")]

            results = json.loads(content.strip())
            
            classifications = []
            for res in results:
                page_type = PageType(res.get("type", "unknown"))
                
                # Only extract Pricing and Header pages (or unknown if unsure)
                should_extract = page_type in {
                    PageType.PRICING,
                    PageType.HEADER,
                    PageType.UNKNOWN,
                }
                
                classifications.append(
                    PageClassification(
                        page_number=res.get("page_number", 0),
                        page_type=page_type,
                        confidence=float(res.get("confidence", 0.5)),
                        should_extract=should_extract,
                        reason=f"Flash: {res.get('reason', 'No reason given')}",
                    )
                )

        except Exception as e:
            logger.warning("flash_classification_failed", error=str(e))
            # On failure, include all pages to be safe
            classifications = [
                PageClassification(
                    page_number=p.page_number,
                    page_type=PageType.UNKNOWN,
                    confidence=0.0,
                    should_extract=True,
                    reason=f"Flash classification failed: {e}",
                ) for p in pages
            ]

        # Log summary
        extract_count = sum(1 for c in classifications if c.should_extract)
        skip_count = len(classifications) - extract_count
        logger.info(
            "page_classification_completed",
            total_pages=len(classifications),
            pages_to_extract=extract_count,
            pages_skipped=skip_count,
            skipped_types={
                c.page_type.value: sum(
                    1 for x in classifications
                    if x.page_type == c.page_type and not x.should_extract
                )
                for c in classifications
                if not c.should_extract
            },
        )

        return classifications

"""Main Extraction Pipeline Orchestrator.

Ties together:
Rasterization → Classification → Preprocessing → LLM Extraction → Post-Processing.
"""
import asyncio
from pathlib import Path
from typing import Any

from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import get_logger
from quotation_extraction.extraction.pdf_rasterizer import PDFRasterizer
from quotation_extraction.extraction.page_classifier import PageClassifier, PageType
from quotation_extraction.extraction.image_preprocessor import ImagePreprocessor
from quotation_extraction.extraction.llm_service import LLMService, LLMServiceError
from quotation_extraction.extraction.post_processor import PostProcessor, ResponseNormalizer
from quotation_extraction.models.extraction import QuotationExtracted

logger = get_logger(__name__)

class ExtractionPipeline:
    """Full pipeline for quotation extraction."""

    def __init__(self):
        self.rasterizer = PDFRasterizer()
        self.classifier = PageClassifier()
        self.preprocessor = ImagePreprocessor()
        self.llm = LLMService()
        self.normalizer = ResponseNormalizer()
        self.post_processor = PostProcessor()
        
    async def process_sync(self, file_path: str | Path) -> QuotationExtracted:
        """Run the full pipeline synchronously (awaiting async parts where needed)."""
        file_path = Path(file_path)
        logger.info("pipeline_started", file=str(file_path))
        
        # 1. Rasterize
        pages = self.rasterizer.rasterize(file_path)
        if not pages:
            raise ValueError("No pages extracted from PDF.")
            
        # 2. Page Classification & Filtering
        if settings.enable_page_filtering:
            # Pass the rasterized images to the async Flash classifier
            classifications = await self.classifier.classify_pages(pages)
                            
            # Filter pages based on Flash classification
            pages_to_keep = [c.page_number for c in classifications if c.should_extract]
            pages = [p for p in pages if p.page_number in pages_to_keep]
            
            if not pages:
                 raise ValueError("No extractable pages found after filtering.")
                 
        # 3. Image Preprocessing
        if settings.enable_image_preprocessing:
            for p in pages:
                res = self.preprocessor.preprocess(p.base64_jpeg)
                p.base64_jpeg = res.base64_jpeg

        # 4. LLM Extraction with Intelligent Retry
        parsed_dict = {}
        metrics = {}
        max_attempts = settings.llm_max_retries
        
        for attempt in range(1, max_attempts + 1):
            try:
                # Pass all filtered pages to Pro in a single call
                # Gemini 2.5 Pro's 2M token context handles this easily and preserves
                # full document context for cross-page semantic references.
                parsed_dict, metrics = self.llm.extract_from_pages(pages, mutation_attempt=attempt)
                
                metrics["attempts"] = attempt
                
                # 5a. Normalization
                canonical_dict = self.normalizer.normalize(parsed_dict)
                
                # Check quality. If very bad, raise error to trigger retry
                if not canonical_dict.get("line_items"):
                    raise LLMServiceError("No line items extracted")
                    
                break # Success!
                
            except LLMServiceError as e:
                logger.warning("extraction_attempt_failed", attempt=attempt, error=str(e))
                if attempt == max_attempts:
                    raise

        # 5b. Validation
        quotation = QuotationExtracted.model_validate(canonical_dict)
        
        # Set metrics
        quotation.extraction_cost = metrics
        quotation.raw_page_count = len(pages)
        
        # 6. Post-processing
        quotation = self.post_processor.process(quotation)
        
        logger.info("pipeline_completed", total_cost=metrics.get("total_cost_usd"))
        return quotation

"""Main extraction pipeline - orchestrates all extraction steps."""
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from quotation_intelligence.core.config import settings
from quotation_intelligence.core.logging_config import get_logger
from quotation_intelligence.extraction.llm_service import LLMExtractionError, LLMService
from quotation_intelligence.extraction.pdf_parser import PDFParser
from quotation_intelligence.extraction.post_processor import PostProcessor
from quotation_intelligence.extraction.regex_extractor import RegexExtractor
from quotation_intelligence.models.database import (
    Document,
    ExtractionConfidence,
    ExtractionResult,
    LineItem,
    ProcessingStatus,
)
from quotation_intelligence.models.extraction import QuotationExtracted
from quotation_intelligence.models.schemas import LineItemCreate

logger = get_logger(__name__)


class ExtractionPipeline:
    """
    Main extraction pipeline that orchestrates:
    1. PDF parsing (text + tables)
    2. Regex candidate extraction
    3. LLM validation & structuring
    4. Post-processing & validation
    5. Database persistence
    """

    def __init__(
        self,
        enable_ocr: bool | None = None,
        enable_llm: bool | None = None,
    ) -> None:
        self.pdf_parser = PDFParser(ocr_enabled=enable_ocr)
        self.regex_extractor = RegexExtractor()
        self.llm_service = LLMService()
        self.post_processor = PostProcessor()
        self.enable_llm = enable_llm if enable_llm is not None else bool(settings.llm_api_key or settings.llm_model)

    async def process_document(
        self,
        file_path: str | Path,
        document: Document,
        db_session: AsyncSession,
    ) -> ProcessingStatus:
        """
        Process a PDF document through the full extraction pipeline.

        Args:
            file_path: Path to the PDF file
            document: Document database model
            db_session: Database session

        Returns:
            Final processing status
        """
        start_time = datetime.utcnow()
        logger.info(
            "extraction_pipeline_started",
            document_id=str(document.id),
            file_name=document.file_name,
        )

        try:
            # Update status
            document.status = ProcessingStatus.PROCESSING
            document.processing_started_at = start_time
            await db_session.commit()

            # Step 1: Parse PDF
            pages = await self._parse_pdf(file_path, document)
            if not pages:
                return await self._handle_failure(
                    document,
                    db_session,
                    "No content extracted from PDF",
                )

            # Step 2: Regex extraction
            full_text = self.pdf_parser.get_full_text(pages)
            # regex_candidates = self.regex_extractor.extract(full_text)

            # Step 3: LLM extraction
            extraction_result = await self._extract_with_llm(
                full_text,
                # regex_candidates,
                pages,
            )

            # Step 4: Post-processing
            processed_result = self.post_processor.process(extraction_result)

            # Step 5: Persist results
            await self._save_extraction_result(
                document,
                processed_result,
                pages,
                db_session,
            )

            # Calculate processing time
            end_time = datetime.utcnow()
            processing_time = (end_time - start_time).total_seconds()

            document.status = ProcessingStatus.COMPLETED
            document.processing_completed_at = end_time
            document.processing_time_seconds = processing_time

            await db_session.commit()

            logger.info(
                "extraction_pipeline_completed",
                document_id=str(document.id),
                processing_time_seconds=processing_time,
                line_items_count=len(processed_result.line_items),
                overall_confidence=processed_result.get_overall_confidence(),
            )

            return ProcessingStatus.COMPLETED

        except Exception as e:
            logger.error(
                "extraction_pipeline_failed",
                document_id=str(document.id),
                error=str(e),
                exc_info=True,
            )
            return await self._handle_failure(document, db_session, str(e))

    async def _parse_pdf(
        self,
        file_path: str | Path,
        document: Document,
    ) -> list:
        """Parse PDF and extract content."""
        pages = self.pdf_parser.parse(file_path)

        # Update document metadata
        metadata = self.pdf_parser.extract_metadata(file_path)
        document.page_count = metadata.get("page_count")

        return pages

    async def _extract_with_llm(
        self,
        text: str,
        regex_candidates: dict[str, Any],
        pages: list,
    ) -> QuotationExtracted:
        """Extract structured data using LLM with fallback."""
        if self.enable_llm and self.llm_service.client:
            try:
                result = self.llm_service.extract_quotation(text, regex_candidates)
                return result
            except LLMExtractionError as e:
                logger.warning("llm_extraction_failed", error=str(e))
                # Fallback to regex-based extraction
                return self.llm_service.fallback_extraction(text)
        else:
            logger.info("llm_disabled_or_not_configured", using="regex_fallback")
            return self.llm_service.fallback_extraction(text)

    async def _save_extraction_result(
        self,
        document: Document,
        result: QuotationExtracted,
        pages: list,
        db_session: AsyncSession,
    ) -> None:
        """Save extraction result to database."""
        # Determine overall status based on confidence
        overall_confidence = result.get_overall_confidence()
        missing_fields = result.get_missing_fields()

        if overall_confidence >= 0.9 and not missing_fields:
            status = ProcessingStatus.COMPLETED
        elif overall_confidence >= 0.7:
            status = ProcessingStatus.COMPLETED
        elif overall_confidence >= 0.5:
            status = ProcessingStatus.PARTIAL
        else:
            status = ProcessingStatus.PARTIAL

        # Create extraction result record
        extraction_result = ExtractionResult(
            document_id=document.id,
            supplier_name=result.supplier_name,
            supplier_name_confidence=result.supplier_name_confidence,
            quotation_number=result.quotation_number,
            quotation_number_confidence=result.quotation_number_confidence,
            quotation_date=result.quotation_date,
            quotation_date_confidence=result.quotation_date_confidence,
            currency=result.currency,
            subtotal=result.subtotal,
            tax_amount=result.tax_amount,
            total_amount=result.total_amount,
            total_confidence=result.total_confidence,
            raw_extracted_data=result.to_export_dict(),
            extraction_errors=result.extraction_errors if result.extraction_errors else [],
        )

        db_session.add(extraction_result)
        await db_session.flush()

        # Create line items
        for item in result.line_items:
            line_item = self._create_line_item(extraction_result.id, item)
            db_session.add(line_item)

        await db_session.flush()

    def _create_line_item(
        self,
        extraction_result_id: UUID,
        item_data: Any,
    ) -> LineItem:
        """Create a LineItem database model from extracted data."""
        overall_confidence = item_data.calculate_overall_confidence()

        # Map confidence to level
        if overall_confidence >= 0.9:
            confidence_level = ExtractionConfidence.HIGH
        elif overall_confidence >= 0.7:
            confidence_level = ExtractionConfidence.MEDIUM
        elif overall_confidence >= 0.5:
            confidence_level = ExtractionConfidence.LOW
        else:
            confidence_level = ExtractionConfidence.UNCERTAIN

        return LineItem(
            extraction_result_id=extraction_result_id,
            line_number=item_data.line_number,
            product_code=item_data.product_code,
            product_code_confidence=item_data.product_code_confidence,
            description=item_data.description,
            description_confidence=item_data.description_confidence,
            quantity=item_data.quantity,
            quantity_confidence=item_data.quantity_confidence,
            unit_of_measure=item_data.unit_of_measure,
            unit_price=item_data.unit_price,
            unit_price_confidence=item_data.unit_price_confidence,
            total_price=item_data.total_price,
            total_price_confidence=item_data.total_price_confidence,
            overall_confidence=overall_confidence,
            confidence_level=confidence_level,
            raw_text=item_data.description if item_data.description else None,
        )

    async def _handle_failure(
        self,
        document: Document,
        db_session: AsyncSession,
        error_message: str,
    ) -> ProcessingStatus:
        """Handle extraction failure."""
        document.status = ProcessingStatus.FAILED
        document.error_message = error_message
        document.processing_completed_at = datetime.utcnow()
        await db_session.commit()

        logger.error(
            "document_processing_failed",
            document_id=str(document.id),
            error=error_message,
        )

        return ProcessingStatus.FAILED

    def process_sync(
        self,
        file_path: str | Path,
    ) -> QuotationExtracted:
        """
        Synchronous version for development/testing.

        Does not persist to database.
        """
        logger.info("sync_processing_started", file_path=str(file_path))

        # Parse PDF
        pages = self.pdf_parser.parse(file_path)
        if not pages:
            raise ValueError("No content extracted from PDF")

        # Extract
        full_text = self.pdf_parser.get_full_text(pages)
        # regex_candidates = self.regex_extractor.extract(full_text)

        # LLM extraction with fallback
        if self.enable_llm and self.llm_service.client:
            try:
                result = self.llm_service.extract_quotation(full_text)
            except LLMExtractionError:
                result = self.llm_service.fallback_extraction(full_text)
        else:
            result = self.llm_service.fallback_extraction(full_text)

        # Post-process
        # return self.post_processor.process(result)
        return result

"""Export service for converting extraction results to various formats."""
import csv
import io
import json
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from quotation_core.core.logging_config import get_logger
from quotation_core.models.database import Document, ExtractionResult, LineItem

logger = get_logger(__name__)


class ExportService:
    """Export extraction results to various formats."""

    @staticmethod
    def to_json(document_id: UUID, extraction_result: ExtractionResult | None) -> str:
        """Export to JSON string."""
        if not extraction_result:
            return json.dumps({"error": "No extraction result found"})

        data = {
            "document_id": str(document_id),
            "supplier_name": extraction_result.supplier_name,
            "quotation_number": extraction_result.quotation_number,
            "quotation_date": extraction_result.quotation_date,
            "currency": extraction_result.currency,
            "subtotal": extraction_result.subtotal,
            "tax_amount": extraction_result.tax_amount,
            "total_amount": extraction_result.total_amount,
            "line_items": [
                {
                    "line_number": item.line_number,
                    "product_code": item.product_code,
                    "description": item.description,
                    "quantity": item.quantity,
                    "unit_of_measure": item.unit_of_measure,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "overall_confidence": item.overall_confidence,
                }
                for item in extraction_result.line_items
            ],
            "metadata": {
                "line_item_count": len(extraction_result.line_items),
                "extraction_errors": extraction_result.extraction_errors,
                "supplier_confidence": extraction_result.supplier_name_confidence,
                "quotation_number_confidence": extraction_result.quotation_number_confidence,
                "quotation_date_confidence": extraction_result.quotation_date_confidence,
                "total_confidence": extraction_result.total_confidence,
            },
        }

        return json.dumps(data, indent=2, default=str)

    @staticmethod
    def to_csv(document_id: UUID, extraction_result: ExtractionResult | None) -> str:
        """Export line items to CSV string."""
        if not extraction_result:
            return "error\nNo extraction result found"

        output = io.StringIO()
        writer = csv.writer(output)

        # Header with metadata
        writer.writerow(["Supplier", extraction_result.supplier_name])
        writer.writerow(["Quotation Number", extraction_result.quotation_number])
        writer.writerow(["Quotation Date", extraction_result.quotation_date])
        writer.writerow(["Currency", extraction_result.currency])
        writer.writerow(["Subtotal", extraction_result.subtotal])
        writer.writerow(["Tax Amount", extraction_result.tax_amount])
        writer.writerow(["Total Amount", extraction_result.total_amount])
        writer.writerow([])  # Empty row

        # Line items header
        writer.writerow([
            "Line #",
            "Product Code",
            "Description",
            "Quantity",
            "UOM",
            "Unit Price",
            "Total Price",
            "Confidence",
        ])

        for item in extraction_result.line_items:
            writer.writerow([
                item.line_number,
                item.product_code,
                item.description,
                item.quantity,
                item.unit_of_measure,
                item.unit_price,
                item.total_price,
                f"{item.overall_confidence:.2f}",
            ])

        return output.getvalue()

    @staticmethod
    def to_excel_bytes(document_id: UUID, extraction_result: ExtractionResult | None) -> bytes:
        """Export to Excel bytes."""
        if not extraction_result:
            # Return empty Excel with error
            df = pd.DataFrame({"error": ["No extraction result found"]})
            buffer = io.BytesIO()
            df.to_excel(buffer, index=False, engine="openpyxl")
            return buffer.getvalue()

        # Create summary DataFrame
        summary_data = {
            "Field": [
                "Document ID",
                "Supplier Name",
                "Quotation Number",
                "Quotation Date",
                "Currency",
                "Subtotal",
                "Tax Amount",
                "Total Amount",
            ],
            "Value": [
                str(document_id),
                extraction_result.supplier_name,
                extraction_result.quotation_number,
                extraction_result.quotation_date,
                extraction_result.currency,
                extraction_result.subtotal,
                extraction_result.tax_amount,
                extraction_result.total_amount,
            ],
            "Confidence": [
                "",
                extraction_result.supplier_name_confidence,
                extraction_result.quotation_number_confidence,
                extraction_result.quotation_date_confidence,
                "",
                "",
                "",
                extraction_result.total_confidence,
            ],
        }

        # Create line items DataFrame
        line_items_data = []
        for item in extraction_result.line_items:
            line_items_data.append({
                "Line #": item.line_number,
                "Product Code": item.product_code,
                "Description": item.description,
                "Quantity": item.quantity,
                "UOM": item.unit_of_measure,
                "Unit Price": item.unit_price,
                "Total Price": item.total_price,
                "Confidence": item.overall_confidence,
                "Product Code Confidence": item.product_code_confidence,
                "Description Confidence": item.description_confidence,
                "Quantity Confidence": item.quantity_confidence,
                "Unit Price Confidence": item.unit_price_confidence,
                "Total Price Confidence": item.total_price_confidence,
            })

        # Write to Excel with multiple sheets
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            # Summary sheet
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name="Summary", index=False)

            # Line items sheet
            line_items_df = pd.DataFrame(line_items_data)
            line_items_df.to_excel(writer, sheet_name="Line Items", index=False)

        return buffer.getvalue()

    @staticmethod
    async def get_extraction_result(
        db_session: AsyncSession,
        document_id: UUID,
    ) -> tuple[Document | None, ExtractionResult | None]:
        """Fetch document and extraction result from database."""
        # Get document
        doc_result = await db_session.execute(
            select(Document).where(Document.id == document_id)
        )
        document = doc_result.scalar_one_or_none()

        if not document:
            return None, None

        # Get extraction result with line items
        extraction_result = await db_session.execute(
            select(ExtractionResult)
            .where(ExtractionResult.document_id == document_id)
            .options(select(ExtractionResult).selectinload(ExtractionResult.line_items))
        )
        extraction = extraction_result.scalar_one_or_none()

        return document, extraction

    @staticmethod
    def generate_export_filename(
        document_id: UUID,
        extraction_result: ExtractionResult | None,
        format: str,
    ) -> str:
        """Generate a meaningful filename for export."""
        if extraction_result and extraction_result.quotation_number:
            base = f"quotation_{extraction_result.quotation_number}"
        else:
            base = f"document_{str(document_id)[:8]}"

        # Clean filename
        base = "".join(c for c in base if c.isalnum() or c in "_-").strip()

        extensions = {
            "json": "json",
            "csv": "csv",
            "excel": "xlsx",
        }

        ext = extensions.get(format, "txt")
        return f"{base}.{ext}"

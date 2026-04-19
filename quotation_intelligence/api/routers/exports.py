"""Export endpoints for extraction results."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from quotation_core.core.security import verify_api_key
from quotation_core.core.logging_config import get_logger
from quotation_core.models.database import get_db_session
from quotation_core.models.schemas import ExportFormat
from quotation_core.services.export_service import ExportService

logger = get_logger(__name__)
router = APIRouter()


@router.get(
    "/{document_id}",
    response_model=None,  # Returns file responses, not a Pydantic model
)
async def export_result(
    document_id: UUID,
    format: ExportFormat = Query(ExportFormat.JSON),
    include_metadata: bool = Query(True),
    include_confidence: bool = Query(True),
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> StreamingResponse | JSONResponse:
    """
    Export extraction result in various formats.

    Supported formats: json, csv, excel
    """
    document, extraction = await ExportService.get_extraction_result(
        db_session,
        document_id,
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if not extraction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction result not found",
        )

    logger.info(
        "export_requested",
        document_id=str(document_id),
        format=format.value,
    )

    filename = ExportService.generate_export_filename(document_id, extraction, format.value)

    if format == ExportFormat.JSON:
        content = ExportService.to_json(document_id, extraction)
        return JSONResponse(
            content=content,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    elif format == ExportFormat.CSV:
        content = ExportService.to_csv(document_id, extraction)
        return StreamingResponse(
            iter([content]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    elif format == ExportFormat.EXCEL:
        content = ExportService.to_excel_bytes(document_id, extraction)
        return StreamingResponse(
            iter([content]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: {format}",
        )


@router.get("/preview/{document_id}", response_model=None)
async def preview_result(
    document_id: UUID,
    db_session: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(verify_api_key),
) -> JSONResponse:
    """
    Get a quick preview of extraction results (JSON format, inline).
    """
    document, extraction = await ExportService.get_extraction_result(
        db_session,
        document_id,
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # Return preview (first 10 line items max)
    if extraction:
        preview_data = {
            "document_id": str(document_id),
            "status": document.status.value,
            "supplier_name": extraction.supplier_name,
            "quotation_number": extraction.quotation_number,
            "quotation_date": extraction.quotation_date,
            "currency": extraction.currency,
            "total_amount": extraction.total_amount,
            "line_items_preview": [
                {
                    "line": item.line_number,
                    "product_code": item.product_code,
                    "description": item.description[:50] + "..." if item.description and len(item.description) > 50 else item.description,
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                }
                for item in extraction.line_items[:10]
            ],
            "total_line_items": len(extraction.line_items),
            "extraction_confidence": {
                "supplier": extraction.supplier_name_confidence,
                "quotation_number": extraction.quotation_number_confidence,
                "total": extraction.total_confidence,
            },
        }
    else:
        preview_data = {
            "document_id": str(document_id),
            "status": document.status.value,
            "message": "No extraction result available yet",
        }

    return JSONResponse(content=preview_data)

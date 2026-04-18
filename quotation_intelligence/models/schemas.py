"""Pydantic schemas for API input/output validation."""
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProcessingStatus(str, Enum):
    """Document processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class ExtractionConfidence(str, Enum):
    """Confidence level for extraction results."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"


# ============== Input Schemas ==============

class DocumentUploadBase64(BaseModel):
    """Upload document via Base64 encoding (production)."""

    file_name: str = Field(..., description="Original file name", max_length=255)
    file_content_base64: str = Field(
        ...,
        description="Base64-encoded PDF content",
        min_length=1,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata for the document",
    )

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, v: str) -> str:
        """Validate file name ends with .pdf."""
        if not v.lower().endswith(".pdf"):
            raise ValueError("File must be a PDF")
        return v


class DocumentUploadLocal(BaseModel):
    """Upload document via local file path (development mode)."""

    file_path: str = Field(..., description="Absolute path to PDF file")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata for the document",
    )

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, v: str) -> str:
        """Validate file path ends with .pdf."""
        if not v.lower().endswith(".pdf"):
            raise ValueError("File must be a PDF")
        return v


class DocumentUploadRequest(BaseModel):
    """Main upload request - either base64 or local path."""

    base64_upload: DocumentUploadBase64 | None = None
    local_upload: DocumentUploadLocal | None = None

    @field_validator("local_upload")
    @classmethod
    def validate_single_upload_method(
        cls,
        v: DocumentUploadLocal | None,
        info: Any,
    ) -> DocumentUploadLocal | None:
        """Ensure only one upload method is provided."""
        data = info.data
        if v is not None and data.get("base64_upload") is not None:
            raise ValueError("Only one of base64_upload or local_upload should be provided")
        if v is None and data.get("base64_upload") is None:
            raise ValueError("Either base64_upload or local_upload must be provided")
        return v


# ============== Line Item Schemas ==============

class LineItemSchema(BaseModel):
    """Schema for extracted line item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    line_number: int | None = None
    product_code: str | None = None
    product_code_confidence: float | None = None
    description: str | None = None
    description_confidence: float | None = None
    quantity: float | None = None
    quantity_confidence: float | None = None
    unit_of_measure: str | None = None
    unit_price: float | None = None
    unit_price_confidence: float | None = None
    total_price: float | None = None
    total_price_confidence: float | None = None
    overall_confidence: float
    confidence_level: ExtractionConfidence
    raw_text: str | None = None


class LineItemCreate(BaseModel):
    """Create a line item (internal use)."""

    line_number: int | None = None
    product_code: str | None = None
    product_code_confidence: float | None = None
    description: str | None = None
    description_confidence: float | None = None
    quantity: float | None = None
    quantity_confidence: float | None = None
    unit_of_measure: str | None = None
    unit_price: float | None = None
    unit_price_confidence: float | None = None
    total_price: float | None = None
    total_price_confidence: float | None = None
    overall_confidence: float = 0.0
    raw_text: str | None = None

    def calculate_overall_confidence(self) -> float:
        """Calculate overall confidence from field confidences."""
        confidences = [
            c for c in [
                self.product_code_confidence,
                self.description_confidence,
                self.quantity_confidence,
                self.unit_price_confidence,
                self.total_price_confidence,
            ]
            if c is not None
        ]
        if not confidences:
            return 0.0
        return sum(confidences) / len(confidences)


# ============== Extraction Result Schemas ==============

class ExtractionResultSchema(BaseModel):
    """Schema for extraction result."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    supplier_name: str | None = None
    supplier_name_confidence: float | None = None
    quotation_number: str | None = None
    quotation_number_confidence: float | None = None
    quotation_date: str | None = None
    quotation_date_confidence: float | None = None
    currency: str | None = None
    subtotal: float | None = None
    tax_amount: float | None = None
    total_amount: float | None = None
    total_confidence: float | None = None
    extraction_errors: list[str] | None = None
    line_items: list[LineItemSchema]
    created_at: datetime


class ExtractionSummary(BaseModel):
    """Summary of extraction for quick overview."""

    line_item_count: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    average_confidence: float
    missing_fields: list[str]


# ============== Document Response Schemas ==============

class DocumentResponse(BaseModel):
    """Response schema for document upload/processing."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    file_name: str
    file_size_bytes: int | None = None
    page_count: int | None = None
    status: ProcessingStatus
    uploaded_at: datetime
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    processing_time_seconds: float | None = None
    error_message: str | None = None


class DocumentDetailResponse(DocumentResponse):
    """Detailed response including extraction results."""

    extraction_result: ExtractionResultSchema | None = None


class ProcessingResponse(BaseModel):
    """Response for processing endpoint."""

    document_id: UUID
    status: ProcessingStatus
    message: str
    estimated_completion_time: str | None = None


class SyncExtractionResponse(BaseModel):
    """Response for synchronous extraction (standalone mode, no database)."""

    status: ProcessingStatus
    data: dict[str, Any]
    confidence_summary: ExtractionSummary
    processing_time_seconds: float
    extraction_errors: list[str]


class ExtractionOutput(BaseModel):
    """Final structured extraction output."""

    document_id: UUID
    status: ProcessingStatus
    data: dict[str, Any]
    confidence_summary: ExtractionSummary
    export_formats: dict[str, str | None]


# ============== Export Schemas ==============

class ExportFormat(str, Enum):
    """Available export formats."""

    JSON = "json"
    EXCEL = "excel"
    CSV = "csv"


class ExportRequest(BaseModel):
    """Request to export extraction result."""

    format: ExportFormat
    include_metadata: bool = True
    include_confidence_scores: bool = True


# ============== Error Schemas ==============

class ErrorResponse(BaseModel):
    """Standard error response."""

    error_code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None

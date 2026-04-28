"""Pydantic schemas for API input/output validation."""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ProcessingStatus(str, Enum):
    """Document processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


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
        """Validate file name ends with .pdf, append if missing."""
        if not v.lower().endswith(".pdf"):
            return f"{v}.pdf"
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


# ============== Response Schemas ==============

class ExtractionSummary(BaseModel):
    """Summary of extraction for quick overview."""

    line_item_count: int
    high_confidence_count: int
    medium_confidence_count: int
    low_confidence_count: int
    average_confidence: float
    missing_fields: list[str]


class ErrorResponse(BaseModel):
    """Standard error response."""

    error_code: str = "ERROR"
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None

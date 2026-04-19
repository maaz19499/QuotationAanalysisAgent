"""Database models and session management."""
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, Float, Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from quotation_core.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


class ProcessingStatus(PyEnum):
    """Document processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class ExtractionConfidence(PyEnum):
    """Confidence level for extraction results."""

    HIGH = "high"  # >= 0.9
    MEDIUM = "medium"  # 0.7 - 0.89
    LOW = "low"  # 0.5 - 0.69
    UNCERTAIN = "uncertain"  # < 0.5


class Document(Base):
    """PDF document uploaded for processing."""

    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(50), default="application/pdf")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Status
    status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus),
        default=ProcessingStatus.PENDING,
    )

    # Metadata
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Error handling
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Relations
    extraction_result: Mapped["ExtractionResult | None"] = relationship(
        "ExtractionResult",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Document {self.id}: {self.file_name} ({self.status.value})>"


class ExtractionResult(Base):
    """Structured extraction result from a document."""

    __tablename__ = "extraction_results"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        "documents.id",
        unique=True,
    )

    # Supplier Info
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_name_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quotation_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quotation_number_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quotation_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quotation_date_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Totals
    subtotal: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Raw extraction data
    raw_extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    extraction_errors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Relations
    document: Mapped[Document] = relationship("Document", back_populates="extraction_result")
    line_items: Mapped[list["LineItem"]] = relationship(
        "LineItem",
        back_populates="extraction_result",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ExtractionResult {self.id}: {self.supplier_name} - {len(self.line_items)} items>"


class LineItem(Base):
    """Individual line item from a quotation."""

    __tablename__ = "line_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    extraction_result_id: Mapped[UUID] = mapped_column("extraction_results.id")

    # Fields
    line_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    product_code_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_price_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Overall confidence
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_level: Mapped[ExtractionConfidence] = mapped_column(
        Enum(ExtractionConfidence),
        default=ExtractionConfidence.UNCERTAIN,
    )

    # Raw data
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relations
    extraction_result: Mapped[ExtractionResult] = relationship(
        "ExtractionResult",
        back_populates="line_items",
    )

    def __repr__(self) -> str:
        return f"<LineItem {self.id}: {self.product_code} - {self.description[:50]}>"


async def get_db_session() -> AsyncSession:
    """Get a database session."""
    async with AsyncSessionLocal() as session:
        yield session

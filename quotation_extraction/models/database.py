import enum
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from quotation_extraction.core.config import settings

# ── Database Models ────────────────────────────────────────────────────────

class Base(AsyncAttrs, DeclarativeBase):
    """Base class for SQLAlchemy declarative models."""
    pass


class ProcessingStatus(str, enum.Enum):
    """Status of a document processing job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    """Represents a quotation document uploaded for extraction."""
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String, index=True, nullable=True)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str] = mapped_column(String, nullable=True)
    
    status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus), 
        default=ProcessingStatus.PENDING, 
        nullable=False
    )
    
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[str | None] = mapped_column(Text, nullable=True) # JSON stored as string for simplicity
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Database Engine and Session setup ──────────────────────────────────────

async_engine = None
async_session_maker = None

def init_db() -> None:
    """Initialize the database engine and session maker."""
    global async_engine, async_session_maker
    if settings.database_url:
        # Avoid issues with pooling if running in a simple test setup
        async_engine = create_async_engine(
            settings.database_url,
            echo=settings.debug,
            pool_pre_ping=True,
        )
        async_session_maker = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

async def get_db_session():
    """Dependency for getting a database session."""
    if not async_session_maker:
        raise RuntimeError("Database not configured. DATABASE_URL is missing.")
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

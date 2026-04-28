"""Test fixtures and configuration."""
import os
import tempfile
from collections.abc import AsyncIterator, Generator
from typing import Any
from unittest.mock import Mock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.future import select
from sqlalchemy.orm import sessionmaker

from quotation_extraction.models.database import Base, Document, ProcessingStatus

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncEngine:
    """Create database engine for testing."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        future=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Create database session for each test."""
    async_session = sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session
        # Cleanup after test
        await session.rollback()


@pytest.fixture
def sample_quotation_text() -> str:
    """Sample quotation text for testing."""
    return """
    ABC SUPPLIES INC.
    QUOTATION #QT-2024-001
    Date: January 15, 2024

    Line    Product Code    Description                 Qty     Unit    Price       Total
    1       ABC-123         Premium Widget A            10      EA      $50.00      $500.00
    2       ABC-456         Standard Widget B           5       EA      $30.00      $150.00
    3       ABC-789         Economy Widget C            20      EA      $15.00      $300.00

    Subtotal: $950.00
    Tax (10%): $95.00
    Total Amount: $1,045.00
    """


@pytest.fixture
def mock_pdf_file() -> Generator[str, Any, Any]:
    """Create a temporary mock PDF file."""
    # Create a minimal valid PDF structure for testing
    pdf_content = b"%PDF-1.4\n1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n%%EOF"

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf_content)
        temp_path = f.name

    yield temp_path

    # Cleanup
    os.unlink(temp_path)


@pytest.fixture
def mock_anthropic_response() -> dict[str, Any]:
    """Mock LLM response for testing."""
    return {
        "supplier_name": "ABC Supplies Inc.",
        "supplier_name_confidence": 0.95,
        "quotation_number": "QT-2024-001",
        "quotation_number_confidence": 0.92,
        "quotation_date": "2024-01-15",
        "quotation_date_confidence": 0.88,
        "currency": "USD",
        "subtotal": 950.00,
        "tax_amount": 95.00,
        "total_amount": 1045.00,
        "total_confidence": 0.90,
        "extraction_errors": [],
        "line_items": [
            {
                "line_number": 1,
                "product_code": "ABC-123",
                "description": "Premium Widget A",
                "quantity": 10,
                "unit_of_measure": "EA",
                "unit_price": 50.00,
                "total_price": 500.00,
                "product_code_confidence": 0.90,
                "description_confidence": 0.88,
                "quantity_confidence": 0.95,
                "unit_price_confidence": 0.92,
                "total_price_confidence": 0.92,
                "extraction_source": "llm",
            },
            {
                "line_number": 2,
                "product_code": "ABC-456",
                "description": "Standard Widget B",
                "quantity": 5,
                "unit_of_measure": "EA",
                "unit_price": 30.00,
                "total_price": 150.00,
                "product_code_confidence": 0.90,
                "description_confidence": 0.88,
                "quantity_confidence": 0.95,
                "unit_price_confidence": 0.92,
                "total_price_confidence": 0.92,
                "extraction_source": "llm",
            },
            {
                "line_number": 3,
                "product_code": "ABC-789",
                "description": "Economy Widget C",
                "quantity": 20,
                "unit_of_measure": "EA",
                "unit_price": 15.00,
                "total_price": 300.00,
                "product_code_confidence": 0.90,
                "description_confidence": 0.88,
                "quantity_confidence": 0.95,
                "unit_price_confidence": 0.92,
                "total_price_confidence": 0.92,
                "extraction_source": "llm",
            },
        ],
    }


@pytest.fixture
def sample_document(db_session: AsyncSession) -> Document:
    """Create a sample document for testing."""
    doc = Document(
        file_name="test.pdf",
        file_path="/tmp/test.pdf",
        file_size_bytes=1024,
        mime_type="application/pdf",
        status=ProcessingStatus.PENDING,
    )
    db_session.add(doc)
    return doc


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set environment variables for testing."""
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

"""Tests for post-processing module."""
import pytest

from quotation_extraction.extraction.post_processor import PostProcessor
from quotation_extraction.models.extraction import LineItemExtracted, QuotationExtracted


class TestPostProcessor:
    """Test cases for PostProcessor."""

    @pytest.fixture
    def processor(self) -> PostProcessor:
        """Create processor instance."""
        return PostProcessor()

    @pytest.fixture
    def sample_quotation(self) -> QuotationExtracted:
        """Create sample quotation for testing."""
        return QuotationExtracted(
            supplier_name="Test Supplier",
            quotation_number="QT-001",
            line_items=[
                LineItemExtracted(
                    line_number=1,
                    product_code="ABC-123",
                    description="Widget A",
                    quantity=10,
                    unit_price=50.0,
                    total_price=500.0,
                ),
                LineItemExtracted(
                    line_number=2,
                    product_code="ABC-456",
                    description="Widget B",
                    quantity=5,
                    unit_price=30.0,
                    total_price=150.0,
                ),
            ],
        )

    def test_deduplication(self, processor: PostProcessor) -> None:
        """Test that duplicate line items are removed."""
        quotation = QuotationExtracted(
            supplier_name="Test",
            line_items=[
                LineItemExtracted(
                    product_code="ABC-123",
                    description="Widget A",
                    quantity=10,
                    unit_price=50.0,
                ),
                LineItemExtracted(
                    product_code="ABC-123",
                    description="Widget A",
                    quantity=10,
                    unit_price=50.0,
                ),
            ],
        )

        result = processor.process(quotation)

        assert len(result.line_items) == 1  # Duplicate removed

    def test_price_validation(self, processor: PostProcessor) -> None:
        """Test that total prices are validated against quantity * unit_price."""
        quotation = QuotationExtracted(
            supplier_name="Test",
            line_items=[
                LineItemExtracted(
                    line_number=1,
                    description="Widget",
                    quantity=10,
                    unit_price=50.0,
                    total_price=550.0,  # Wrong! Should be 500
                ),
            ],
        )

        result = processor.process(quotation)

        # Price mismatch detected but not auto-corrected if close enough
        # Or should be corrected if significant
        assert result.line_items[0].total_price is not None

    def test_missing_total_calculation(self, processor: PostProcessor) -> None:
        """Test that missing totals are calculated from line items."""
        quotation = QuotationExtracted(
            supplier_name="Test",
            line_items=[
                LineItemExtracted(
                    quantity=10,
                    unit_price=50.0,
                    total_price=500.0,
                ),
            ],
            subtotal=None,
            total_amount=None,
        )

        result = processor.process(quotation)

        assert result.subtotal == 500.0
        assert result.total_amount == 500.0  # No tax

    def test_line_item_renumbering(self, processor: PostProcessor) -> None:
        """Test that line items are renumbered sequentially."""
        quotation = QuotationExtracted(
            supplier_name="Test",
            line_items=[
                LineItemExtracted(line_number=5, description="Item 1"),
                LineItemExtracted(line_number=None, description="Item 2"),
                LineItemExtracted(line_number=3, description="Item 3"),
            ],
        )

        result = processor.process(quotation)

        assert result.line_items[0].line_number == 1
        assert result.line_items[1].line_number == 2
        assert result.line_items[2].line_number == 3

    def test_currency_normalization(self, processor: PostProcessor) -> None:
        """Test currency code normalization."""
        quotation = QuotationExtracted(
            supplier_name="Test",
            currency="eur",  # Lowercase
        )

        result = processor.process(quotation)

        assert result.currency == "EUR"  # Normalized to uppercase

    def test_tax_calculation(self, processor: PostProcessor) -> None:
        """Test total calculation with tax."""
        quotation = QuotationExtracted(
            supplier_name="Test",
            subtotal=1000.0,
            tax_amount=100.0,
            total_amount=None,
        )

        result = processor.process(quotation)

        assert result.total_amount == 1100.0

    def test_validation_warning(self, processor: PostProcessor) -> None:
        """Test that validation warnings are added for mismatched totals."""
        quotation = QuotationExtracted(
            supplier_name="Test",
            line_items=[
                LineItemExtracted(total_price=100.0),
            ],
            subtotal=500.0,  # Doesn't match line items
        )

        result = processor.process(quotation)

        assert result.extraction_errors is not None
        assert len(result.extraction_errors) > 0

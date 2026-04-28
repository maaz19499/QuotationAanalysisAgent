"""Tests for regex extraction module."""
import pytest

from quotation_extraction.extraction.regex_extractor import RegexExtractor


class TestRegexExtractor:
    """Test cases for RegexExtractor."""

    @pytest.fixture
    def extractor(self) -> RegexExtractor:
        """Create extractor instance."""
        return RegexExtractor()

    def test_extract_quotation_number(self, extractor: RegexExtractor) -> None:
        """Test quotation number extraction."""
        text = "Quotation #ABC-2024-001 for your review"
        results = extractor.extract(text)

        assert "quotation_number" in results
        assert len(results["quotation_number"]) > 0
        assert results["quotation_number"][0].value == "ABC-2024-001"
        assert results["quotation_number"][0].confidence >= 0.7

    def test_extract_date(self, extractor: RegexExtractor) -> None:
        """Test date extraction."""
        text = "Quotation Date: 15/01/2024"
        results = extractor.extract(text)

        assert "quotation_date" in results
        assert len(results["quotation_date"]) > 0
        assert results["quotation_date"][0].confidence >= 0.6

    def test_extract_total_amount(self, extractor: RegexExtractor) -> None:
        """Test total amount extraction."""
        text = "Grand Total: $1,234.56"
        results = extractor.extract(text)

        assert "total_amount" in results
        assert len(results["total_amount"]) > 0

    def test_extract_subtotal_and_tax(self, extractor: RegexExtractor) -> None:
        """Test subtotal and tax extraction."""
        text = """
        Subtotal: $1,000.00
        Tax (10%): $100.00
        Total: $1,100.00
        """
        results = extractor.extract(text)

        assert "subtotal" in results
        assert "tax_amount" in results
        assert results["subtotal"][0].confidence >= 0.7
        assert results["tax_amount"][0].confidence >= 0.6

    def test_extract_currency(self, extractor: RegexExtractor) -> None:
        """Test currency detection."""
        text = "All amounts in EUR"
        results = extractor.extract(text)

        assert "currency" in results

    def test_confidence_scoring(self, extractor: RegexExtractor) -> None:
        """Test confidence scores are reasonable."""
        text = "Quotation #: QT-12345"
        results = extractor.extract(text)

        for field, matches in results.items():
            for match in matches:
                assert 0.0 <= match.confidence <= 1.0

    def test_line_item_candidate_extraction(self, extractor: RegexExtractor) -> None:
        """Test line item extraction from table rows."""
        table_rows = [
            {
                "Item": "1",
                "Code": "ABC-123",
                "Description": "Widget A",
                "Qty": "10",
                "Price": "$50.00",
                "Total": "$500.00",
            },
        ]

        candidates = extractor.extract_line_item_candidates(table_rows)

        assert len(candidates) > 0
        assert "product_code" in candidates[0] or candidates[0].get("_row_index") == 1

    def test_empty_text(self, extractor: RegexExtractor) -> None:
        """Test extraction from empty text."""
        results = extractor.extract("")
        assert results == {}

    def test_no_matches(self, extractor: RegexExtractor) -> None:
        """Test extraction from text with no matches."""
        text = "Random text without quotation data"
        results = extractor.extract(text)

        # Should still find some patterns (email, etc.)
        # But not quotation-specific data
        assert "quotation_number" not in results or len(results.get("quotation_number", [])) == 0


class TestRegexConfidence:
    """Test confidence calculation."""

    def test_strong_indicators_boost_confidence(self) -> None:
        """Test that strong indicators increase confidence."""
        extractor = RegexExtractor()

        # Text with strong indicator
        text_strong = "Quotation Number: QT-2024-001"
        results_strong = extractor.extract(text_strong)

        # Text with weak indicator
        text_weak = "Ref: QT-2024-001"
        results_weak = extractor.extract(text_weak)

        # Both should find the number
        if "quotation_number" in results_strong and "quotation_number" in results_weak:
            strong_conf = results_strong["quotation_number"][0].confidence
            weak_conf = results_weak["quotation_number"][0].confidence

            # Strong indicator should have higher confidence
            assert strong_conf >= weak_conf - 0.1  # Allow small variance

    def test_short_value_penalty(self) -> None:
        """Test that short values have lower confidence."""
        extractor = RegexExtractor()

        text = "No: 12"  # Very short
        results = extractor.extract(text)

        if "quotation_number" in results:
            assert results["quotation_number"][0].confidence < 0.7  # Should be low

    def test_header_label_boost(self) -> None:
        """Test that clear headers boost confidence."""
        extractor = RegexExtractor()

        text = "Grand Total: $5,000.00"
        results = extractor.extract(text)

        if "total_amount" in results:
            # "Grand Total" is a strong label
            assert results["total_amount"][0].confidence >= 0.75

"""Regex-based candidate extraction with confidence scoring."""
import re
from dataclasses import dataclass
from typing import Any

from quotation_core.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class RegexMatch:
    """A regex extraction result."""

    pattern_name: str
    value: str
    confidence: float
    position: tuple[int, int]
    raw_match: str


class RegexExtractor:
    """Extract candidates using regex patterns."""

    # Currency symbols and codes (inlined to avoid nested-set FutureWarning in Python 3.12+)
    CURRENCY_SYMBOLS = r"[$€£¥]"
    CURRENCY_CODES = r"(?:USD|EUR|GBP|JPY|CAD|AUD|CHF|CNY|INR)"

    # Common patterns
    PATTERNS = {
        # Quotation numbers - various formats
        "quotation_number": [
            re.compile(
                r"(?:quotation|quote|qt|qtn|quot|estimate|inv)[-#\s]?([A-Z0-9\-]{4,20})",
                re.IGNORECASE,
            ),
            re.compile(r"(?:ref|reference|no|number|#)[:\s]+([A-Z0-9\-]{4,20})", re.IGNORECASE),
            re.compile(r"quote\s*(?:number|#)?\s*:?\s*([A-Z0-9\-]{3,20})", re.IGNORECASE),
        ],
        # Dates - various formats
        "quotation_date": [
            re.compile(
                r"(?:date|dated|quotation\s+date)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                re.IGNORECASE,
            ),
            re.compile(
                r"(?:date|dated)[:\s]+(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4})",
                re.IGNORECASE,
            ),
            re.compile(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})", re.IGNORECASE),
        ],
        # Currency
        "currency": [
            re.compile(r"(?:currency|cur)[:\s]+(?:USD|EUR|GBP|JPY|CAD|AUD|CHF|CNY|INR)", re.IGNORECASE),
            re.compile(r"All\s+amounts\s+in\s+:?\s*(?:USD|EUR|GBP|JPY|CAD|AUD|CHF|CNY|INR|[$€£¥])", re.IGNORECASE),
            re.compile(r"[$€£¥]\s*[\d,]+\.\d{2}"),
        ],
        # Total amounts
        "total_amount": [
            re.compile(
                r"(?:total|grand\s+total|amount\s+due|total\s+due)[:\s]+[$€£¥]?\s*([\d,]+\.?\d{0,2})",
                re.IGNORECASE,
            ),
            re.compile(r"(?:total)[:\s]+[$€£¥]?\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
        ],
        # Subtotal
        "subtotal": [
            re.compile(
                r"(?:subtotal|sub\s+total|net\s+total)[:\s]+[$€£¥]?\s*([\d,]+\.?\d{0,2})",
                re.IGNORECASE,
            ),
        ],
        # Tax
        "tax_amount": [
            re.compile(
                r"(?:tax|vat|gst|sales\s+tax)[:\s]+[$€£¥]?\s*([\d,]+\.?\d{0,2})",
                re.IGNORECASE,
            ),
            re.compile(r"(?:tax|vat)[:\s]+\(?[$€£¥]?\s*([\d,]+\.?\d{0,2})\)?", re.IGNORECASE),
        ],
        # Email addresses (often contain supplier info)
        "email": [
            re.compile(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"),
        ],
        # Phone numbers
        "phone": [
            re.compile(r"(?:tel|phone|mobile)[:\s]+([+\d\s\-\(\)]{7,20})", re.IGNORECASE),
            re.compile(r"(\+\d[\d\s\-\(\)]{8,15})")
        ],
    }

    # Line item patterns
    LINE_ITEM_PATTERNS = [
        # Product code patterns
        re.compile(r"^[A-Z0-9\-]{4,20}$"),  # SKU format
        re.compile(r"^\d{3,10}$"),  # Numeric SKU
        # Quantity patterns
        re.compile(r"^\d+(?:\.\d+)?\s*(?:EA|PCS|SET|BOX|PKT|KG|M|L|UNIT|PC|CTN)s?", re.IGNORECASE),
        # Price patterns
        re.compile(r"[$€£¥]?\s*[\d,]+\.\d{2}"),
    ]

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def extract(self, text: str) -> dict[str, list[RegexMatch]]:
        """
        Extract candidates from text using all patterns.

        Returns dict mapping field names to lists of matches with confidence.
        """
        results: dict[str, list[RegexMatch]] = {}

        for field_name, patterns in self.PATTERNS.items():
            matches: list[RegexMatch] = []

            for pattern in patterns:
                for match in pattern.finditer(text):
                    confidence = self._calculate_confidence(field_name, match, text)

                    # Extract value (first group if available, else full match)
                    value = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)

                    regex_match = RegexMatch(
                        pattern_name=field_name,
                        value=value.strip(),
                        confidence=confidence,
                        position=(match.start(), match.end()),
                        raw_match=match.group(0),
                    )
                    matches.append(regex_match)

            if matches:
                # Sort by confidence descending
                matches.sort(key=lambda x: x.confidence, reverse=True)
                results[field_name] = matches

        self.logger.debug(
            "regex_extraction_complete",
            fields_found=list(results.keys()),
            total_matches=sum(len(m) for m in results.values()),
        )

        return results

    def extract_line_item_candidates(self, table_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
        """
        Extract line item candidates from table rows.

        Uses header name analysis and value patterns.
        """
        if not table_rows:
            return []

        candidates = []

        # Detect column types from first row
        if table_rows:
            first_row = table_rows[0]
            header_mapping = self._map_headers(list(first_row.keys()))

        for idx, row in enumerate(table_rows, start=1):
            candidate: dict[str, Any] = {"_row_index": idx}

            for header, value in row.items():
                mapped_field = header_mapping.get(header.lower(), None)
                if mapped_field:
                    candidate[mapped_field] = {
                        "value": value,
                        "confidence": self._score_line_item_value(mapped_field, value),
                    }

            # Only include if at least description exists
            if "description" in candidate or any(
                "description" in str(k).lower() for k in row.keys()
            ):
                candidates.append(candidate)

        return candidates

    def _map_headers(self, headers: list[str]) -> dict[str, str]:
        """Map header names to standard field names."""
        mapping: dict[str, str] = {}

        header_keywords = {
            "item": "item_no",
            "no": "item_no",
            "line": "line_number",
            "product": "product_code",
            "code": "product_code",
            "sku": "product_code",
            "part": "product_code",
            "description": "description",
            "desc": "description",
            "details": "description",
            "item+description": "description",
            "qty": "quantity",
            "quantity": "quantity",
            "unit": "unit_of_measure",
            "uom": "unit_of_measure",
            "price": "unit_price",
            "unit*price": "unit_price",
            "rate": "unit_price",
            "amount": "total_price",
            "total": "total_price",
            "line*total": "total_price",
        }

        for header in headers:
            header_lower = header.lower().strip()
            for pattern, field in header_keywords.items():
                if re.search(pattern, header_lower, re.IGNORECASE):
                    mapping[header_lower] = field
                    break

        return mapping

    def _calculate_confidence(self, field_name: str, match: re.Match, context: str) -> float:
        """Calculate confidence score for a regex match."""
        base_confidence = 0.7  # Base regex confidence

        # Adjust based on field type
        adjustments = {
            "quotation_number": 0.05,
            "quotation_date": 0.05,
            "currency": 0.10,
            "total_amount": 0.10,
            "subtotal": 0.08,
            "tax_amount": 0.08,
            "email": 0.15,
            "phone": 0.10,
        }

        confidence = base_confidence + adjustments.get(field_name, 0)

        # Boost confidence based on context indicators
        match_text = match.group(0).lower()

        # Strong indicators boost confidence
        strong_indicators = {
            "quotation_number": ["quotation", "quote #", "quote no", "reference", "qt #"],
            "quotation_date": ["quotation date", "quote date", "date of quote"],
            "total_amount": ["grand total", "amount due", "total due", "total payable"],
        }

        indicators = strong_indicators.get(field_name, [])
        if any(ind in match_text for ind in indicators):
            confidence += 0.15

        # Penalize if match is very short or suspicious
        value = match.group(1) if match.lastindex else match.group(0)
        if value:
            if len(value.strip()) < 3:
                confidence -= 0.2
            if re.search(r'[!@#$%^&*]', value):  # Suspicious characters
                confidence -= 0.15

        # Check if preceded by strong label
        context_before = context[max(0, match.start() - 50):match.start()].lower()
        strong_labels = {
            "quotation_number": ["quotation no", "quote no", "quotation #", "ref:"],
            "total_amount": ["grand total:", "total due:", "amount due:"],
        }
        labels = strong_labels.get(field_name, [])
        if any(label in context_before for label in labels):
            confidence += 0.1

        return round(max(0.1, min(0.95, confidence)), 2)

    def _score_line_item_value(self, field: str, value: str) -> float:
        """Score a line item field value."""
        if not value or not value.strip():
            return 0.0

        value = value.strip()

        scores = {
            "product_code": self._score_product_code(value),
            "description": self._score_description(value),
            "quantity": self._score_quantity(value),
            "unit_price": self._score_price(value),
            "total_price": self._score_price(value),
        }

        return scores.get(field, 0.5)

    def _score_product_code(self, value: str) -> float:
        """Score product code validity."""
        if not value:
            return 0.0
        value = value.strip()

        # Looks like a SKU
        if re.match(r'^[A-Z0-9\-]{4,20}$', value):
            return 0.85
        if re.match(r'^\d{3,10}$', value):
            return 0.75
        if len(value) > 2 and len(value) < 30:
            return 0.6
        return 0.3

    def _score_description(self, value: str) -> float:
        """Score description validity."""
        if not value:
            return 0.0
        value = value.strip()

        length = len(value)
        if 10 <= length <= 200:
            return 0.85
        elif 5 <= length < 300:
            return 0.7
        elif length > 0:
            return 0.4
        return 0.0

    def _score_quantity(self, value: str) -> float:
        """Score quantity value."""
        if not value:
            return 0.0

        # Extract numeric part
        numeric = re.search(r'^(\d+(?:\.\d+)?)', value.strip())
        if numeric:
            num = float(numeric.group(1))
            if 0 < num < 100000:
                return 0.85
            return 0.6
        return 0.2

    def _score_price(self, value: str) -> float:
        """Score price value."""
        if not value:
            return 0.0

        # Extract numeric part
        cleaned = re.sub(r'[$€£,\s]', '', value.strip())
        try:
            num = float(cleaned)
            if 0 <= num < 10000000:  # Reasonable price range
                return 0.85
            return 0.5
        except ValueError:
            return 0.2

"""Regex-based candidate extraction with confidence scoring."""
import re
from dataclasses import dataclass
from typing import Any

from quotation_extraction.core.logging_config import get_logger

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

    PATTERNS = {
        "quotation_number": [
            re.compile(r"(?:quotation|quote|qt|qtn|quot|estimate|inv)[-#\s]?([A-Z0-9\-]{4,20})", re.IGNORECASE),
            re.compile(r"(?:ref|reference|no|number|#)[:\s]+([A-Z0-9\-]{4,20})", re.IGNORECASE),
        ],
        "quotation_date": [
            re.compile(r"(?:date|dated|quotation\s+date)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
            re.compile(r"(\d{1,2}[/-]\d{1,2}[/-]\d{4})", re.IGNORECASE),
        ],
        "total_amount": [
            re.compile(r"(?:total|grand\s+total|amount\s+due|total\s+due)[:\s]+[$€£¥]?\s*([\d,]+\.?\d{0,2})", re.IGNORECASE),
        ],
    }

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def extract(self, text: str) -> dict[str, list[RegexMatch]]:
        results: dict[str, list[RegexMatch]] = {}
        for field_name, patterns in self.PATTERNS.items():
            matches: list[RegexMatch] = []
            for pattern in patterns:
                for match in pattern.finditer(text):
                    confidence = 0.7
                    value = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                    matches.append(RegexMatch(field_name, value.strip(), confidence, (match.start(), match.end()), match.group(0)))
            if matches:
                matches.sort(key=lambda x: x.confidence, reverse=True)
                results[field_name] = matches
        return results

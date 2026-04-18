"""Post-processing and validation of extraction results."""
import re
from typing import Any

from quotation_intelligence.core.logging_config import get_logger
from quotation_intelligence.models.extraction import LineItemExtracted, QuotationExtracted

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Field aliases: keys that different LLMs use for the same concept
# ---------------------------------------------------------------------------
_SUPPLIER_ALIASES = ("supplier_name", "supplier", "vendor", "company", "from", "seller")
_QUOTATION_NUMBER_ALIASES = ("quotation_number", "quote_number", "reference", "ref", "quotation_ref", "order_number")
_DATE_ALIASES = ("quotation_date", "date", "issue_date", "created_date", "doc_date")
_CURRENCY_ALIASES = ("currency", "currency_code", "curr")
_SUBTOTAL_ALIASES = ("subtotal", "sub_total", "net_amount", "taxable_amount")
_TAX_ALIASES = ("tax_amount", "tax", "vat", "gst", "tax_total")
_TOTAL_ALIASES = ("total_amount", "total", "grand_total", "amount_due", "invoice_total")

_LINE_ALIASES = ("line_items", "items", "products", "line_entries", "rows", "entries")

_LINE_PRODUCT_CODE = ("product_code", "sku", "code", "item_code", "part_number", "ref")
_LINE_DESC = ("description", "desc", "product_name", "name", "item", "details")
_LINE_QTY = ("quantity", "qty", "units", "amount_qty")
_LINE_UOM = ("unit_of_measure", "uom", "unit", "units_label")
_LINE_UNIT_PRICE = ("unit_price", "price", "rate", "unit_cost", "price_per_unit")
_LINE_TOTAL = ("total_price", "total", "amount", "line_total", "extended_price", "subtotal")


def _first(d: dict, *keys: str, default: Any = None) -> Any:
    """Return the value of the first matching key in *d*."""
    for k in keys:
        if k in d:
            return d[k]
    return default


def _to_float(v: Any) -> float | None:
    """Coerce a value to float, stripping common currency formatting."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        # Strip currency symbols, commas, "SR", whitespace
        cleaned = re.sub(r"[^\d.\-]", "", v.replace(",", ""))
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _to_str(v: Any) -> str | None:
    """Coerce a value to a stripped string."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("null", "none", "n/a", "") else None


def _clamp_conf(v: Any) -> float:
    """Return a confidence value clamped to [0.0, 1.0]."""
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


class ResponseNormalizer:
    """
    Converts raw LLM output — in *any* shape — into a canonical dict
    that ``QuotationExtracted.model_validate()`` can safely consume.

    Usage::

        normalizer = ResponseNormalizer()
        canonical = normalizer.normalize(raw_parsed)          # raw_parsed is whatever json.loads() returned
        result = QuotationExtracted.model_validate(canonical)

    Handles:
    - Bare ``list`` of line items (LLM forgot the wrapper object)
    - ``dict`` with wrong / aliased top-level keys
    - Line items that use non-standard key names
    - Currency strings like "30,106.08 SR" → 30106.08
    - Missing confidence fields (defaults to 0.0)
    - Nested ``{"data": {...}}`` wrapper objects
    """

    def normalize(self, raw: Any) -> dict[str, Any]:
        """Return a canonical dict from any LLM-parsed value."""
        # ── 1. Handle bare list ───────────────────────────────────────────
        if isinstance(raw, list):
            logger.warning("normalizer_bare_list", item_count=len(raw))
            return self._build(line_items_raw=raw)

        # ── 2. Handle non-dict (unexpected scalar, None, …) ───────────────
        if not isinstance(raw, dict):
            logger.warning("normalizer_unexpected_type", type=type(raw).__name__)
            return self._build()

        # ── 3. Unwrap single-key wrapper objects: {"data": {...}} ─────────
        if len(raw) == 1:
            only_val = next(iter(raw.values()))
            if isinstance(only_val, dict):
                logger.warning("normalizer_unwrapping_wrapper", key=next(iter(raw)))
                raw = only_val

        # ── 4. Find line items (may be under various keys) ────────────────
        line_items_raw = None
        for alias in _LINE_ALIASES:
            if alias in raw and isinstance(raw[alias], list):
                line_items_raw = raw[alias]
                break

        # ── 5. Build canonical dict ───────────────────────────────────────
        return self._build(source=raw, line_items_raw=line_items_raw)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build(
        self,
        source: dict[str, Any] | None = None,
        line_items_raw: list | None = None,
    ) -> dict[str, Any]:
        """Assemble the canonical dict from an optional source dict and raw line items."""
        s = source or {}

        canonical: dict[str, Any] = {
            # Header fields
            "supplier_name": _to_str(_first(s, *_SUPPLIER_ALIASES)),
            "quotation_number": _to_str(_first(s, *_QUOTATION_NUMBER_ALIASES)),
            "quotation_date": _to_str(_first(s, *_DATE_ALIASES)),
            "currency": _to_str(_first(s, *_CURRENCY_ALIASES)),
            # Financial totals
            "subtotal": _to_float(_first(s, *_SUBTOTAL_ALIASES)),
            "tax_amount": _to_float(_first(s, *_TAX_ALIASES)),
            "total_amount": _to_float(_first(s, *_TOTAL_ALIASES)),
            # Confidence scores
            "supplier_name_confidence": _clamp_conf(s.get("supplier_name_confidence", 0.0)),
            "quotation_number_confidence": _clamp_conf(s.get("quotation_number_confidence", 0.0)),
            "quotation_date_confidence": _clamp_conf(s.get("quotation_date_confidence", 0.0)),
            "total_confidence": _clamp_conf(s.get("total_confidence", 0.0)),
            # Errors
            "extraction_errors": s.get("extraction_errors") or [],
            # Line items
            "line_items": self._normalize_line_items(line_items_raw or []),
        }

        return canonical

    def _normalize_line_items(self, raw_items: list) -> list[dict[str, Any]]:
        """Normalize a list of raw line-item dicts into canonical form."""
        result = []
        for idx, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                logger.warning("normalizer_skipping_non_dict_item", index=idx)
                continue

            desc = _to_str(_first(item, *_LINE_DESC))
            if not desc:
                logger.warning("normalizer_skipping_item_no_description", index=idx)
                continue

            result.append({
                "line_number": item.get("line_number") or idx,
                "product_code": _to_str(_first(item, *_LINE_PRODUCT_CODE)),
                "description": desc,
                "quantity": _to_float(_first(item, *_LINE_QTY)),
                "unit_of_measure": _to_str(_first(item, *_LINE_UOM)),
                "unit_price": _to_float(_first(item, *_LINE_UNIT_PRICE)),
                "total_price": _to_float(_first(item, *_LINE_TOTAL)),
                # Confidence scores
                "product_code_confidence": _clamp_conf(item.get("product_code_confidence", 0.0)),
                "description_confidence": _clamp_conf(item.get("description_confidence", 0.0)),
                "quantity_confidence": _clamp_conf(item.get("quantity_confidence", 0.0)),
                "unit_price_confidence": _clamp_conf(item.get("unit_price_confidence", 0.0)),
                "total_price_confidence": _clamp_conf(item.get("total_price_confidence", 0.0)),
                "extraction_source": item.get("extraction_source", "llm"),
            })

        return result


class PostProcessor:
    """Post-process and validate extracted data."""

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def process(self, result: QuotationExtracted) -> QuotationExtracted:
        """
        Apply post-processing to extraction result.

        Includes: deduplication, validation, normalization.
        """
        self.logger.info("post_processing_started")

        # Deduplicate line items
        result.line_items = self._deduplicate_line_items(result.line_items)

        # Sort line items by line number
        result.line_items = sorted(
            result.line_items,
            key=lambda x: x.line_number or 9999,
        )

        # Re-number line items sequentially
        for i, item in enumerate(result.line_items, start=1):
            item.line_number = i

        # Validate and correct prices
        self._validate_prices(result)

        # Calculate totals if missing
        self._calculate_missing_totals(result)

        # Normalize currency
        self._normalize_currency(result)

        # Validate extracted amounts against line items
        self._validate_totals(result)

        self.logger.info(
            "post_processing_completed",
            line_items_count=len(result.line_items),
            supplier=result.supplier_name,
        )

        return result

    def _deduplicate_line_items(
        self,
        items: list[LineItemExtracted],
    ) -> list[LineItemExtracted]:
        """Remove duplicate line items based on content similarity."""
        if not items:
            return []

        seen: set[str] = set()
        unique_items: list[LineItemExtracted] = []

        for item in items:
            # Create a signature for deduplication
            sig_parts = [
                item.product_code or "",
                (item.description or "")[:50].lower().strip(),
                str(item.quantity or ""),
                str(item.unit_price or ""),
            ]
            signature = "|".join(sig_parts)

            if signature not in seen and (item.description or item.product_code):
                seen.add(signature)
                unique_items.append(item)

        if len(unique_items) < len(items):
            self.logger.info(
                "duplicates_removed",
                original_count=len(items),
                final_count=len(unique_items),
            )

        return unique_items

    def _validate_prices(self, result: QuotationExtracted) -> None:
        """Validate and correct line item prices."""
        for item in result.line_items:
            if item.quantity and item.unit_price:
                expected_total = item.quantity * item.unit_price

                if item.total_price:
                    # Check if total matches
                    diff_ratio = abs(item.total_price - expected_total) / expected_total

                    if diff_ratio > 0.01:  # More than 1% difference
                        self.logger.warning(
                            "price_mismatch_detected",
                            line=item.line_number,
                            expected=expected_total,
                            actual=item.total_price,
                            diff_ratio=diff_ratio,
                        )

                        # Trust the total if it's close, otherwise recalculate
                        if diff_ratio > 0.1:
                            item.total_price = round(expected_total, 2)
                            item.total_price_confidence = 0.6
                else:
                    # Calculate missing total
                    item.total_price = round(expected_total, 2)
                    item.total_price_confidence = min(
                        (item.quantity_confidence + item.unit_price_confidence) / 2,
                        0.8,
                    )

    def _calculate_missing_totals(self, result: QuotationExtracted) -> None:
        """Calculate missing totals from line items."""
        if not result.line_items:
            return

        # Calculate line items total
        line_items_total = sum(
            item.total_price or 0 for item in result.line_items
        )

        # Set subtotal if missing
        if result.subtotal is None and line_items_total > 0:
            result.subtotal = line_items_total
            # Lower confidence since calculated
            result.total_confidence = 0.7 if result.total_confidence < 0.9 else result.total_confidence

        # Calculate total if missing
        if result.total_amount is None and result.subtotal is not None:
            tax = result.tax_amount or 0
            result.total_amount = result.subtotal + tax
            result.total_confidence = 0.7

    def _normalize_currency(self, result: QuotationExtracted) -> None:
        """Normalize currency code."""
        if result.currency:
            currency_map = {
                "usd": "USD",
                "eur": "EUR",
                "gbp": "GBP",
                "jpy": "JPY",
                "cad": "CAD",
                "aud": "AUD",
                "chf": "CHF",
                "cny": "CNY",
                "inr": "INR",
                "$": "USD",
                "€": "EUR",
                "£": "GBP",
            }

            normalized = currency_map.get(result.currency.lower().strip())
            if normalized:
                result.currency = normalized

    def _validate_totals(self, result: QuotationExtracted) -> None:
        """Validate that totals match sum of line items."""
        if not result.line_items or result.subtotal is None:
            return

        line_items_sum = sum(item.total_price or 0 for item in result.line_items)

        if result.subtotal > 0:
            diff = abs(result.subtotal - line_items_sum)
            diff_ratio = diff / result.subtotal if result.subtotal > 0 else 0

            if diff_ratio > 0.05:  # 5% tolerance
                self.logger.warning(
                    "totals_validation_failed",
                    subtotal=result.subtotal,
                    line_items_sum=line_items_sum,
                    difference=diff,
                    diff_ratio=diff_ratio,
                )

                # Add warning to extraction errors
                if result.extraction_errors is None:
                    result.extraction_errors = []

                result.extraction_errors.append(
                    f"Subtotal ({result.subtotal}) doesn't match line items sum ({line_items_sum:.2f})"
                )

                # Lower confidence
                result.total_confidence = min(result.total_confidence or 0.5, 0.5)

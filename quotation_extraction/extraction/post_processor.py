"""Post-processing and validation of extraction results."""
import re
from typing import Any

from quotation_extraction.core.logging_config import get_logger
from quotation_extraction.models.extraction import LineItemExtracted, QuotationExtracted

logger = get_logger(__name__)

# Field aliases for response normalization
_SUPPLIER_ALIASES = ("supplier_name", "vendor", "company", "from", "seller")
_QUOTATION_NUMBER_ALIASES = ("quotation_number", "quote_number", "reference", "ref", "quotation_ref")
_DATE_ALIASES = ("quotation_date", "date", "issue_date", "doc_date")
_CURRENCY_ALIASES = ("currency", "currency_code", "curr")
_SUBTOTAL_ALIASES = ("subtotal", "sub_total", "net_amount")
_TAX_ALIASES = ("tax_amount", "tax", "vat")
_TOTAL_ALIASES = ("total_amount", "total", "grand_total")

_LINE_ALIASES = ("line_items", "items", "products", "rows")
_LINE_PRODUCT_CODE = ("product_code", "sku", "code", "item_code")
_LINE_ITEM_NUMBER = ("item_number", "item_no", "pos")
_LINE_DESC = ("description", "desc", "product_name")
_LINE_QTY = ("quantity", "qty", "units")
_LINE_UOM = ("unit_of_measure", "uom", "unit")
_LINE_UNIT_PRICE = ("unit_price", "price", "rate")
_LINE_TOTAL = ("total_price", "total", "amount")


def _first(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if k in d: return d[k]
    return default

def _to_float(v: Any) -> float | None:
    if v is None: return None
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        try: return float(re.sub(r"[^\d.\-]", "", v.replace(",", "")))
        except ValueError: return None
    return None

def _to_str(v: Any) -> str | None:
    if v is None: return None
    s = str(v).strip()
    return s if s and s.lower() not in ("null", "none", "n/a", "") else None

def _clamp_conf(v: Any) -> float:
    try: return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError): return 0.0


class ResponseNormalizer:
    """Converts raw LLM output into a canonical dict."""
    def normalize(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, list):
            return self._build(line_items_raw=raw)
        if not isinstance(raw, dict):
            return self._build()
        if len(raw) == 1 and isinstance(next(iter(raw.values())), dict):
            raw = next(iter(raw.values()))

        line_items_raw = None
        for alias in _LINE_ALIASES:
            if alias in raw and isinstance(raw[alias], list):
                line_items_raw = raw[alias]
                break

        return self._build(source=raw, line_items_raw=line_items_raw)

    def _build(self, source: dict[str, Any] | None = None, line_items_raw: list | None = None) -> dict[str, Any]:
        s = source or {}
        supplier_name = _to_str(_first(s, *_SUPPLIER_ALIASES)) or _to_str((s.get("supplier") or {}).get("company"))
        total_amount = _to_float(_first(s, *_TOTAL_ALIASES)) or _to_float((s.get("totals") or {}).get("grand_total_eur"))

        return {
            "supplier_name": supplier_name,
            "quotation_number": _to_str(_first(s, *_QUOTATION_NUMBER_ALIASES)),
            "customer_number": _to_str(s.get("customer_number")),
            "quotation_date": _to_str(_first(s, *_DATE_ALIASES)),
            "currency": _to_str(_first(s, *_CURRENCY_ALIASES)),
            "customer": s.get("customer") if isinstance(s.get("customer"), dict) else None,
            "supplier": s.get("supplier") if isinstance(s.get("supplier"), dict) else None,
            "project": s.get("project") if isinstance(s.get("project"), dict) else None,
            "price_validity": _to_str(s.get("price_validity")),
            "delivery_terms": _to_str(s.get("delivery_terms")),
            "payment_terms": _to_str(s.get("payment_terms")),
            "subtotal": _to_float(_first(s, *_SUBTOTAL_ALIASES)),
            "tax_amount": _to_float(_first(s, *_TAX_ALIASES)),
            "total_amount": total_amount,
            "totals": s.get("totals") if isinstance(s.get("totals"), dict) else None,
            "supplier_name_confidence": _clamp_conf(s.get("supplier_name_confidence", 0.0)),
            "quotation_number_confidence": _clamp_conf(s.get("quotation_number_confidence", 0.0)),
            "quotation_date_confidence": _clamp_conf(s.get("quotation_date_confidence", 0.0)),
            "total_confidence": _clamp_conf(s.get("total_confidence", 0.0)),
            "extraction_errors": s.get("extraction_errors") or [],
            "line_items": self._normalize_line_items(line_items_raw or []),
        }

    def _normalize_line_items(self, raw_items: list) -> list[dict[str, Any]]:
        result = []
        for idx, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict): continue
            desc = _to_str(_first(item, *_LINE_DESC))
            if not desc: continue

            result.append({
                "line_number": item.get("line_number") or idx,
                "item_number": _to_str(_first(item, *_LINE_ITEM_NUMBER)),
                "item_code": _to_str(_first(item, *_LINE_PRODUCT_CODE)),
                "product_code": _to_str(_first(item, *_LINE_PRODUCT_CODE)),
                "item_type": _to_str(item.get("item_type") or item.get("type")),
                "product_name": _to_str(item.get("product_name")),
                "model_number": _to_str(item.get("model_number")),
                "description": desc,
                "specifications": item.get("specifications") if isinstance(item.get("specifications"), dict) else None,
                "quantity": _to_float(_first(item, *_LINE_QTY)),
                "unit_of_measure": _to_str(_first(item, *_LINE_UOM)),
                "unit_price": _to_float(_first(item, *_LINE_UNIT_PRICE)),
                "total_price": _to_float(_first(item, *_LINE_TOTAL)),
                "delivery_weeks": _to_float(item.get("delivery_weeks")),
                "delivery_note": _to_str(item.get("delivery_note")),
                "important_notes": item.get("important_notes") or [],
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
        self.logger.info("post_processing_started")

        result.line_items = self._deduplicate_line_items(result.line_items)
        result.line_items = sorted(result.line_items, key=lambda x: x.line_number or 9999)
        for i, item in enumerate(result.line_items, start=1):
            item.line_number = i

        self._validate_prices(result)
        self._calculate_missing_totals(result)
        self._normalize_currency(result)
        self._validate_totals(result)

        return result

    def _deduplicate_line_items(self, items: list[LineItemExtracted]) -> list[LineItemExtracted]:
        seen: set[str] = set()
        unique_items: list[LineItemExtracted] = []

        for item in items:
            sig = f"{item.product_code}|{str(item.description)[:50]}|{item.quantity}|{item.unit_price}"
            if sig not in seen and (item.description or item.product_code):
                seen.add(sig)
                unique_items.append(item)
        return unique_items

    def _validate_prices(self, result: QuotationExtracted) -> None:
        for item in result.line_items:
            if item.quantity and item.unit_price:
                expected = item.quantity * item.unit_price
                if item.total_price:
                    if abs(item.total_price - expected) / expected > 0.01:
                        if abs(item.total_price - expected) / expected > 0.1:
                            item.total_price = round(expected, 2)
                else:
                    item.total_price = round(expected, 2)

    def _calculate_missing_totals(self, result: QuotationExtracted) -> None:
        if not result.line_items: return
        line_items_total = sum(item.total_price or 0 for item in result.line_items)
        if result.subtotal is None and line_items_total > 0:
            result.subtotal = line_items_total
        if result.total_amount is None and result.subtotal is not None:
            result.total_amount = result.subtotal + (result.tax_amount or 0)

    def _normalize_currency(self, result: QuotationExtracted) -> None:
        if result.currency:
            cmap = {"usd":"USD","eur":"EUR","gbp":"GBP","$":"USD","€":"EUR","£":"GBP"}
            result.currency = cmap.get(result.currency.lower().strip(), result.currency)

    def _validate_totals(self, result: QuotationExtracted) -> None:
        if not result.line_items or result.subtotal is None: return
        line_items_sum = sum(item.total_price or 0 for item in result.line_items)
        if result.subtotal > 0 and abs(result.subtotal - line_items_sum) / result.subtotal > 0.05:
            if result.extraction_errors is None: result.extraction_errors = []
            result.extraction_errors.append(f"Subtotal doesn't match sum of lines")

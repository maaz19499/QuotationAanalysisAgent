"""Pydantic models for LLM extraction output validation.

Enriched schema supporting nested customer, supplier, project, and
per-item specification objects — tailored for lighting / technical
quotations (BEGA, Trilux, etc.) but flexible enough for general use.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Nested sub-models ────────────────────────────────────────────────────────

class CustomerInfo(BaseModel):
    """Customer / buyer details from the quotation header."""

    model_config = ConfigDict(extra="ignore")

    company: str | None = None
    contact_name: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None


class SupplierInfo(BaseModel):
    """Supplier / vendor details from the quotation header."""

    model_config = ConfigDict(extra="ignore")

    company: str | None = None
    contact_person: str | None = None
    email: str | None = None


class ProjectInfo(BaseModel):
    """Project / object reference from the quotation header."""

    model_config = ConfigDict(extra="ignore")

    object_number: str | None = None
    object_name: str | None = None


class ItemSpecifications(BaseModel):
    """Technical specifications for a line item (lighting-focused)."""

    model_config = ConfigDict(extra="ignore")

    led_color_temp_k: float | None = None
    cri: float | None = None
    luminous_flux_lm: float | None = None
    wattage_w: float | None = None
    ip_rating: str | None = None
    dali_version: str | None = None
    dimensions_mm: str | None = None
    color_finish: str | None = None
    material: str | None = None
    service_life_hours: float | None = None


class TotalsInfo(BaseModel):
    """Document-level totals."""

    model_config = ConfigDict(extra="ignore")

    grand_total_eur: float | None = None
    vat_included: bool = False


# ── Line item ────────────────────────────────────────────────────────────────

class LineItemExtracted(BaseModel):
    """Line item extracted by LLM."""

    model_config = ConfigDict(extra="ignore")

    line_number: int | None = Field(None, description="Sequential line number")
    item_number: str | None = Field(None, description="Item number as shown on quotation")
    item_code: str | None = Field(None, description="Product/SKU code")
    product_code: str | None = Field(None, description="Alias for item_code (backward compat)")
    item_type: Literal["main", "alternative", "accessory"] | None = Field(
        None, description="main | alternative | accessory"
    )
    product_name: str | None = Field(None, description="Short product name")
    model_number: str | None = Field(None, description="Model / catalog number")
    description: str = Field(..., description="Product description")
    specifications: ItemSpecifications | None = Field(None, description="Technical specs")
    quantity: float | None = Field(None, description="Quantity")
    unit_of_measure: str | None = Field(None, description="Unit of measure (EA, BOX, etc.)")
    unit_price: float | None = Field(None, description="Price per unit")
    total_price: float | None = Field(None, description="Total price for line")
    delivery_weeks: float | None = Field(None, description="Delivery time in weeks")
    delivery_note: str | None = Field(None, description="Delivery note (e.g. 'stocked')")
    important_notes: list[str] = Field(default_factory=list, description="Important notes for this item")

    # Confidence scores (0.0 - 1.0)
    product_code_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    description_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    quantity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    unit_price_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    total_price_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Source of extraction
    extraction_source: str = Field(default="llm", description="llm, regex, or ocr")

    @field_validator("unit_price", "total_price", "quantity", mode="before")
    @classmethod
    def convert_numeric_strings(cls, v: Any) -> float | None:
        """Convert string numbers to floats."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            # Remove currency symbols and commas
            cleaned = v.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @field_validator("description", "product_code", "item_code", "product_name", "model_number", mode="before")
    @classmethod
    def clean_strings(cls, v: Any) -> str | None:
        """Clean string fields."""
        if v is None:
            return None
        if isinstance(v, str):
            return v.strip()
        return str(v)

    def calculate_overall_confidence(self) -> float:
        """Calculate overall confidence score."""
        scores = [
            self.product_code_confidence or 0,
            self.description_confidence or 0,
            self.quantity_confidence or 0,
            self.unit_price_confidence or 0,
            self.total_price_confidence or 0,
        ]
        weights = [0.15, 0.25, 0.20, 0.20, 0.20]
        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        return round(weighted_sum, 3)


# ── Top-level quotation ─────────────────────────────────────────────────────

class QuotationExtracted(BaseModel):
    """Complete extracted quotation data."""

    model_config = ConfigDict(extra="ignore")

    # Header fields (flat — backward compatible)
    supplier_name: str | None = Field(None, description="Supplier/Vendor name (flat alias)")
    quotation_number: str | None = Field(None, description="Quotation/Quote number")
    customer_number: str | None = Field(None, description="Customer reference number")
    quotation_date: str | None = Field(None, description="Date of quotation (YYYY-MM-DD)")
    currency: str | None = Field(None, description="Currency code (USD, EUR, etc.)")

    # Nested header objects
    customer: CustomerInfo | None = Field(None, description="Customer details")
    supplier: SupplierInfo | None = Field(None, description="Supplier details")
    project: ProjectInfo | None = Field(None, description="Project reference")

    # Terms
    price_validity: str | None = Field(None, description="Price validity period")
    delivery_terms: str | None = Field(None, description="Delivery terms (e.g. DAP, FOB)")
    payment_terms: str | None = Field(None, description="Payment terms")

    # Financial totals (flat — backward compatible)
    subtotal: float | None = Field(None, description="Subtotal before tax")
    tax_amount: float | None = Field(None, description="Tax amount")
    total_amount: float | None = Field(None, description="Total amount")

    # Nested totals
    totals: TotalsInfo | None = Field(None, description="Document-level totals")

    # Confidence scores for header fields
    supplier_name_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    quotation_number_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    quotation_date_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    total_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    # Line items
    line_items: list[LineItemExtracted] = Field(default_factory=list)

    # Extraction metadata
    extraction_errors: list[str] = Field(default_factory=list)
    raw_page_count: int | None = None

    # ── Cost tracking (populated by pipeline) ────────────────────────────
    extraction_cost: dict[str, Any] | None = Field(
        None,
        description="Token usage and cost breakdown per LLM call",
    )

    @field_validator(
        "subtotal",
        "tax_amount",
        "total_amount",
        mode="before",
    )
    @classmethod
    def convert_currency_strings(cls, v: Any) -> float | None:
        """Convert currency strings to floats."""
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            cleaned = v.replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @field_validator("supplier_name", "quotation_number", "quotation_date", "currency")
    @classmethod
    def clean_header_strings(cls, v: str | None) -> str | None:
        """Clean header string fields."""
        if v is None:
            return None
        return v.strip()

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, v: str | None) -> str | None:
        """Normalize currency codes."""
        if v is None:
            return None
        currency_map = {
            "USD": "USD",
            "EUR": "EUR",
            "GBP": "GBP",
            "$": "USD",
            "€": "EUR",
            "£": "GBP",
            "US": "USD",
            "EU": "EUR",
        }
        upper = v.upper().strip()
        return currency_map.get(upper, upper)

    def get_overall_confidence(self) -> float:
        """Get overall confidence for entire extraction."""
        if not self.line_items:
            return 0.0

        header_confidence = (
            (self.supplier_name_confidence or 0) * 0.2
            + (self.quotation_number_confidence or 0) * 0.15
            + (self.quotation_date_confidence or 0) * 0.1
            + (self.total_confidence or 0) * 0.15
        )

        avg_line_confidence = sum(
            item.calculate_overall_confidence() for item in self.line_items
        ) / len(self.line_items)

        line_weight = 0.4
        header_weight = 0.6

        return round(
            header_weight * header_confidence + line_weight * avg_line_confidence,
            3,
        )

    def get_missing_fields(self) -> list[str]:
        """Get list of missing or low-confidence fields."""
        missing = []

        if not self.supplier_name or self.supplier_name_confidence < 0.5:
            missing.append("supplier_name")
        if not self.quotation_number or self.quotation_number_confidence < 0.5:
            missing.append("quotation_number")
        if not self.quotation_date or self.quotation_date_confidence < 0.5:
            missing.append("quotation_date")
        if not self.total_amount or self.total_confidence < 0.5:
            missing.append("total_amount")

        return missing

    def to_export_dict(self) -> dict[str, Any]:
        """Convert to dict suitable for export."""
        return {
            "supplier_name": self.supplier_name,
            "quotation_number": self.quotation_number,
            "customer_number": self.customer_number,
            "quotation_date": self.quotation_date,
            "currency": self.currency,
            "customer": self.customer.model_dump() if self.customer else None,
            "supplier": self.supplier.model_dump() if self.supplier else None,
            "project": self.project.model_dump() if self.project else None,
            "price_validity": self.price_validity,
            "delivery_terms": self.delivery_terms,
            "payment_terms": self.payment_terms,
            "subtotal": self.subtotal,
            "tax_amount": self.tax_amount,
            "total_amount": self.total_amount,
            "totals": self.totals.model_dump() if self.totals else None,
            "line_items": [
                {
                    "line_number": item.line_number,
                    "item_number": item.item_number,
                    "item_code": item.item_code or item.product_code,
                    "item_type": item.item_type,
                    "product_name": item.product_name,
                    "model_number": item.model_number,
                    "description": item.description,
                    "specifications": item.specifications.model_dump() if item.specifications else None,
                    "quantity": item.quantity,
                    "unit_of_measure": item.unit_of_measure,
                    "unit_price": item.unit_price,
                    "total_price": item.total_price,
                    "delivery_weeks": item.delivery_weeks,
                    "delivery_note": item.delivery_note,
                    "important_notes": item.important_notes,
                }
                for item in self.line_items
            ],
            "metadata": {
                "line_item_count": len(self.line_items),
                "extraction_errors": self.extraction_errors,
                "extraction_cost": self.extraction_cost,
            },
        }

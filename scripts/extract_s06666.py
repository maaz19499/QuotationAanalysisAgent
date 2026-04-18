"""
Standalone extraction script for Quotation S06666
==================================================

Tailored to the five challenges of this specific PDF:
  1. Pages all
  2. row_index guard  — explicit prompt instruction to NEVER merge rows with the same SKU
  3. Section tracking — Girls Part 1 / Girls Part 2 / Boys Building captured per row
  4. Arabic handling  — bilingual descriptions are kept; Arabic is placed in a separate field
  5. Post-extraction  — re-sums amount column and checks against expected total 577,713.17 SR

Usage
-----
  # Process ALL pages (default — recommended for unknown PDFs)
  python scripts/extract_s06666.py path/to/S06666.pdf

  # Limit to specific pages to skip known T&C boilerplate
  python scripts/extract_s06666.py path/to/S06666.pdf --pages 1-5

  # Discard Arabic text, write output to a specific path
  python scripts/extract_s06666.py path/to/S06666.pdf --keep-arabic false
  python scripts/extract_s06666.py path/to/S06666.pdf --out results/S06666.json
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Force UTF-8 output on Windows so box-drawing characters, checkmarks, Arabic
# text, etc. all print without UnicodeEncodeError on cp1252 terminals.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Load .env BEFORE importing anything that reads settings ──────────────────
# Find the project root (two levels up from this script)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"

if _ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE, override=False)
    print(f"[env] Loaded {_ENV_FILE}")
else:
    print(f"[warn] .env not found at {_ENV_FILE}")

# ── Now safe to import project modules ───────────────────────────────────────
import pdfplumber  # type: ignore
import litellm     # type: ignore
from litellm import completion  # type: ignore

from quotation_intelligence.core.config import settings

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
EXPECTED_TOTAL_SR = 577_713.17
EXPECTED_TOTAL_TOLERANCE = 1.00   # allow ±1 SR rounding difference

SECTION_KEYWORDS = {
    "Girls Part 1": ["girls part 1", "بنات الجزء الأول"],
    "Girls Part 2": ["girls part 2", "بنات الجزء الثاني"],
    "Boys Building": ["boys building", "مبنى الأولاد"],
}

# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LineItem:
    row_index: int                      # 1-based; preserved even for duplicate SKUs
    section: str | None                 # Girls Part 1 / Girls Part 2 / Boys Building
    product_code: str | None
    description_en: str | None          # English part of bilingual description
    description_ar: str | None          # Arabic part (if keep_arabic=True)
    quantity: float | None
    unit_of_measure: str | None
    unit_price: float | None
    amount: float | None
    confidence: float = 0.0             # 0.0–1.0


@dataclass
class ExtractionResult:
    supplier_name: str | None = None
    quotation_number: str | None = None
    quotation_date: str | None = None
    currency: str | None = None
    total_amount: float | None = None
    line_items: list[LineItem] = field(default_factory=list)
    extraction_errors: list[str] = field(default_factory=list)
    # Validation output (filled by post_validate)
    computed_total: float | None = None
    total_matches: bool | None = None
    missing_rows_suspected: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Step 1: PDF → text (pages 1–5 only)
# ─────────────────────────────────────────────────────────────────────────────
def extract_text_pages(
    pdf_path: Path,
    page_range: tuple[int, int] | None = None,
) -> tuple[str, list[str]]:
    """
    Extract text from `page_range` (inclusive, 1-based).
    Pass None to process ALL pages — the default and recommended setting
    when the PDF structure is unknown.
    Returns (full_combined_text, list_of_per_page_texts).
    """
    per_page: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)

        if page_range is None:
            start_page, end_page = 1, total
            print(f"[pdf] {total} pages found — processing ALL pages")
        else:
            start_page, end_page = page_range
            end_page = min(end_page, total)
            skipped = total - end_page
            note = f" ({skipped} page(s) skipped)" if skipped else ""
            print(f"[pdf] {total} pages found — using pages {start_page}–{end_page}{note}")

        for i in range(start_page - 1, end_page):   # pdfplumber is 0-indexed
            page = pdf.pages[i]
            per_page.append(page.extract_text() or "")

    combined = "\n\n--- PAGE BREAK ---\n\n".join(
        f"=== Page {start_page + i} ===\n{txt}"
        for i, txt in enumerate(per_page)
    )
    return combined, per_page


# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Detect active section for each text block
# ─────────────────────────────────────────────────────────────────────────────
def detect_current_section(text_block: str) -> str | None:
    lower = text_block.lower()
    for section_name, keywords in SECTION_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            return section_name
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Build the LLM prompt
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a precise document extraction engine specialised in Arabic/English bilingual quotations.
Your output MUST be valid JSON — no markdown, no prose, no comments, no trailing commas."""

def build_user_prompt(text: str, keep_arabic: bool) -> str:
    arabic_instruction = (
        'For each line item, split the description into two parts: "description_en" '
        '(English text only) and "description_ar" (Arabic text only). '
        'If only one language is present, put it in description_en and set description_ar to null.'
        if keep_arabic else
        'Extract only the English description into "description_en". Set "description_ar" to null.'
    )

    return f"""Extract ALL line items from this quotation text. Apply these rules strictly:

CRITICAL RULES:
1. **row_index**: Assign a unique sequential integer starting from 1 to EVERY row, even if the same
   product_code appears multiple times. NEVER merge rows that share a product_code — they represent
   separate purchase lines with different quantities.
2. **section**: Each row belongs to one of three sections visible in the document:
   "Girls Part 1", "Girls Part 2", or "Boys Building". Track which section is active
   and assign it to every row. If a row's section is ambiguous mark it null.
3. **Arabic/English split**: {arabic_instruction}
4. **Numbers**: Extract quantity, unit_price, and amount as plain numbers (no commas, no currency symbols).
5. **Completeness**: Return EVERY data row. Do NOT skip rows that appear to be subtotals of a section —
   but DO skip the grand total line.

RESPONSE FORMAT — return ONLY this JSON object:
{{
  "supplier_name": "string or null",
  "quotation_number": "string or null",
  "quotation_date": "string or null",
  "currency": "SAR/USD/EUR or null",
  "total_amount": number or null,
  "line_items": [
    {{
      "row_index": 1,
      "section": "Girls Part 1 | Girls Part 2 | Boys Building | null",
      "product_code": "string or null",
      "description_en": "English description",
      "description_ar": "Arabic description or null",
      "quantity": number or null,
      "unit_of_measure": "string or null",
      "unit_price": number or null,
      "amount": number or null,
      "confidence": 0.0
    }}
  ],
  "extraction_errors": []
}}

TEXT TO EXTRACT:
---BEGIN---
{text}
---END---
"""


# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Call LLM via LiteLLM
# ─────────────────────────────────────────────────────────────────────────────

# Correction prompt used when the model ignores the JSON-only instruction
_JSON_CORRECTION_PROMPT = (
    "Your previous response was plain text or a summary. "
    "That is WRONG. You MUST output ONLY the raw JSON object described in the instructions — "
    "no prose, no markdown, no explanation. Start your response with '{' and end with '}'. "
    "Output the JSON now:"
)


def _save_raw_response(raw: str, pdf_stem: str, attempt: int) -> Path:
    """Save raw LLM output to disk so it can always be inspected."""
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{pdf_stem}_llm_raw_attempt{attempt}.txt"
    out_path.write_text(raw, encoding="utf-8")
    print(f"[llm] Raw response saved -> {out_path}")
    return out_path


def call_llm(
    prompt_text: str,
    keep_arabic: bool,
    pdf_stem: str = "doc",
) -> dict[str, Any]:
    model = settings.llm_model
    api_base = settings.llm_api_base or None
    timeout = settings.llm_timeout_seconds
    max_tokens = settings.llm_max_tokens
    temperature = settings.llm_temperature

    if settings.llm_api_key:
        litellm.api_key = settings.llm_api_key
    litellm.suppress_debug_info = True

    base_kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    if api_base:
        base_kwargs["api_base"] = api_base

    # ── Attempt 1: normal extraction prompt ──────────────────────────────────
    print(f"[llm] Calling {model} (timeout={timeout}s, max_tokens={max_tokens}) …")
    t0 = time.time()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(prompt_text, keep_arabic)},
    ]
    response = completion(messages=messages, **base_kwargs)
    elapsed = time.time() - t0
    print(f"[llm] Response received in {elapsed:.1f}s")

    raw = response.choices[0].message.content or ""
    _save_raw_response(raw, pdf_stem, attempt=1)

    try:
        return _parse_json(raw)
    except ValueError as first_err:
        print(f"[llm] Attempt 1 did not return valid JSON — retrying with correction prompt …")
        print(f"      Reason: {first_err}")

    # ── Attempt 2: correction prompt ─────────────────────────────────────────
    messages.append({"role": "assistant", "content": raw})
    messages.append({"role": "user", "content": _JSON_CORRECTION_PROMPT})

    t0 = time.time()
    response2 = completion(messages=messages, **base_kwargs)
    elapsed2 = time.time() - t0
    print(f"[llm] Correction response received in {elapsed2:.1f}s")

    raw2 = response2.choices[0].message.content or ""
    _save_raw_response(raw2, pdf_stem, attempt=2)

    return _parse_json(raw2)  # Let exception propagate if still bad


def _parse_json(raw: str) -> dict[str, Any]:
    """Strip markdown fences and parse JSON."""
    content = raw.strip()
    if not content:
        raise ValueError("LLM returned an empty response")

    if "```json" in content:
        content = content[content.find("```json") + 7 : content.rfind("```")].strip()
    elif content.startswith("```"):
        content = content[content.find("\n") + 1 : content.rfind("```")].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start == -1 or end == -1:
            # Show a preview of what the model said to aid debugging
            preview = raw[:300].replace("\n", " ")
            raise ValueError(
                f"No JSON object found in LLM response.\n"
                f"Preview: {preview!r}"
            )
        return json.loads(content[start : end + 1])


# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Parse LLM output → typed ExtractionResult
# ─────────────────────────────────────────────────────────────────────────────
def parse_llm_output(data: dict[str, Any]) -> ExtractionResult:
    result = ExtractionResult(
        supplier_name=data.get("supplier_name"),
        quotation_number=data.get("quotation_number"),
        quotation_date=data.get("quotation_date"),
        currency=data.get("currency"),
        total_amount=_to_float(data.get("total_amount")),
        extraction_errors=data.get("extraction_errors") or [],
    )

    seen_row_indices: set[int] = set()
    raw_items: list[dict] = data.get("line_items") or []

    for i, item in enumerate(raw_items, start=1):
        # Guarantee row_index uniqueness even if LLM messed up
        row_idx = item.get("row_index")
        if row_idx is None or row_idx in seen_row_indices:
            # Assign a new one
            row_idx = max(seen_row_indices, default=0) + 1
            result.extraction_errors.append(
                f"row_index missing/duplicate at position {i}; auto-assigned {row_idx}"
            )
        seen_row_indices.add(row_idx)

        li = LineItem(
            row_index=row_idx,
            section=item.get("section"),
            product_code=item.get("product_code"),
            description_en=item.get("description_en"),
            description_ar=item.get("description_ar"),
            quantity=_to_float(item.get("quantity")),
            unit_of_measure=item.get("unit_of_measure"),
            unit_price=_to_float(item.get("unit_price")),
            amount=_to_float(item.get("amount")),
            confidence=float(item.get("confidence") or 0.0),
        )
        result.line_items.append(li)

    return result


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = v.replace(",", "").replace("SR", "").replace("SAR", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Post-extraction validation
# ─────────────────────────────────────────────────────────────────────────────
def post_validate(result: ExtractionResult, expected_total: float, tolerance: float) -> None:
    """
    Re-sum the `amount` column and compare against the known grand total.
    Flags missing/merged rows if the delta is too large.
    """
    amounts = [li.amount for li in result.line_items if li.amount is not None]
    computed = round(sum(amounts), 2)
    result.computed_total = computed

    delta = abs(computed - expected_total)
    result.total_matches = delta <= tolerance

    if not result.total_matches:
        result.missing_rows_suspected = delta > tolerance
        result.extraction_errors.append(
            f"Amount mismatch: computed {computed:,.2f} vs expected {expected_total:,.2f} "
            f"(Δ = {computed - expected_total:+,.2f} SR)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Print summary report
# ─────────────────────────────────────────────────────────────────────────────
def print_report(result: ExtractionResult) -> None:
    sep = "─" * 72
    tick = "✓" if result.total_matches else "✗"

    print(f"\n{sep}")
    print("  EXTRACTION REPORT  —  Quotation S06666")
    print(sep)
    print(f"  Supplier       : {result.supplier_name}")
    print(f"  Quotation No.  : {result.quotation_number}")
    print(f"  Date           : {result.quotation_date}")
    print(f"  Currency       : {result.currency}")
    print(f"  LLM total      : {result.total_amount:,.2f}" if result.total_amount else "  LLM total      : —")
    print(f"  Line items     : {len(result.line_items)}")
    print(sep)

    # Section breakdown
    sections: dict[str, dict] = {}
    for li in result.line_items:
        s = li.section or "Unknown"
        if s not in sections:
            sections[s] = {"rows": 0, "amount": 0.0}
        sections[s]["rows"] += 1
        sections[s]["amount"] += li.amount or 0.0

    print("  Section breakdown:")
    for sec, info in sections.items():
        print(f"    {sec:<20}: {info['rows']:>3} rows  |  {info['amount']:>12,.2f} SR")

    print(sep)
    print(f"  {tick} Computed total : {result.computed_total:,.2f} SR")
    print(f"  Expected total : {EXPECTED_TOTAL_SR:,.2f} SR")
    if not result.total_matches:
        delta = (result.computed_total or 0) - EXPECTED_TOTAL_SR
        print(f"  ⚠  Delta       : {delta:+,.2f} SR  ← rows may be missing or merged")

    if result.extraction_errors:
        print(f"\n  Errors / Warnings ({len(result.extraction_errors)}):")
        for e in result.extraction_errors:
            print(f"    • {e}")

    print(sep)

    # Show duplicate SKU rows (the whole point of row_index)
    from collections import Counter
    sku_counts = Counter(li.product_code for li in result.line_items if li.product_code)
    dupes = {sku: cnt for sku, cnt in sku_counts.items() if cnt > 1}
    if dupes:
        print("  Duplicate SKUs preserved (expected behaviour):")
        for sku, cnt in dupes.items():
            rows_for_sku = [li for li in result.line_items if li.product_code == sku]
            print(f"    {sku}  ({cnt}×)")
            for li in rows_for_sku:
                print(f"      row {li.row_index:>3} | qty {li.quantity} | amount {li.amount}")
        print(sep)


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract structured data from Quotation S06666 PDF"
    )
    parser.add_argument("pdf", type=Path, help="Path to the PDF file")
    parser.add_argument(
        "--pages",
        default=None,
        help=(
            "Optional page range to process, e.g. '1-5' to skip known T&C pages. "
            "Omit this flag (default) to process ALL pages in the PDF."
        ),
    )
    parser.add_argument(
        "--keep-arabic",
        dest="keep_arabic",
        default="true",
        choices=["true", "false"],
        help="Whether to extract Arabic descriptions separately (default: true)",
    )
    parser.add_argument(
        "--expected-total",
        type=float,
        default=EXPECTED_TOTAL_SR,
        help=f"Expected grand total in SR for validation (default: {EXPECTED_TOTAL_SR:,.2f})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to write JSON output (e.g. results/S06666.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    pdf_path: Path = args.pdf.resolve()
    if not pdf_path.exists():
        print(f"[error] PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    # Parse page range — None means all pages
    page_range: tuple[int, int] | None = None
    if args.pages is not None:
        try:
            parts = args.pages.split("-")
            if len(parts) == 2:
                page_range = (int(parts[0]), int(parts[1]))
            elif len(parts) == 1:
                # Single page number treated as "page N only"
                n = int(parts[0])
                page_range = (n, n)
            else:
                raise ValueError("bad format")
        except ValueError:
            print(f"[error] Invalid --pages value '{args.pages}'. Use format: 1-5 or 3", file=sys.stderr)
            sys.exit(1)

    keep_arabic = args.keep_arabic.lower() == "true"
    expected_total = args.expected_total

    pages_label = f"{page_range[0]}–{page_range[1]}" if page_range else "all"
    print(f"\n[start] Processing: {pdf_path.name}")
    print(f"        Pages     : {pages_label}")
    print(f"        Arabic    : {'keep' if keep_arabic else 'discard'}")
    print(f"        Model     : {settings.llm_model}\n")

    # 1. Extract PDF text
    text, _per_page = extract_text_pages(pdf_path, page_range)
    char_count = len(text)
    print(f"[pdf] Extracted {char_count:,} characters (pages: {pages_label})")
    if char_count > 20_000:
        print(
            f"[warn] Text is large ({char_count:,} chars). "
            "Consider using --pages to limit to data-only pages if the model struggles."
        )

    # 2. Call LLM (passes pdf stem for raw-response file naming)
    raw_data = call_llm(text, keep_arabic, pdf_stem=pdf_path.stem)

    # 3. Parse into typed result
    result = parse_llm_output(raw_data)

    # 4. Post-validate totals
    post_validate(result, expected_total, EXPECTED_TOTAL_TOLERANCE)

    # 5. Print human-readable report
    print_report(result)

    # 6. Optionally save JSON
    out_path = args.out
    if out_path is None:
        out_path = pdf_path.parent / f"{pdf_path.stem}_extracted.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(asdict(result), fh, ensure_ascii=False, indent=2)
    print(f"\n[out] JSON saved -> {out_path}")


if __name__ == "__main__":
    main()

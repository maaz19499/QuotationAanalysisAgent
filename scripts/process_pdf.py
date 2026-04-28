#!/usr/bin/env python
"""CLI script for processing PDF quotations directly."""
import argparse
import json
import sys
from pathlib import Path

from quotation_core.core.logging_config import configure_logging
from quotation_core.extraction.pipeline import ExtractionPipeline

configure_logging()


def main() -> int:
    """Process a PDF file and output structured data."""
    parser = argparse.ArgumentParser(
        description="Extract structured data from quotation PDFs (vision-based)",
    )
    parser.add_argument(
        "input",
        type=str,
        help="Path to PDF file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "pretty"],
        default="pretty",
        help="Output format",
    )

    args = parser.parse_args()

    # Validate input
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File not found: {args.input}", file=sys.stderr)
        return 1

    if not input_path.suffix.lower() == ".pdf":
        print(f"Error: File must be a PDF: {args.input}", file=sys.stderr)
        return 1

    # Process
    try:
        pipeline = ExtractionPipeline()

        result = pipeline.process_sync(str(input_path))

        # Format output
        if args.format == "json":
            output = json.dumps(
                result.to_export_dict(),
                indent=2,
                default=str,
            )
        else:
            # Pretty print
            lines = [
                f"Supplier: {result.supplier_name or 'N/A'}",
                f"Quotation #: {result.quotation_number or 'N/A'}",
                f"Date: {result.quotation_date or 'N/A'}",
                f"Currency: {result.currency or 'N/A'}",
                f"Total: {result.total_amount or 'N/A'}",
                f"",
                f"Line Items ({len(result.line_items)}):",
            ]

            for item in result.line_items:
                lines.append(
                    f"  {item.line_number}. {item.product_code or 'N/A'} - "
                    f"{item.description or 'N/A'} - "
                    f"Qty: {item.quantity or 'N/A'} - "
                    f"Price: {item.total_price or 'N/A'}"
                )

            lines.append("")
            lines.append(f"Overall Confidence: {result.get_overall_confidence():.2%}")

            if result.extraction_errors:
                lines.append(f"Errors: {len(result.extraction_errors)}")
                for err in result.extraction_errors:
                    lines.append(f"  - {err}")

            output = "\n".join(lines)

        # Output
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Output written to: {args.output}")
        else:
            print(output)

        return 0

    except Exception as e:
        print(f"Error processing PDF: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

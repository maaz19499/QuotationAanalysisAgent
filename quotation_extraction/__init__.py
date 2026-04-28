"""Quotation Extraction — Production-grade PDF quotation to structured data pipeline.

Unified architecture:
  PDF → PyMuPDF rasterization → Page classification → Pillow preprocessing →
  LLM extraction (Flash pre-filter + Pro deep extraction) → Pydantic validation →
  Intelligent retry → Excel/JSON export
"""

__version__ = "2.0.0"
__author__ = "Mohammed Maaz"
__email__ = "maaz19499@gmail.com"

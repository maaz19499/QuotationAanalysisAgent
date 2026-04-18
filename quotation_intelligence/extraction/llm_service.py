"""LLM service for extraction validation and structuring — powered by LiteLLM.

LiteLLM acts as a unified gateway to any LLM provider.  Switch providers by
changing LLM_MODEL in your .env — no code changes required.

Model string examples
---------------------
  anthropic/claude-3-5-sonnet-20241022   # Anthropic
  openai/gpt-4o                          # OpenAI
  ollama/llama3.2                        # Ollama (local)
  groq/llama3-70b-8192                   # Groq
  gemini/gemini-1.5-pro                  # Google Gemini
"""
import json
from typing import Any

import litellm
from litellm import completion
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from quotation_intelligence.core.config import settings
from quotation_intelligence.core.logging_config import get_logger
from quotation_intelligence.extraction.post_processor import ResponseNormalizer
from quotation_intelligence.models.extraction import LineItemExtracted, QuotationExtracted

logger = get_logger(__name__)

# Silence LiteLLM's verbose default logging; we handle logging ourselves.
litellm.suppress_debug_info = True


class LLMExtractionError(Exception):
    """Custom error for LLM extraction failures."""

    pass


class LLMService:
    """Service for LLM-based extraction and validation via LiteLLM."""

    SYSTEM_PROMPT = """You are a specialized document extraction system for quotations and invoices.
Your task is to extract structured data from the provided document text.

Call the `structure_quotation` tool with the extracted values.

**Extraction rules:**
1. Extract supplier/company name, quotation number, date, and all line items
2. For each line item extract: product code, description, quantity, unit of measure, unit price, total price
3. Detect and return the currency code (SAR, USD, EUR, etc.)
4. Extract subtotal, tax/VAT, and grand total amounts
5. Provide confidence scores (0.0-1.0) for each field
6. Use null when a field is not present — never fabricate values

**Confidence Guidelines:**
- 0.9-1.0: Explicitly labeled and clearly readable
- 0.7-0.89: Identifiable with reasonable certainty
- 0.5-0.69: Inferred or partially unclear
- 0.0-0.49: Uncertain, guessed, or missing

**Numeric values:** strip currency symbols and commas (e.g. "30,106.08 SR" → 30106.08).
**Line numbers** must be sequential starting from 1.

**Output Schema:**
```json
{
  "supplier_name": "<string | null>",
  "quotation_number": "<string | null>",
  "quotation_date": "<string | null>",
  "currency": "<ISO code | null>",
  "subtotal": "<number | null>",
  "tax_amount": "<number | null>",
  "total_amount": "<number | null>",
  "supplier_name_confidence": "<0.0 – 1.0>",
  "quotation_number_confidence": "<0.0 – 1.0>",
  "quotation_date_confidence": "<0.0 – 1.0>",
  "total_confidence": "<0.0 – 1.0>",
  "extraction_errors": ["<any issues encountered>"],
  "line_items": [
    {
      "line_number": "<integer | null>",
      "product_code": "<string | null>",
      "description": "<string>",
      "quantity": "<number | null>",
      "unit_of_measure": "<string | null>",
      "unit_price": "<number | null>",
      "total_price": "<number | null>",
      "product_code_confidence": "<0.0 – 1.0>",
      "description_confidence": "<0.0 – 1.0>",
      "quantity_confidence": "<0.0 – 1.0>",
      "unit_price_confidence": "<0.0 – 1.0>",
      "total_price_confidence": "<0.0 – 1.0>"
    }
  ]
}
```
"""

    # ------------------------------------------------------------------
    # Tool schema — passed to the LLM so it MUST return structured args
    # instead of free-form text.  Mirrors QuotationExtracted / LineItemExtracted.
    # ------------------------------------------------------------------
    EXTRACTION_TOOL: dict = {
        "type": "function",
        "function": {
            "name": "structure_quotation",
            "description": (
                "Store the structured data extracted from a quotation or invoice document."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier_name": {
                        "type": ["string", "null"],
                        "description": "Supplier / vendor company name",
                    },
                    "quotation_number": {
                        "type": ["string", "null"],
                        "description": "Quotation or reference number",
                    },
                    "quotation_date": {
                        "type": ["string", "null"],
                        "description": "Date the quotation was issued (any format)",
                    },
                    "currency": {
                        "type": ["string", "null"],
                        "description": "ISO currency code e.g. SAR, USD, EUR",
                    },
                    "subtotal": {
                        "type": ["number", "null"],
                        "description": "Total before tax",
                    },
                    "tax_amount": {
                        "type": ["number", "null"],
                        "description": "VAT / GST / tax amount",
                    },
                    "total_amount": {
                        "type": ["number", "null"],
                        "description": "Grand total including tax",
                    },
                    "supplier_name_confidence": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                    },
                    "quotation_number_confidence": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                    },
                    "quotation_date_confidence": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                    },
                    "total_confidence": {
                        "type": "number", "minimum": 0.0, "maximum": 1.0,
                    },
                    "extraction_errors": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of any extraction problems encountered",
                    },
                    "line_items": {
                        "type": "array",
                        "description": "All product / service line items found in the document",
                        "items": {
                            "type": "object",
                            "required": ["description"],
                            "properties": {
                                "line_number": {"type": ["integer", "null"]},
                                "product_code": {"type": ["string", "null"]},
                                "description": {"type": "string"},
                                "quantity": {"type": ["number", "null"]},
                                "unit_of_measure": {"type": ["string", "null"]},
                                "unit_price": {"type": ["number", "null"]},
                                "total_price": {"type": ["number", "null"]},
                                "product_code_confidence": {
                                    "type": "number", "minimum": 0.0, "maximum": 1.0,
                                },
                                "description_confidence": {
                                    "type": "number", "minimum": 0.0, "maximum": 1.0,
                                },
                                "quantity_confidence": {
                                    "type": "number", "minimum": 0.0, "maximum": 1.0,
                                },
                                "unit_price_confidence": {
                                    "type": "number", "minimum": 0.0, "maximum": 1.0,
                                },
                                "total_price_confidence": {
                                    "type": "number", "minimum": 0.0, "maximum": 1.0,
                                },
                            },
                        },
                    },
                },
                "required": ["line_items"],
            },
        },
    }

    def __init__(self) -> None:
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature
        self.timeout = settings.llm_timeout_seconds
        self._normalizer = ResponseNormalizer()
        self._used_tool_call: bool = False  # set per-call for logging

        # Optional: set a global API key for providers that use a single key.
        # Provider-specific keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.) are
        # picked up automatically by LiteLLM from the environment.
        if settings.llm_api_key:
            litellm.api_key = settings.llm_api_key

        # Confirm model is reachable (best-effort — just logs a warning if not)
        logger.info(
            "llm_service_initialized",
            model=self.model,
            api_base=settings.llm_api_base or "default",
        )

    @property
    def client(self) -> bool:
        """
        Compatibility shim used by the pipeline to check whether LLM is available.

        With LiteLLM there's no explicit client object — we always return True
        and let the actual completion call surface any auth errors.
        """
        return True

    @retry(
        retry=retry_if_exception_type(
            (
                litellm.RateLimitError,
                litellm.Timeout,
                litellm.ServiceUnavailableError,
                litellm.APIConnectionError,
            )
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=30),
        reraise=True,
    )
    def extract_quotation(
        self,
        text: str,
        regex_candidates: dict[str, Any] | None = None,
    ) -> QuotationExtracted:
        """
        Extract structured quotation data using any LLM via LiteLLM.

        Args:
            text: Extracted text from PDF
            regex_candidates: Optional regex extraction candidates as hints

        Returns:
            Structured QuotationExtracted object
        """
        # user_prompt = self._build_prompt(text, regex_candidates)
        user_prompt = f"Extract all data from this document:\n\n{text}"

        logger.info(
            "llm_extraction_started",
            text_length=len(text),
            model=self.model,
        )

        try:
            response = completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                tools=[self.EXTRACTION_TOOL],
                tool_choice={"type": "function", "function": {"name": "structure_quotation"}},
                # max_tokens=self.max_tokens,
                temperature=self.temperature,
                timeout=self.timeout,
                format = "json",
                # Optional custom API base (e.g. Ollama at http://localhost:11434)
                **({"api_base": settings.llm_api_base} if settings.llm_api_base else {}),
            )

            raw_parsed = self._parse_tool_response(response)
            logger.info("raw_parsed", raw_parsed=raw_parsed)
            canonical = self._normalizer.normalize(raw_parsed)
            result = QuotationExtracted.model_validate(canonical)

            logger.info(
                "llm_extraction_completed",
                supplier=result.supplier_name,
                line_items_count=len(result.line_items),
                confidence=result.get_overall_confidence(),
                provider=response.model,
                extraction_mode="tool_call" if self._used_tool_call else "text_fallback",
            )

            return result

        except litellm.RateLimitError:
            logger.error("llm_rate_limit_exceeded", model=self.model)
            raise
        except litellm.AuthenticationError:
            logger.error("llm_authentication_error", model=self.model)
            raise LLMExtractionError(
                f"Authentication failed for model '{self.model}'. "
                "Check that the correct API key env variable is set."
            )
        except litellm.BadRequestError as e:
            logger.error("llm_bad_request", model=self.model, error=str(e))
            raise LLMExtractionError(f"Bad request to LLM: {e}") from e
        except json.JSONDecodeError as e:
            logger.error("llm_json_parse_error", error=str(e))
            raise LLMExtractionError(f"Failed to parse LLM response as JSON: {e}") from e
        except Exception as e:
            logger.error("llm_extraction_error", error=str(e), exc_info=True)
            raise LLMExtractionError(f"Extraction failed: {e}") from e

    def _build_prompt(
        self,
        text: str,
        regex_candidates: dict[str, Any] | None = None,
    ) -> str:
        """Build the extraction prompt with optional regex hints."""
        prompt_parts = [
            "Extract structured quotation data from the following text:",
            "",
            "---BEGIN TEXT---",
            text,  # Limit to avoid token limits
            "---END TEXT---",
            "",
        ]

        if regex_candidates:
            prompt_parts.extend([
                "Hints from preliminary analysis (use as reference only):",
                json.dumps(regex_candidates, indent=2, default=str),
                "",
            ])

        prompt_parts.extend([
            "Extract and return ONLY the JSON object per the system instructions.",
            "If you find potential line items in tables, include them all.",
            "Be precise with numerical values - do not guess.",
        ])

        return "\n".join(prompt_parts)

    def _parse_tool_response(self, response: Any) -> Any:
        """
        Extract structured data from a LiteLLM response.

        Priority order:
        1. **Tool call args** (``tool_calls[0].function.arguments``) — the model
           called ``structure_quotation`` with typed, schema-validated arguments.
        2. **Text fallback** — the model returned plain text / JSON in ``content``
           (common for Ollama or any provider that doesn't support tool calling).

        In both cases the result is passed to ``ResponseNormalizer`` before
        being handed to Pydantic, so shape mismatches are handled gracefully.
        """
        message = response.choices[0].message

        # ── Path 1: tool call ──────────────────────────────────────────────
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            args_str = tool_calls[0].function.arguments
            self._used_tool_call = True
            logger.debug("llm_tool_call_received", tool=tool_calls[0].function.name)
            try:
                return json.loads(args_str)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "tool_call_args_json_error",
                    error=str(exc),
                    fallback="text_content",
                )
                # Fall through to text fallback

        # ── Path 2: text fallback ──────────────────────────────────────────
        self._used_tool_call = False
        logger.warning(
            "llm_no_tool_call",
            model=response.model,
            hint="Model may not support tool calling; using text content fallback",
        )
        content = message.content or ""
        parsed = self._parse_response(content)
        
        # Sometimes models don't invoke native tools, but manually inline
        # the exact OpenAI interface (e.g., {"name": "func", "arguments": {...}})
        if isinstance(parsed, dict) and "arguments" in parsed and "name" in parsed:
            # Safely unwrap if inner arguments are double-stringified
            if isinstance(parsed["arguments"], str):
                import json
                try:
                    return json.loads(parsed["arguments"])
                except json.JSONDecodeError:
                    return parsed["arguments"]
            return parsed["arguments"]
            
        return parsed

    def _parse_response(self, content: str) -> Any:
        """Parse JSON from LLM response, handling markdown code fences."""
        content = content.strip()

        # Strip markdown code fences
        if "```json" in content:
            json_start = content.find("```json") + 7
            json_end = content.find("```", json_start)
            content = content[json_start:json_end].strip()
        elif content.startswith("```"):
            json_start = content.find("\n") + 1
            json_end = content.rfind("```")
            content = content[json_start:json_end].strip()

        # Direct parse: return whatever json.loads gives (dict, list, …).
        # ResponseNormalizer will handle any shape downstream.
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Fall back: find the outermost JSON object or array
            obj_start = content.find("{")
            arr_start = content.find("[")

            # Prefer whichever delimiter appears first
            if obj_start == -1 and arr_start == -1:
                raise json.JSONDecodeError("No JSON found in LLM response", content, 0)

            if obj_start != -1 and (arr_start == -1 or obj_start < arr_start):
                end_idx = content.rfind("}")
                return json.loads(content[obj_start : end_idx + 1])
            else:
                end_idx = content.rfind("]")
                return json.loads(content[arr_start : end_idx + 1])

    def validate_and_merge(
        self,
        llm_result: QuotationExtracted,
        regex_result: dict[str, Any],
    ) -> QuotationExtracted:
        """
        Validate LLM result against regex results and merge where beneficial.

        Future enhancement: boost confidence for fields where both methods agree.
        Currently trusts the LLM result.
        """
        return llm_result

    def fallback_extraction(self, text: str) -> QuotationExtracted:
        """
        Regex-only extraction when LLM is unavailable or fails.

        Confidence scores are penalised to reflect lower certainty.
        """
        from quotation_intelligence.extraction.regex_extractor import RegexExtractor

        extractor = RegexExtractor()
        candidates = extractor.extract(text)

        result = QuotationExtracted(
            supplier_name=None,
            extraction_errors=["LLM extraction failed — using regex fallback"],
            line_items=[],
        )

        if "quotation_number" in candidates:
            match = candidates["quotation_number"][0]
            result.quotation_number = match.value
            result.quotation_number_confidence = match.confidence * 0.7  # Penalise

        if "quotation_date" in candidates:
            match = candidates["quotation_date"][0]
            result.quotation_date = match.value
            result.quotation_date_confidence = match.confidence * 0.7

        if "total_amount" in candidates:
            match = candidates["total_amount"][0]
            try:
                result.total_amount = float(match.value.replace(",", ""))
                result.total_confidence = match.confidence * 0.7
            except ValueError:
                pass

        return result

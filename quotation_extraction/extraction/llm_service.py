"""LLM Service — Interacts with LiteLLM for vision-based extraction."""
import json
import time
from typing import Any

import litellm
from litellm import completion
from pydantic import TypeAdapter

from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import get_logger
from quotation_extraction.models.extraction import QuotationExtracted
from quotation_extraction.extraction.pdf_rasterizer import PageImage

logger = get_logger(__name__)


class LLMServiceError(Exception):
    """Raised when LLM extraction fails."""


class LLMService:
    """Service for extracting data from document images using LiteLLM."""

    def __init__(self) -> None:
        self.model = settings.llm_model
        self.merge_model = settings.llm_merge_model or settings.llm_model
        
        self.api_key = settings.llm_api_key
        if "gemini" in self.model.lower() and settings.gemini_api_key_paid:
            self.api_key = settings.gemini_api_key_paid
            
        self.api_base = settings.llm_api_base
        self.max_retries = settings.llm_max_retries
        self.timeout = settings.llm_timeout_seconds

        # Configure litellm (global settings)
        if self.api_base:
            litellm.api_base = self.api_base

    def extract_from_pages(
        self,
        pages: list[PageImage],
        mutation_attempt: int = 1,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Extract structured data from a list of page images.

        Args:
            pages: List of PageImage objects (base64 JPEGs).
            mutation_attempt: Current retry attempt (1-based). Used to mutate prompt.

        Returns:
            Tuple of (parsed_json_dict, cost_metrics_dict).
        """
        if not pages:
            raise ValueError("No pages provided for extraction")

        messages = self._build_messages(pages, mutation_attempt)
        schema = QuotationExtracted.model_json_schema()
        
        try:
            start_time = time.time()
            
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": settings.llm_temperature,
                "max_tokens": settings.llm_max_tokens,
                "timeout": self.timeout,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key

            # We use JSON mode if supported, or tools if supported.
            # For simplicity across providers, we use standard litellm tool calling for JSON output
            # (which is the most robust cross-provider way).
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": "extract_quotation",
                        "description": "Extract structured data from the quotation document.",
                        "parameters": schema,
                    },
                }
            ]
            kwargs["tool_choice"] = {"type": "function", "function": {"name": "extract_quotation"}}

            logger.info(
                "llm_request_started",
                model=self.model,
                pages=len(pages),
                attempt=mutation_attempt,
            )

            response = completion(**kwargs)
            
            latency = time.time() - start_time
            
            # Extract content from tool call
            try:
                if not response.choices:
                    logger.warning("llm_response_no_choices", response=str(response))
                    raise LLMServiceError("LLM returned no choices. This often happens if safety filters are triggered.")

                tool_calls = getattr(response.choices[0].message, 'tool_calls', None)
                if tool_calls and len(tool_calls) > 0:
                    content = tool_calls[0].function.arguments
                else:
                    content = response.choices[0].message.content or "{}"
            except (AttributeError, IndexError) as e:
                 logger.warning("llm_content_extraction_failed", error=str(e))
                 content = "{}"
                 
            logger.debug("llm_raw_content", content=content[:500] + "..." if len(content) > 500 else content)

            # Ensure we have a string to parse
            if isinstance(content, dict):
                parsed = content
            else:
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    # Strip markdown block if present
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0]
                    elif content.startswith("```"):
                        content = content[content.find("\n") + 1 : content.rfind("```")]
                    parsed = json.loads(content.strip())
            
            # Calculate cost metrics
            prompt_tokens = response.usage.prompt_tokens if hasattr(response, "usage") else 0
            completion_tokens = response.usage.completion_tokens if hasattr(response, "usage") else 0
            
            try:
                cost = litellm.cost_calculator.completion_cost(completion_response=response)
            except Exception:
                cost = 0.0

            metrics = {
                "model": self.model,
                "latency_sec": round(latency, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cost_usd": cost,
            }

            logger.info("llm_request_completed", **metrics)

            return parsed, metrics

        except Exception as e:
            logger.error("llm_request_failed", error=str(e), exc_info=True)
            raise LLMServiceError(f"LLM extraction failed: {e}") from e

    def _build_messages(self, pages: list[PageImage], attempt: int) -> list[dict[str, Any]]:
        """Build the messages payload for the LLM API, with prompt mutation."""
        
        # Base instructions
        system_prompt = (
            "You are an expert AI quotation extraction system. Your task is to accurately extract "
            "structured data from the provided images of quotation documents.\n\n"
            "Rules:\n"
            "1. Extract the supplier/vendor name, quotation number, date, and currency.\n"
            "2. Extract ALL line items exactly as they appear. Do not skip any items.\n"
            "3. Pay special attention to tabular data. Correlate descriptions, quantities, and prices carefully.\n"
            "4. Provide confidence scores (0.0 to 1.0) for your extractions.\n"
            "5. The output MUST be a valid JSON object matching the provided schema."
        )

        # Prompt Mutation: If we are retrying, adjust the prompt to focus the model
        if attempt == 2:
            system_prompt += (
                "\n\nCRITICAL WARNING (Attempt 2): A previous extraction attempt failed or missed line items. "
                "Please scan the document VERY carefully for tables containing products, quantities, and prices. "
                "Ensure NO items are left behind."
            )
        elif attempt >= 3:
            system_prompt += (
                "\n\nCRITICAL WARNING (Attempt 3): Previous attempts struggled with the structure. "
                "Focus EXCLUSIVELY on finding the line items table. Ignore headers and footers if they confuse you. "
                "Extract every row of the table with whatever data you can glean."
            )

        messages = [{"role": "system", "content": system_prompt}]

        content_parts = []
        for i, page in enumerate(pages):
            content_parts.append({"type": "text", "text": f"Page {page.page_number}:"})
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{page.base64_jpeg}"
                    },
                }
            )

        messages.append({"role": "user", "content": content_parts})
        return messages

    def merge_extractions(self, extractions: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Merge multiple chunked extractions into a single complete document.
        Used when a PDF has too many pages to process in one LLM call.
        """
        if not extractions:
            return {}, {}

        if len(extractions) == 1:
            return extractions[0], {"cost_usd": 0.0, "total_tokens": 0}

        try:
            start_time = time.time()
            
            system_prompt = (
                "You are an expert data merger. You are given several JSON objects representing "
                "partial extractions from chunks of a large quotation document. "
                "Your job is to merge them into a single, cohesive JSON object.\n\n"
                "Rules:\n"
                "1. Combine all `line_items` into a single, ordered list. Remove any obvious duplicates.\n"
                "2. Consolidate the header info (supplier, quotation number, etc.). Use the most complete/confident values.\n"
                "3. Consolidate totals. If chunks have different sub-totals, prefer the one from the final chunk.\n"
                "4. Output strictly according to the provided JSON schema."
            )

            kwargs: dict[str, Any] = {
                "model": self.merge_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(extractions)},
                ],
                "temperature": 0.0,
                "timeout": self.timeout,
            }
            if self.api_key:
                kwargs["api_key"] = self.api_key

            schema = QuotationExtracted.model_json_schema()
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": "merge_quotations",
                        "description": "Merge partial quotation data into a single coherent document.",
                        "parameters": schema,
                    },
                }
            ]
            kwargs["tool_choice"] = {"type": "function", "function": {"name": "merge_quotations"}}

            logger.info("llm_merge_started", chunks=len(extractions))

            response = completion(**kwargs)
            latency = time.time() - start_time
            
            try:
                tool_calls = response.choices[0].message.tool_calls
                if tool_calls and len(tool_calls) > 0:
                    content = tool_calls[0].function.arguments
                else:
                    content = response.choices[0].message.content or "{}"
            except AttributeError:
                 content = response.choices[0].message.content or "{}"

            if isinstance(content, dict):
                parsed = content
            else:
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif content.startswith("```"):
                    content = content[content.find("\n") + 1 : content.rfind("```")]
                parsed = json.loads(content.strip())
            
            prompt_tokens = response.usage.prompt_tokens if hasattr(response, "usage") else 0
            completion_tokens = response.usage.completion_tokens if hasattr(response, "usage") else 0
            try:
                cost = litellm.cost_calculator.completion_cost(completion_response=response)
            except Exception:
                cost = 0.0

            metrics = {
                "model": self.merge_model,
                "latency_sec": round(latency, 2),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "cost_usd": cost,
            }

            logger.info("llm_merge_completed", **metrics)
            return parsed, metrics

        except Exception as e:
            logger.error("llm_merge_failed", error=str(e), exc_info=True)
            # Fallback: naive python dict merge
            logger.warning("falling_back_to_naive_merge")
            merged = extractions[0].copy()
            merged["line_items"] = []
            for ext in extractions:
                if "line_items" in ext:
                    merged["line_items"].extend(ext["line_items"])
            return merged, {"cost_usd": 0.0, "total_tokens": 0, "fallback_used": True}

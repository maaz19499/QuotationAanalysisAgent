# Changelog

All notable changes to **Quotation Intelligence** are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [0.2.0] — 2026-04-17

### ✨ Added

- **LiteLLM gateway** — replaced the hard-coded Anthropic client with
  [LiteLLM](https://docs.litellm.ai/) as a universal provider gateway.
  Switch between any LLM (Anthropic, OpenAI, Groq, Ollama, Gemini, Bedrock, …)
  by changing a single environment variable — no code changes required.
- **Standalone API router** (`/api/v1/standalone/extract`) — new synchronous
  endpoint that runs the full extraction pipeline (PDF parsing → regex →
  LLM) and returns results immediately, without requiring PostgreSQL, Redis,
  or Celery. Designed for rapid local testing.
- **Test notebook** (`notebooks/test_api.ipynb`) — comprehensive Jupyter
  notebook covering:
  - Direct LiteLLM / `LLMService` unit tests
  - Health-check endpoints
  - Standalone extract (local file path & base64)
  - Full pipeline (upload → poll → export) with PostgreSQL + Celery
  - CSV / Excel / JSON export downloads
  - Provider-switching demonstration cell
- **`asyncpg` dependency** — added to resolve `ModuleNotFoundError` when
  SQLAlchemy initialises an async PostgreSQL connection.
- **`ipykernel` & `requests`** — added to project dependencies to support
  running the test notebook inside the Poetry virtualenv.

### 🔄 Changed

- **`LLM_MODEL` env var** (breaking for existing `.env` files) — replaces the
  old `ANTHROPIC_API_KEY`-only approach. Set `LLM_MODEL` to a LiteLLM provider
  string (e.g. `ollama/gemma4:e4b`, `anthropic/claude-3-5-sonnet-20241022`).
  See `.env.example` for the full provider reference table.
- **`LLM_API_BASE`** — new env var for custom / local provider endpoints
  (e.g. `http://localhost:11434` for Ollama).
- **`LLM_API_KEY`** — generic key field replaces `ANTHROPIC_API_KEY`.
  Provider-specific keys (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are
  still read automatically by LiteLLM from the environment.
- **`LLM_TIMEOUT_SECONDS`** — increased default from `60` to `300` to
  accommodate slower local models (e.g. Ollama running a 27B-class model).
- **`logging_config.py`** — updated `structlog` processor chain to be
  compatible with structlog 24.x API (`foreign_chain` parameter removed,
  `ProcessorFormatter` signature updated).
- **`.env.example`** — fully rewritten with a provider reference table and
  clear comments for every LLM-related variable.

### 🐛 Fixed

- **`AttributeError: 'Settings' object has no attribute 'anthropic_api_key'`**
  in `pipeline.py` — updated reference to the renamed field. The pipeline now
  enables LLM mode if either `llm_api_key` **or** `llm_model` is set.
- **`UnboundLocalError: cannot access local variable 'status'`** in
  `standalone.py` — renamed the local variable `status` (which shadowed the
  imported `fastapi.status` module) to `result_status`.
- **`FastAPIError` on startup** in `exports.py` — added `response_model=None`
  to the two file-download route decorators (`FileResponse` / `StreamingResponse`
  return types are not compatible with FastAPI's automatic schema generation).
- **`FutureWarning: Possible nested set`** in `regex_extractor.py` — inlined
  currency symbol and code constants directly into the compiled regex patterns
  to avoid Python 3.12+ warnings about nested character-class sets.
- **`ReadTimeout` when calling Ollama** — root cause was the 60-second default
  timeout being too short for large local models. Fixed by raising
  `LLM_TIMEOUT_SECONDS` to 300 in `.env`.

### 🗂 Files Changed

| File | Change |
|---|---|
| `quotation_intelligence/extraction/llm_service.py` | Full rewrite — Anthropic SDK replaced by LiteLLM |
| `quotation_intelligence/extraction/pipeline.py` | `settings.anthropic_api_key` → `settings.llm_api_key or settings.llm_model` |
| `quotation_intelligence/extraction/regex_extractor.py` | Inlined currency regex patterns; fixed `FutureWarning` |
| `quotation_intelligence/api/main.py` | Mounted standalone router at `/api/v1/standalone` |
| `quotation_intelligence/api/routers/__init__.py` | Exported `standalone` router |
| `quotation_intelligence/api/routers/standalone.py` | Renamed `status` var to `result_status`; fixed `UnboundLocalError` |
| `quotation_intelligence/api/routers/exports.py` | Added `response_model=None` to file-download routes |
| `quotation_intelligence/core/logging_config.py` | Updated structlog 24.x processor chain |
| `quotation_intelligence/core/config.py` | Added `llm_model`, `llm_api_key`, `llm_api_base`, `llm_timeout_seconds` settings |
| `.env` | `LLM_TIMEOUT_SECONDS` raised to `300`; Ollama configured as default provider |
| `.env.example` | Full rewrite with LiteLLM provider reference table |
| `pyproject.toml` | Added `litellm`, `asyncpg`, `ipykernel`, `requests` dependencies |
| `notebooks/test_api.ipynb` | **New** — comprehensive API & LLM test notebook |

---

## [0.1.0] — initial release

- FastAPI application scaffold with document upload, Celery task queue,
  PostgreSQL storage, and Anthropic-based PDF extraction pipeline.
- Regex extractor for quotation fields (supplier, date, currency, line items).
- Export endpoints: JSON, CSV, Excel.
- Docker Compose configuration for local development.
- Prometheus metrics and Sentry error tracking integration.

---

[Unreleased]: https://github.com/yourorg/quotation-intelligence/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/yourorg/quotation-intelligence/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/yourorg/quotation-intelligence/releases/tag/v0.1.0

# Change Log - Quotation Intelligence SaaS

## [0.1.0] - 2026-04-17

### Initial Implementation

#### Core Architecture
- **Project Structure**: Set up clean architecture with separation of concerns
  - `api/`: FastAPI application layer
  - `core/`: Configuration and logging
  - `extraction/`: Hybrid extraction pipeline
  - `models/`: Database models and Pydantic schemas
  - `services/`: Business services (storage, export)
  - `tasks/`: Celery async task queue

#### Extraction Pipeline (`extraction/`)
- `pdf_parser.py`: PDF text and table extraction using pdfplumber + PyMuPDF
  - Automatic OCR fallback via Tesseract for scanned documents
  - Extracts both text content and structured tables
  - Page-level processing with metadata extraction

- `regex_extractor.py`: Pattern-based candidate extraction
  - 8+ regex patterns for common fields (quotation numbers, dates, totals, tax)
  - Table header mapping for line item detection
  - Confidence scoring based on context indicators
  - Currency symbol and code detection

- `llm_service.py`: Anthropic Claude integration
  - Claude 3.5 Sonnet for validation and structuring
  - 3-attempt retry with exponential backoff
  - JSON schema enforcement via Pydantic
  - Fallback to regex-only if LLM unavailable
  - 60-second timeout with soft limits

- `post_processor.py`: Data validation and normalization
  - Line item deduplication (content similarity)
  - Price validation (quantity × unit_price = total_price)
  - Missing total calculation from line items
  - Currency normalization (USD, EUR, etc.)
  - Subtotal/total validation with error reporting
  - Sequential line item renumbering

- `pipeline.py`: Main orchestrator
  - Async processing flow: Parse → Regex → LLM → Post-process → Persist
  - Processing status tracking (PENDING → PROCESSING → COMPLETED/PARTIAL/FAILED)
  - Error handling with retry logic
  - Processing time metrics

#### Data Models (`models/`)
- `database.py`: SQLAlchemy async models
  - `Document`: File metadata, processing status, timestamps
  - `ExtractionResult`: Structured extraction output with confidence scores
  - `LineItem`: Individual line items with per-field confidence
  - Enums: ProcessingStatus, ExtractionConfidence
  - Indexes on status, dates, confidence for query performance

- `schemas.py`: Pydantic API schemas
  - `DocumentUploadBase64` / `DocumentUploadLocal`: Input validation
  - `DocumentResponse` / `DocumentDetailResponse`: Output schemas
  - `LineItemSchema`: Complete line item with confidence
  - `ExtractionSummary`: Aggregate confidence metrics
  - `ExportRequest`: Export format selection

- `extraction.py`: LLM output validation
  - `LineItemExtracted`: Validated line item extraction
  - `QuotationExtracted`: Complete quotation with header fields
  - Automatic numeric conversion (handles currency strings)
  - Overall confidence calculation with weighted field importance
  - Missing field detection

#### API Layer (`api/`)
- `main.py`: FastAPI application
  - Lifespan events for startup/shutdown logging
  - Global exception handler with structured logging
  - Sentry integration (conditional on DSN)
  - CORS middleware with environment-specific origins
  - Health check endpoint at `/health`

- `routers/documents.py`: Document endpoints
  - `POST /upload`: Accepts Base64 (production) or local path (dev)
  - File validation (size, type, extension)
  - `GET /{id}`: Retrieve document with extraction results
  - `GET /`: List documents with status filtering
  - `POST /{id}/reprocess`: Retry failed processing
  - API key authentication via X-API-Key header

- `routers/exports.py`: Export endpoints
  - `GET /{id}?format=json/csv/excel`: Download extraction results
  - `GET /preview/{id}`: Quick inline preview (first 10 line items)
  - Streaming responses for large files
  - Meaningful filenames from quotation numbers

- `routers/health.py`: Health monitoring
  - `/ready`: Readiness probe with DB connectivity check
  - `/live`: Liveness probe
  - `/version`: Version and feature flags

#### Services (`services/`)
- `storage_service.py`: File storage abstraction
  - Local filesystem or S3 backend
  - Base64 decoding and validation
  - File size limits (configurable, default 10MB)
  - MIME type validation
  - Unique filename generation with UUID

- `export_service.py`: Format conversion
  - JSON: Structured with metadata
  - CSV: Line items with headers
  - Excel: Multi-sheet (Summary + Line Items) with confidence columns

#### Task Queue (`tasks/`)
- `celery_app.py`: Celery configuration
  - Redis broker and backend
  - JSON serialization
  - Task timeouts (120 seconds)
  - Late acks with prefetch=1 for reliability

- `processing_tasks.py`: Document processing worker
  - `process_document_task`: Main processing task with retry logic
  - `cleanup_old_documents`: Scheduled cleanup (30-day retention)
  - Async DB session management
  - Soft time limit handling

#### Configuration (`core/`)
- `config.py`: Pydantic-settings
  - Environment variable loading
  - Type-safe settings with validation
  - Sync/async database URL conversion
  - Environment-specific defaults

- `logging_config.py`: Structured logging
  - JSON logs for production (ELK/Datadog compatible)
  - Pretty colored logs for development
  - structlog integration with contextvars
  - Quiet noisy library logging (urllib3, httpx)

#### Database Migration (`alembic/`)
- `env.py`: Async Alembic configuration
- `versions/initial_migration.py`: Initial schema
  - PostgreSQL enum types
  - Foreign key constraints with CASCADE
  - Indexes for common queries

#### Docker Configuration (`docker/`)
- `Dockerfile`: Multi-stage build
  - `builder`: Install dependencies
  - `production`: Optimized runtime image
  - `development`: With reload and dev tools
  - Tesseract OCR + poppler-utils included
  - Non-root user (`appuser`)
  - Health check via HTTP endpoint

- `docker-compose.yml`: Full stack
  - PostgreSQL 15 with health checks
  - Redis 7 for Celery
  - API server with live reload
  - Celery worker with concurrency=2
  - Celery beat for scheduled tasks
  - Flower monitoring on port 5555
  - Volume persistence for uploads

#### Testing (`tests/`)
- `conftest.py`: Test fixtures
  - In-memory SQLite for tests
  - Async session management
  - Sample quotation text fixture
  - Mock PDF file generator
  - Mock Anthropic response fixture
  - Environment variable mocking

- `unit/test_regex_extractor.py`: Regex tests
  - Quotation number pattern matching
  - Date extraction (multiple formats)
  - Total/subtotal/tax extraction
  - Confidence scoring validation
  - Line item candidate extraction

- `unit/test_post_processor.py`: Post-processing tests
  - Duplicate line item removal
  - Price validation and correction
  - Missing total calculation
  - Sequential renumbering
  - Currency normalization
  - Validation warning generation

- `integration/test_api.py`: API tests
  - Health check endpoint
  - Document upload (Base64, local path, validation errors)
  - Export endpoints
  - Input validation (422 errors)

#### Build & Development Tools
- `pyproject.toml`: Poetry configuration
  - Dependencies: FastAPI, SQLAlchemy, Celery, pdfplumber, anthropic
  - Dev dependencies: pytest, black, ruff, mypy
  - Tool configs: black (100 char), ruff, mypy (strict), pytest

- `Makefile`: Common commands
  - `db-up` / `db-down`: Docker services
  - `run` / `worker`: Development servers
  - `test` / `test-cov`: Testing
  - `lint` / `format`: Code quality
  - `migrate` / `migrate-make`: Database

- `scripts/process_pdf.py`: CLI tool
  - Direct PDF processing without API
  - JSON and pretty-print output formats
  - Optional LLM/OCR disable flags
  - Exit codes for scripting

#### Documentation
- `README.md`: Complete usage guide
  - Quick start instructions
  - API examples with curl
  - Configuration reference
  - Project structure diagram
  - Deployment checklist
  - Testing commands

- `.env.example`: Template environment file
  - All configuration options documented
  - Development defaults
  - Security warnings for production

### Design Patterns & Best Practices

1. **Clean Architecture**: Clear separation between API, business logic, and data layers
2. **Async/Await**: Full async stack (FastAPI, SQLAlchemy, Celery tasks)
3. **Hybrid AI Approach**: Regex for speed/cost, LLM for accuracy, with fallbacks
4. **Confidence Scoring**: Every field has confidence, aggregates at document level
5. **Graceful Degradation**: Works without LLM (regex-only), works without OCR (text-only)
6. **Structured Logging**: JSON logs for production, pretty for dev
7. **Pydantic Validation**: Input/output validation at all boundaries
8. **Retry Logic**: Exponential backoff for LLM, idempotent tasks
9. **Type Safety**: Full mypy strict mode, type hints everywhere
10. **Test Coverage**: Unit + integration tests with async fixtures

### Known Limitations

- OCR accuracy depends on Tesseract (v1); planned: specialized document OCR
- Handwriting not supported (v1 non-goal per PRD)
- LLM costs scale with document volume (regex reduces calls)
- No web UI for manual correction (v2 roadmap)

### Next Steps (Recommended)

1. Add sample PDF fixtures for accuracy testing
2. Implement vendor-specific extraction profiles
3. Add batch upload endpoint (ZIP processing)
4. Build web UI for review/correction
5. Add metrics collection (extraction accuracy tracking)
6. Implement learning from corrections (fine-tuning pipeline)

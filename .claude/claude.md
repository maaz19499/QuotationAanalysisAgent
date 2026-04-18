# CLAUDE.md - Quotation Intelligence SaaS

## Project Overview

**Quotation Intelligence** is a SaaS platform that converts unstructured quotation PDFs into structured, standardized data (Excel/CRM-ready) using a hybrid AI + rule-based extraction engine.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   Frontend  │────▶│  FastAPI     │────▶│  Celery Worker  │
│  (Custom)   │     │  (Async)     │     │  (Queue)        │
└─────────────┘     └──────────────┘     └─────────────────┘
                           │                       │
                           ▼                       ▼
                    ┌──────────────┐      ┌─────────────────┐
                    │  PostgreSQL  │      │  LLM Service    │
                    │  (Metadata)  │      │  (Anthropic)    │
                    └──────────────┘      └─────────────────┘
                                                   │
                                                   ▼
                                          ┌─────────────────┐
                                          │  OCR (Tesseract)│
                                          └─────────────────┘
```

## Tech Stack

- **API**: FastAPI (async)
- **Database**: PostgreSQL + SQLAlchemy async
- **Queue**: Celery + Redis
- **PDF Parsing**: pdfplumber, PyMuPDF
- **OCR**: Tesseract
- **LLM**: Anthropic Claude 3.5 Sonnet
- **Validation**: Pydantic v2
- **Testing**: pytest + async fixtures
- **Deployment**: Docker + Docker Compose

## Directory Structure

```
quotation_intelligence/
├── api/              # FastAPI application
│   ├── main.py       # App entry point
│   └── routers/      # API endpoints (documents, exports, health)
├── core/             # Configuration, logging
│   ├── config.py     # Settings (pydantic-settings)
│   └── logging_config.py  # Structured logging (structlog)
├── extraction/       # Hybrid extraction pipeline
│   ├── pdf_parser.py       # PDF text/tables + OCR fallback
│   ├── regex_extractor.py  # Pattern matching (candidates)
│   ├── llm_service.py     # Anthropic LLM validation
│   ├── post_processor.py  # Validation & normalization
│   └── pipeline.py         # Orchestrator
├── models/           # Data layer
│   ├── database.py   # SQLAlchemy models (Document, ExtractionResult, LineItem)
│   ├── schemas.py    # Pydantic API schemas
│   └── extraction.py # LLM output validation models
├── services/         # Business logic
│   ├── storage_service.py  # Local/S3 file storage
│   └── export_service.py   # JSON/CSV/Excel export
└── tasks/            # Celery async tasks
    ├── celery_app.py       # Celery configuration
    └── processing_tasks.py # Document processing queue

docker/               # Docker configuration
├── Dockerfile        # Multi-stage build (builder + prod + dev)
└── docker-compose.yml # Full stack (API, Worker, DB, Redis, Flower)

tests/                # Test suite
├── unit/             # Unit tests (regex, post-processor)
└── integration/      # API integration tests

alembic/              # Database migrations
```

## Key Design Decisions

### 1. Hybrid Extraction Strategy
- **Regex first**: Extract candidates quickly, low cost
- **LLM validation**: Claude validates and structures, high accuracy
- **Confidence scoring**: Every field has 0.0-1.0 confidence
- **Fallbacks**: If LLM fails, use regex; if OCR needed, auto-trigger

### 2. Async Architecture
- FastAPI with async SQLAlchemy
- Celery workers for CPU-intensive PDF processing
- Non-blocking file uploads

### 3. Validation Strategy
- Pydantic models at every boundary
- Post-processing validates totals match line items
- Duplicate detection and removal

### 4. Error Handling
- Retry with exponential backoff (LLM, 3 attempts)
- Graceful degradation to lower-accuracy modes
- Partial results with confidence flags

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | - | LLM API key |
| `DATABASE_URL` | Yes | - | PostgreSQL connection |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Celery broker |
| `STORAGE_TYPE` | No | `local` | `local` or `s3` |
| `MAX_FILE_SIZE_MB` | No | `10` | Upload limit |
| `ENABLE_OCR_FALLBACK` | No | `true` | OCR for scanned PDFs |
| `ENVIRONMENT` | No | `development` | `development`/`staging`/`production` |

*Required for full extraction; falls back to regex-only if missing

## Common Commands

```bash
# Development
make db-up       # Start PostgreSQL + Redis
make run         # Run API server (uvicorn --reload)
make worker      # Run Celery worker
make migrate     # Run database migrations

# Testing
make test        # Run all tests
make test-cov    # With coverage report
make lint        # ruff + mypy
make format      # black + ruff --fix

# Docker (full stack)
make up          # docker-compose up --build
make down        # docker-compose down -v
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/documents/upload` | Upload PDF (Base64 or local path) |
| GET | `/api/v1/documents/{id}` | Get document + extraction result |
| GET | `/api/v1/documents/` | List documents (paginated) |
| POST | `/api/v1/documents/{id}/reprocess` | Retry processing |
| GET | `/api/v1/exports/{id}?format=` | Export (json/csv/excel) |
| GET | `/api/v1/exports/preview/{id}` | Quick preview |
| GET | `/health` | Health check |
| GET | `/api/v1/health/ready` | Readiness (includes DB check) |

## Testing Strategy

- **Unit tests**: Regex patterns, post-processing logic
- **Integration tests**: API endpoints with async client
- **Mocking**: LLM responses, file storage
- **Fixtures**: Sample PDF content, mock extraction results

## Deployment

### Production Checklist
1. Set `ENVIRONMENT=production`
2. Strong `SECRET_KEY` for API auth
3. S3 for file storage (not local)
4. Enable Sentry (`SENTRY_DSN`)
5. Multiple Celery workers (horizontal scaling)
6. Run migrations before deploy

### Scaling
- Stateless API servers (scale horizontally)
- Queue-based processing (add workers)
- Database connection pooling
- S3 for shared storage

## Future Roadmap

- [ ] Web UI for manual review/correction
- [ ] Vendor-specific optimization profiles
- [ ] Learning from corrections (fine-tuning)
- [ ] Multi-language OCR support
- [ ] API integrations (Salesforce, HubSpot)
- [ ] Batch processing (ZIP upload)

## Notes

- PDF parsing uses `pdfplumber` for tables, `PyMuPDF` as fallback
- OCR triggers automatically when page has <50 chars
- Confidence thresholds: High (≥0.9), Medium (0.7-0.89), Low (0.5-0.69), Uncertain (<0.5)
- All timestamps UTC, stored in PostgreSQL

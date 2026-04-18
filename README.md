# Quotation Intelligence SaaS

Convert unstructured quotation PDFs into structured, standardized data using a hybrid AI + rule-based extraction engine.

## Features

- **PDF Upload**: Support for drag & drop, bulk upload, and API uploads
- **Hybrid Extraction Engine**: Combines regex pattern matching with LLM validation
- **Field Extraction**: Supplier name, quotation number, dates, line items (product code, description, quantity, pricing)
- **Export Formats**: JSON, CSV, Excel
- **Async Processing**: Queue-based processing with Celery
- **Confidence Scoring**: Every extraction includes confidence scores

## Architecture

```
Frontend → FastAPI → Celery Worker
                ↓
            PostgreSQL
                ↓
        Extraction Pipeline
        (PDF → Text → Regex → LLM → Validate)
```

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+
- Redis 7+
- Tesseract OCR (optional but recommended)

### Installation

```bash
# Clone and setup
git clone <repo-url>
cd quotation-intelligence-saas

# Install Poetry if not present
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install

# Setup environment
cp .env.example .env
# Edit .env with your configuration

# Run migrations
poetry run alembic upgrade head

# Start services
docker-compose -f docker/docker-compose.yml up -d db redis

# Run API
poetry run uvicorn quotation_intelligence.api.main:app --reload

# Run Celery worker (in another terminal)
poetry run celery -A quotation_intelligence.tasks worker --loglevel=info
```

### Docker (Full Stack)

```bash
docker-compose -f docker/docker-compose.yml up --build
```

## API Usage

### Upload Document

```bash
curl -X POST "http://localhost:8000/api/v1/documents/upload" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "base64_upload": {
      "file_name": "quotation.pdf",
      "file_content_base64": "JVBERi0xLjQ...",
      "metadata": {"source": "email"}
    }
  }'
```

Response:
```json
{
  "document_id": "uuid",
  "status": "pending",
  "message": "Document queued for processing",
  "estimated_completion_time": "10-30 seconds"
}
```

### Check Status

```bash
curl "http://localhost:8000/api/v1/documents/{document_id}" \
  -H "X-API-Key: your-api-key"
```

### Export Results

```bash
# JSON
curl "http://localhost:8000/api/v1/exports/{document_id}?format=json" \
  -H "X-API-Key: your-api-key"

# Excel
curl -OJ "http://localhost:8000/api/v1/exports/{document_id}?format=excel" \
  -H "X-API-Key: your-api-key"
```

## Configuration

Key environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection | `redis://localhost:6379/0` |
| `ANTHROPIC_API_KEY` | LLM API key | - |
| `STORAGE_TYPE` | `local` or `s3` | `local` |
| `MAX_FILE_SIZE_MB` | Max upload size | `10` |
| `ENABLE_OCR_FALLBACK` | OCR for scanned PDFs | `true` |

## Project Structure

```
quotation_intelligence/
├── api/              # FastAPI application
│   ├── main.py       # App entry point
│   └── routers/      # API endpoints
├── core/             # Core configuration
├── extraction/       # Extraction pipeline
│   ├── pdf_parser.py       # PDF text/tables
│   ├── regex_extractor.py  # Pattern matching
│   ├── llm_service.py      # LLM validation
│   ├── post_processor.py   # Data validation
│   └── pipeline.py         # Main orchestrator
├── models/           # Database models & schemas
├── services/         # Business services
├── tasks/            # Celery tasks
└── utils/            # Utilities
docker/               # Docker configuration
tests/                # Test suite
```

## Testing

```bash
# Run tests
poetry run pytest

# With coverage
poetry run pytest --cov=quotation_intelligence --cov-report=html

# Specific test
poetry run pytest tests/unit/test_regex_extractor.py -v
```

## Monitoring

- **Flower**: Celery monitoring at `http://localhost:5555`
- **API Docs**: Swagger at `http://localhost:8000/docs`
- **Health**: `http://localhost:8000/health`
- **Metrics**: Prometheus at `http://localhost:8000/metrics` (if enabled)

## Deployment

### Production Checklist

1. Set `ENVIRONMENT=production`
2. Configure `SECRET_KEY` (cryptographically strong)
3. Set up S3 for file storage
4. Enable Sentry for error tracking
5. Configure PostgreSQL with backups
6. Run migrations before deployment
7. Use multiple Celery workers

### AWS ECS Example

```bash
# Build and push
docker build -f docker/Dockerfile -t quotation-api:latest .
docker tag quotation-api:latest $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/quotation-api:latest
docker push $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/quotation-api:latest

# Deploy
echo "Update ECS service with new image"
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run tests and linting: `poetry run ruff check . && poetry run mypy .`
4. Submit a Pull Request

## Roadmap

- [ ] Web UI for document review and correction
- [ ] Multi-language support
- [ ] Vendor-specific optimization
- [ ] ML fine-tuning from corrections
- [ ] API integrations (Salesforce, HubSpot)

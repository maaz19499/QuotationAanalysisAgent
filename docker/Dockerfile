# Multi-stage build for optimized production image
FROM python:3.11-slim as builder

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
WORKDIR /app
RUN pip install --no-cache-dir poetry

# Copy poetry files
COPY pyproject.toml ./

# Generate lockfile if not present and install dependencies
RUN poetry config virtualenvs.in-project true && \
    poetry lock --no-update 2>/dev/null || true && \
    poetry install --no-root --no-dev

# Production stage
FROM python:3.11-slim as production

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONFAULTHANDLER=1

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Create necessary directories
RUN mkdir -p /app/uploads /app/logs && chown -R appuser:appuser /app

# Copy application code
WORKDIR /app
COPY quotation_intelligence ./quotation_intelligence
COPY alembic ./alembic
COPY alembic.ini ./

# Change ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()"

# Default command
CMD ["uvicorn", "quotation_intelligence.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Development stage
FROM builder as development

# Install dev dependencies
RUN poetry install --no-root

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for development
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy everything
COPY . .

# Install in editable mode
RUN poetry install

EXPOSE 8000

CMD ["uvicorn", "quotation_intelligence.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

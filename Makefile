# Quotation Intelligence - Makefile
.PHONY: help install dev-install test lint format migrate db-up db-down run worker shell clean

# Default target
help:
	@echo "Available commands:"
	@echo "  install       - Install production dependencies"
	@echo "  dev-install   - Install development dependencies"
	@echo "  test          - Run test suite"
	@echo "  lint          - Run linting (ruff, mypy)"
	@echo "  format        - Format code (black, ruff)"
	@echo "  migrate       - Run database migrations"
	@echo "  migrate-make  - Create new migration"
	@echo "  db-up         - Start Docker services (db, redis)"
	@echo "  db-down       - Stop Docker services"
	@echo "  run           - Run development server"
	@echo "  worker        - Run Celery worker"
	@echo "  flower        - Run Flower monitoring"
	@echo "  shell         - Open Python shell"
	@echo "  clean         - Clean generated files"

# Dependencies
install:
	poetry install --no-dev

dev-install:
	poetry install

# Testing
test:
	poetry run pytest -v

test-cov:
	poetry run pytest --cov=quotation_extraction --cov-report=html

test-unit:
	poetry run pytest tests/unit -v

test-integration:
	poetry run pytest tests/integration -v

# Linting and formatting
lint:
	poetry run ruff check quotation_extraction tests
	poetry run mypy quotation_extraction

format:
	poetry run black quotation_extraction tests
	poetry run ruff check --fix quotation_extraction tests

format-check:
	poetry run black --check quotation_extraction tests

# Database
migrate:
	poetry run alembic upgrade head

migrate-make:
	@read -p "Migration message: " msg; \
	poetry run alembic revision --autogenerate -m "$$msg"

db-reset:
	poetry run alembic downgrade base
	poetry run alembic upgrade head

# Docker
db-up:
	docker-compose -f docker/docker-compose.yml up -d db redis

db-down:
	docker-compose -f docker/docker-compose.yml down

up:
	docker-compose -f docker/docker-compose.yml up --build

down:
	docker-compose -f docker/docker-compose.yml down -v

# Running
run:
	poetry run uvicorn quotation_extraction.api.main:app --reload --host 0.0.0.0 --port 8000

run-prod:
	poetry run gunicorn quotation_extraction.api.main:app -k uvicorn.workers.UvicornWorker -w 4

worker:
	poetry run celery -A quotation_extraction.tasks worker --loglevel=info -c 2

worker-debug:
	poetry run celery -A quotation_extraction.tasks worker --loglevel=debug -c 1

beat:
	poetry run celery -A quotation_extraction.tasks beat --loglevel=info

flower:
	poetry run celery -A quotation_extraction.tasks flower --port=5555

# Development
shell:
	poetry run python

ipython:
	poetry run ipython

# Utilities
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage 2>/dev/null || true
	rm -rf dist build 2>/dev/null || true

docker-build:
	docker build -f docker/Dockerfile -t quotation-api:latest .

# CI targets (for GitHub Actions, etc.)
ci-test:
	poetry run pytest --cov=quotation_extraction --cov-report=xml

ci-lint:
	poetry run ruff check quotation_extraction tests
	poetry run mypy quotation_extraction

ci-security:
	poetry run bandit -r quotation_extraction

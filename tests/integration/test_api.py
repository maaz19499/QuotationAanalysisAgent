"""API integration tests."""
import base64
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from quotation_extraction.api.main import app


@pytest.fixture
async def async_client() -> AsyncClient:
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    async def test_health_check(self, async_client: AsyncClient) -> None:
        """Test health endpoint returns healthy."""
        response = await async_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestDocumentEndpoints:
    """Tests for document upload and retrieval."""

    async def test_upload_base64_valid_pdf(self, async_client: AsyncClient) -> None:
        """Test uploading a valid PDF via Base64."""
        # Create minimal PDF
        pdf_content = b"%PDF-1.4\n1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n%%EOF"
        base64_content = base64.b64encode(pdf_content).decode()

        response = await async_client.post(
            "/api/v1/documents/upload",
            json={
                "base64_upload": {
                    "file_name": "test.pdf",
                    "file_content_base64": base64_content,
                    "metadata": {"test": True},
                }
            },
        )

        # Should be accepted (202) or validation error (400 for non-PDF structure)
        assert response.status_code in [202, 400]

    async def test_upload_invalid_base64(self, async_client: AsyncClient) -> None:
        """Test uploading with invalid base64."""
        response = await async_client.post(
            "/api/v1/documents/upload",
            json={
                "base64_upload": {
                    "file_name": "test.pdf",
                    "file_content_base64": "not-valid-base64!!!",
                }
            },
        )

        assert response.status_code == 400

    async def test_upload_no_pdf_extension(self, async_client: AsyncClient) -> None:
        """Test uploading file without PDF extension."""
        base64_content = base64.b64encode(b"test").decode()

        response = await async_client.post(
            "/api/v1/documents/upload",
            json={
                "base64_upload": {
                    "file_name": "test.txt",  # Wrong extension
                    "file_content_base64": base64_content,
                }
            },
        )

        assert response.status_code == 400

    async def test_upload_both_methods(self, async_client: AsyncClient) -> None:
        """Test that both upload methods can't be provided."""
        response = await async_client.post(
            "/api/v1/documents/upload",
            json={
                "base64_upload": {
                    "file_name": "test1.pdf",
                    "file_content_base64": base64.b64encode(b"test").decode(),
                },
                "local_upload": {
                    "file_path": "/path/to/test.pdf",
                },
            },
        )

        assert response.status_code == 422  # Validation error

    async def test_get_nonexistent_document(self, async_client: AsyncClient) -> None:
        """Test getting a document that doesn't exist."""
        response = await async_client.get(
            "/api/v1/documents/12345678-1234-1234-1234-123456789abc"
        )

        assert response.status_code == 404

    async def test_list_documents(self, async_client: AsyncClient) -> None:
        """Test listing documents."""
        response = await async_client.get("/api/v1/documents/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestExportEndpoints:
    """Tests for export functionality."""

    async def test_export_nonexistent_document(self, async_client: AsyncClient) -> None:
        """Test exporting non-existent document."""
        response = await async_client.get(
            "/api/v1/exports/12345678-1234-1234-1234-123456789abc?format=json"
        )

        assert response.status_code == 404

    async def test_invalid_export_format(self, async_client: AsyncClient) -> None:
        """Test exporting with invalid format."""
        response = await async_client.get(
            "/api/v1/exports/12345678-1234-1234-1234-123456789abc?format=xml"
        )

        # Should be validation error
        assert response.status_code in [400, 404, 422]


class TestValidation:
    """Tests for input validation."""

    async def test_upload_no_method(self, async_client: AsyncClient) -> None:
        """Test upload with no method provided."""
        response = await async_client.post(
            "/api/v1/documents/upload",
            json={},
        )

        assert response.status_code == 422

    async def test_upload_empty_base64(self, async_client: AsyncClient) -> None:
        """Test upload with empty base64 content."""
        response = await async_client.post(
            "/api/v1/documents/upload",
            json={
                "base64_upload": {
                    "file_name": "test.pdf",
                    "file_content_base64": "",
                }
            },
        )

        assert response.status_code == 422  # Empty content validation

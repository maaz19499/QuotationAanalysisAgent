"""File storage service - local or S3."""
import base64
import io
import shutil
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

from quotation_intelligence.core.config import settings
from quotation_intelligence.core.logging_config import get_logger

logger = get_logger(__name__)


class StorageError(Exception):
    """Storage operation error."""

    pass


class FileValidationError(Exception):
    """File validation error."""

    pass


class StorageService:
    """Handle file storage - local filesystem or S3."""

    MAX_FILE_SIZE_BYTES = settings.max_file_size_mb * 1024 * 1024
    ALLOWED_MIME_TYPES = {"application/pdf"}

    def __init__(self) -> None:
        self.storage_type = settings.storage_type
        self.local_path = Path(settings.storage_local_path)
        self.s3_bucket = settings.s3_bucket_name
        self.s3_client = None

        if self.storage_type == "local":
            self.local_path.mkdir(parents=True, exist_ok=True)
        elif self.storage_type == "s3" and settings.aws_access_key_id:
            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )

    def validate_file(
        self,
        content: bytes | BinaryIO,
        file_name: str,
        mime_type: str | None = None,
    ) -> None:
        """Validate file size and type."""
        # Get size
        if isinstance(content, bytes):
            size = len(content)
        else:
            content.seek(0, 2)  # Seek to end
            size = content.tell()
            content.seek(0)  # Reset

        # Check size
        if size > self.MAX_FILE_SIZE_BYTES:
            raise FileValidationError(
                f"File size ({size / 1024 / 1024:.1f}MB) exceeds "
                f"maximum allowed ({settings.max_file_size_mb}MB)"
            )

        if size == 0:
            raise FileValidationError("File is empty")

        # Check mime type
        if mime_type and mime_type not in self.ALLOWED_MIME_TYPES:
            raise FileValidationError(f"Invalid file type: {mime_type}")

        # Check file extension
        if not file_name.lower().endswith(".pdf"):
            raise FileValidationError("File must be a PDF")

        logger.debug(
            "file_validation_passed",
            file_name=file_name,
            size_bytes=size,
            mime_type=mime_type,
        )

    def save_from_base64(
        self,
        base64_content: str,
        file_name: str,
        mime_type: str | None = None,
    ) -> str:
        """
        Save file from base64 content.

        Returns:
            Path or key to the saved file
        """
        try:
            content = base64.b64decode(base64_content)
        except Exception as e:
            raise FileValidationError(f"Invalid base64 content: {e}")

        self.validate_file(content, file_name, mime_type)

        # Generate unique filename
        unique_id = uuid4().hex[:12]
        safe_name = Path(file_name).stem[:50]  # Truncate long names
        unique_file_name = f"{unique_id}_{safe_name}.pdf"

        if self.storage_type == "s3" and self.s3_client:
            return self._save_to_s3(content, unique_file_name, mime_type)
        else:
            return self._save_to_local(content, unique_file_name)

    def save_from_local_path(
        self,
        source_path: str,
        file_name: str | None = None,
    ) -> str:
        """
        Save file from local path (for dev/testing).

        Returns:
            Path or key to the saved file
        """
        source = Path(source_path)
        if not source.exists():
            raise StorageError(f"File not found: {source_path}")

        file_name = file_name or source.name

        with open(source, "rb") as f:
            content = f.read()

        self.validate_file(content, file_name)

        # Generate unique filename
        unique_id = uuid4().hex[:12]
        safe_name = Path(file_name).stem[:50]
        unique_file_name = f"{unique_id}_{safe_name}.pdf"

        if self.storage_type == "s3" and self.s3_client:
            return self._save_to_s3(content, unique_file_name)
        else:
            # Copy to local storage
            dest_path = self.local_path / unique_file_name
            shutil.copy(source, dest_path)
            return str(dest_path)

    def _save_to_local(self, content: bytes, file_name: str) -> str:
        """Save file to local filesystem."""
        file_path = self.local_path / file_name

        with open(file_path, "wb") as f:
            f.write(content)

        logger.info("file_saved_local", path=str(file_path), size=len(content))
        return str(file_path)

    def _save_to_s3(
        self,
        content: bytes,
        file_name: str,
        mime_type: str | None = None,
    ) -> str:
        """Save file to S3."""
        if not self.s3_client or not self.s3_bucket:
            raise StorageError("S3 not configured")

        try:
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=file_name,
                Body=content,
                ContentType=mime_type or "application/pdf",
            )

            logger.info("file_saved_s3", bucket=self.s3_bucket, key=file_name)
            return f"s3://{self.s3_bucket}/{file_name}"

        except ClientError as e:
            logger.error("s3_upload_failed", error=str(e))
            raise StorageError(f"Failed to upload to S3: {e}")

    def get_file(self, file_path: str) -> BinaryIO:
        """Get file content."""
        if file_path.startswith("s3://"):
            return self._get_from_s3(file_path)
        else:
            path = Path(file_path)
            if not path.exists():
                raise StorageError(f"File not found: {file_path}")
            return open(path, "rb")

    def _get_from_s3(self, s3_url: str) -> BinaryIO:
        """Get file from S3."""
        if not self.s3_client:
            raise StorageError("S3 not configured")

        # Parse s3://bucket/key
        parts = s3_url.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            return io.BytesIO(response["Body"].read())
        except ClientError as e:
            raise StorageError(f"Failed to get from S3: {e}")

    def delete_file(self, file_path: str) -> None:
        """Delete a file."""
        if file_path.startswith("s3://"):
            self._delete_from_s3(file_path)
        else:
            path = Path(file_path)
            if path.exists():
                path.unlink()
                logger.info("file_deleted_local", path=str(path))

    def _delete_from_s3(self, s3_url: str) -> None:
        """Delete file from S3."""
        if not self.s3_client:
            return

        parts = s3_url.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""

        try:
            self.s3_client.delete_object(Bucket=bucket, Key=key)
            logger.info("file_deleted_s3", bucket=bucket, key=key)
        except ClientError as e:
            logger.warning("s3_delete_failed", error=str(e))

"""File storage service."""
import base64
import shutil
from pathlib import Path

from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import get_logger

logger = get_logger(__name__)

class FileValidationError(Exception):
    pass

class StorageService:
    def __init__(self):
        self.local_path = Path(settings.storage_local_path)
        self.local_path.mkdir(parents=True, exist_ok=True)

    def validate_file(self, content: bytes, file_name: str, mime_type: str | None = None) -> None:
        size = len(content)
        max_size = settings.max_file_size_mb * 1024 * 1024
        if size > max_size:
            raise FileValidationError(f"File size exceeds maximum allowed ({settings.max_file_size_mb}MB)")
        if not file_name.lower().endswith(".pdf"):
            raise FileValidationError("File must be a PDF")

    def save_from_base64(self, base64_content: str, file_name: str, session_id: str) -> str:
        content = base64.b64decode(base64_content)
        self.validate_file(content, file_name, "application/pdf")
        
        session_dir = self.local_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = session_dir / file_name
        file_path.write_bytes(content)
        return str(file_path)

    def save_from_local_path(self, source_path: str, file_name: str, session_id: str) -> str:
        source = Path(source_path)
        if not source.exists():
            raise FileValidationError(f"File not found: {source_path}")
            
        content = source.read_bytes()
        self.validate_file(content, file_name)
        
        session_dir = self.local_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        
        dest_path = session_dir / file_name
        shutil.copy(source, dest_path)
        return str(dest_path)

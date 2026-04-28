"""Session management for standalone API."""
import json
import os
import shutil
from pathlib import Path
from typing import Any

from quotation_extraction.core.config import settings
from quotation_extraction.core.logging_config import get_logger

# Optional upstash-redis import
try:
    from upstash_redis import Redis
except ImportError:
    Redis = None

logger = get_logger(__name__)

class SessionManager:
    """Manages ephemeral sessions and their temp directories. Uses Upstash Redis if configured."""
    
    def __init__(self):
        self.temp_dir = Path(settings.storage_local_path)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_file = self.temp_dir / "sessions.json"
        
        self.redis = None
        if settings.upstash_redis_rest_url and settings.upstash_redis_rest_token and Redis:
            try:
                self.redis = Redis(
                    url=settings.upstash_redis_rest_url,
                    token=settings.upstash_redis_rest_token
                )
                logger.info("Upstash Redis initialized for session management")
            except Exception as e:
                logger.error("redis_init_failed", error=str(e))
        
    def _read_sessions(self) -> dict:
        if not self.sessions_file.exists():
            return {}
        try:
            return json.loads(self.sessions_file.read_text())
        except Exception:
            return {}
            
    def _write_sessions(self, sessions: dict) -> None:
        self.sessions_file.write_text(json.dumps(sessions, indent=2))
        
    def init_session(self, session_id: str, file_name: str) -> None:
        session_data = {
            "status": "pending",
            "file_name": file_name,
            "error": None,
            "result": None
        }
        
        if self.redis:
            self.redis.set(f"session:{session_id}", json.dumps(session_data), ex=86400) # 24h expiration
        else:
            sessions = self._read_sessions()
            sessions[session_id] = session_data
            self._write_sessions(sessions)
        
    def update_session(self, session_id: str, status: str, result: Any = None, error: str | None = None, excel_base64: str | None = None) -> None:
        if self.redis:
            val = self.redis.get(f"session:{session_id}")
            if val:
                session_data = val if isinstance(val, dict) else json.loads(val)
                session_data["status"] = status
                if result:
                    session_data["result"] = result
                if error:
                    session_data["error"] = error
                if excel_base64:
                    session_data["excel_base64"] = excel_base64
                self.redis.set(f"session:{session_id}", json.dumps(session_data), ex=86400)
        else:
            sessions = self._read_sessions()
            if session_id in sessions:
                sessions[session_id]["status"] = status
                if result:
                    sessions[session_id]["result"] = result
                if error:
                    sessions[session_id]["error"] = error
                if excel_base64:
                    sessions[session_id]["excel_base64"] = excel_base64
                self._write_sessions(sessions)
            
    def get_session(self, session_id: str) -> dict | None:
        if self.redis:
            val = self.redis.get(f"session:{session_id}")
            if val:
                return val if isinstance(val, dict) else json.loads(val)
            return None
        return self._read_sessions().get(session_id)
        
    def cleanup_session(self, session_id: str) -> None:
        """Remove the session's temp directory and track status."""
        session_dir = self.temp_dir / session_id
        if session_dir.exists():
            try:
                shutil.rmtree(session_dir)
            except Exception as e:
                logger.error("session_cleanup_failed", session_id=session_id, error=str(e))
        
        # We don't delete from Redis/JSON immediately so the user can fetch the final result.
        # Redis has TTL, JSON can be pruned by cron.

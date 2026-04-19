import json
import logging
import threading
from datetime import datetime, timedelta, timezone
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Standalone session tracking file in the root
SESSION_FILE = Path("sessions_standalone.json")
TEMP_DIR = Path("temp")
_json_lock = threading.Lock()

# Standard library IST Timezone
IST = timezone(timedelta(hours=5, minutes=30), name="IST")

def get_ist_now() -> datetime:
    """Returns the current aware datetime in IST."""
    return datetime.now(IST)

def _read_sessions() -> dict[str, Any]:
    """Reads session JSON safely without lock (must be called within a lock)."""
    if not SESSION_FILE.exists():
        return {}
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    except Exception as e:
        logger.error(f"Error reading sessions JSON: {e}")
        return {}

def _write_sessions(data: dict[str, Any]):
    """Writes session JSON safely without lock (must be called within a lock)."""
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error writing sessions JSON: {e}")

def cleanup_old_sessions():
    """Removes sessions whose datetimes are older than 2 hours from IST now."""
    with _json_lock:
        data = _read_sessions()
        now = get_ist_now()
        
        keys_to_delete = []
        for session_id, sdata in data.items():
            dt_str = sdata.get("datetime")
            if dt_str:
                try:
                    dt = datetime.fromisoformat(dt_str)
                    if (now - dt) > timedelta(hours=2):
                        keys_to_delete.append(session_id)
                except ValueError:
                    # Malformed date, prune it
                    keys_to_delete.append(session_id)
        
        if keys_to_delete:
            for k in keys_to_delete:
                del data[k]
                
                # Delete corresponding workspace folder if it exists
                workspace = TEMP_DIR / k
                if workspace.exists() and workspace.is_dir():
                    try:
                        shutil.rmtree(workspace)
                    except Exception as e:
                        logger.error(f"Failed to delete workspace {workspace}: {e}")

            _write_sessions(data)
            logger.info(f"Cleaned up {len(keys_to_delete)} old sessions.")
            
        # Hard sweep orphans in temp/ directly based on folder modified time
        if TEMP_DIR.exists() and TEMP_DIR.is_dir():
            for folder in TEMP_DIR.iterdir():
                if folder.is_dir():
                    try:
                        mtime = datetime.fromtimestamp(folder.stat().st_mtime, IST)
                        if (now - mtime) > timedelta(hours=2):
                            shutil.rmtree(folder)
                    except Exception:
                        pass

def save_session_state(session_id: str, state: dict[str, Any]):
    """Updates the state dictionary for a specific session ID. Ensures datetime stays intact."""
    with _json_lock:
        data = _read_sessions()
        
        if session_id in data:
            data[session_id].update(state)
        else:
            data[session_id] = state
            data[session_id]["datetime"] = get_ist_now().isoformat()
            
        _write_sessions(data)

def get_session_state(session_id: str) -> dict[str, Any] | None:
    """Runs a cleanup operation, then returns the state of the session_id if present."""
    cleanup_old_sessions()
    
    with _json_lock:
        data = _read_sessions()
        return data.get(session_id)

def get_session_workspace(session_id: str) -> Path:
    """Returns the workspace path for the given session ID."""
    return TEMP_DIR / session_id

def create_session_workspace(session_id: str) -> Path:
    """Creates and returns the session workspace directory."""
    workspace = get_session_workspace(session_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace

def delete_session_workspace(session_id: str):
    """Permanently deletes the session workspace."""
    workspace = get_session_workspace(session_id)
    if workspace.exists() and workspace.is_dir():
        try:
            shutil.rmtree(workspace)
            logger.info(f"Deleted workspace for {session_id}")
        except Exception as e:
            logger.error(f"Failed to delete workspace {session_id}: {e}")


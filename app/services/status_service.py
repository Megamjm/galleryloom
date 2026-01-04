import threading
import time
from typing import Any, Dict, Optional

_lock = threading.Lock()
_status: Dict[str, Any] = {
    "state": "standby",
    "message": "Idle",
    "progress": None,
    "meta": {},
    "updated_at": time.time(),
}


def set_status(state: str, message: Optional[str] = None, progress: Optional[float] = None, meta: Optional[Dict[str, Any]] = None):
    with _lock:
        _status.update(
            {
                "state": state,
                "message": message or _status.get("message", ""),
                "progress": progress,
                "meta": meta or _status.get("meta", {}),
                "updated_at": time.time(),
            }
        )


def get_status() -> Dict[str, Any]:
    with _lock:
        return dict(_status)

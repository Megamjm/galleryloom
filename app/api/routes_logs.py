from collections import deque
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Query

from app.core.config import settings as env_settings

router = APIRouter(prefix="/logs", tags=["logs"])


def _tail(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    buf: deque[str] = deque(maxlen=lines)
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            buf.append(line.rstrip("\n"))
    return list(buf)


@router.get("/")
async def read_logs(level: Literal["info", "debug"] = Query(default="info"), lines: int = Query(default=200, ge=1, le=1000)):
    log_dir = Path(env_settings.config_root) / "logs"
    filename = "galleryloom.log" if level == "info" else "galleryloom-debug.log"
    path = log_dir / filename
    return {
        "path": str(path),
        "level": level,
        "exists": path.exists(),
        "lines": _tail(path, lines),
    }

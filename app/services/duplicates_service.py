import json
from pathlib import Path
from typing import Iterable, Set

from app.core.config import settings as env_settings


def _ack_file() -> Path:
    return Path(env_settings.config_root) / "duplicates_ack.json"


def load_acknowledged() -> Set[str]:
    path = _ack_file()
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
        return set(data if isinstance(data, list) else [])
    except Exception:
        return set()


def mark_acknowledged(keys: Iterable[str]) -> None:
    existing = load_acknowledged()
    existing.update(keys)
    path = _ack_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(existing)))

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DiskInfo, SettingsOut, SystemInfo
from app.core.config import APP_VERSION, settings as env_settings
from app.core.db import get_session
from app.services.settings_service import get_settings

router = APIRouter(prefix="/system", tags=["system"])


def _stat_path(path: str) -> DiskInfo:
    try:
        st = os.statvfs(path)
        total = st.f_frsize * st.f_blocks
        free = st.f_frsize * st.f_bfree
        avail = st.f_frsize * st.f_bavail
    except Exception:  # pragma: no cover - platform dependent
        total = free = avail = 0
    return DiskInfo(path=str(path), total_bytes=total, free_bytes=free, available_bytes=avail)


def _resolve_commit() -> str | None:
    for key in ("GIT_COMMIT", "SOURCE_COMMIT", "COMMIT"):
        val = os.getenv(key)
        if val:
            return val
    repo_root = Path(__file__).resolve().parents[2]
    git_dir = repo_root / ".git"
    if git_dir.exists():
        try:
            commit = (
                subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, text=True)
                .strip()
            )
            return commit or None
        except Exception:
            return None
    return None


def _duplicates_available() -> bool:
    path = Path(env_settings.duplicates_root)
    return path.exists() and path.is_dir() and os.access(path, os.W_OK)


@router.get("/", response_model=SystemInfo)
async def system_info(session: AsyncSession = Depends(get_session)):
    settings_payload = await get_settings(session)
    settings_out = SettingsOut(**settings_payload.model_dump(), updated_at=None)
    disk_output = _stat_path(env_settings.output_root)
    disk_config = _stat_path(env_settings.config_root)
    return SystemInfo(
        data_root=str(env_settings.data_root),
        output_root=str(env_settings.output_root),
        config_root=str(env_settings.config_root),
        duplicates_root=str(env_settings.duplicates_root),
        tmp_root=str(env_settings.tmp_root),
        temp_dir=str(env_settings.temp_dir) if env_settings.temp_dir else None,
        browse_roots=[str(root) for root in env_settings.allowed_browse_roots],
        puid=env_settings.puid,
        pgid=env_settings.pgid,
        duplicates_enabled=settings_payload.duplicates_enabled and _duplicates_available(),
        settings=settings_out,
        disk_output=disk_output,
        disk_config=disk_config,
        version=APP_VERSION,
        commit=_resolve_commit(),
    )

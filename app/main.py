import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes_activity import router as activity_router
from app.api.routes_fs import router as fs_router
from app.api.routes_health import router as health_router
from app.api.routes_logs import router as logs_router
from app.api.routes_galleries import router as galleries_router
from app.api.routes_scan import router as scan_router
from app.api.routes_settings import router as settings_router
from app.api.routes_sources import router as sources_router
from app.api.routes_system import router as system_router
from app.api.routes_status import router as status_router
from app.api.routes_exclusions import router as exclusions_router
from app.core.config import APP_VERSION, settings as env_settings
from app.core.db import init_db, SessionLocal
from app.core.logging_utils import setup_logging, reconfigure_logging
from app.services.settings_service import get_settings
from app.worker.jobs import start_worker
from app.worker.auto_scan import start_auto_scan_thread

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = BASE_DIR / "ui"

app = FastAPI(title="GalleryLoom", version=APP_VERSION)


def _ensure_dir(path: Path, allow_failure: bool = False) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as exc:  # pragma: no cover - startup safety
        logging.warning("Failed to create directory %s: %s", path, exc)
        if not allow_failure:
            raise
        return False


def _chown_if_requested(path: Path):
    if env_settings.puid is None and env_settings.pgid is None:
        return
    uid = env_settings.puid if env_settings.puid is not None else -1
    gid = env_settings.pgid if env_settings.pgid is not None else -1
    try:
        os.chown(path, uid, gid)
    except PermissionError as exc:  # pragma: no cover - depends on platform
        logging.warning("Could not chown %s (permission error): %s", path, exc)
    except Exception as exc:  # pragma: no cover - startup safety
        logging.warning("Could not chown %s: %s", path, exc)


@app.on_event("startup")
async def startup():
    setup_logging(Path(env_settings.config_root), debug_enabled=env_settings.debug_logging)
    created_paths = [
        Path(env_settings.config_root),
        Path(env_settings.tmp_root),
        Path(env_settings.output_root),
    ]
    if env_settings.temp_dir:
        temp_override = Path(env_settings.temp_dir)
        if temp_override not in created_paths:
            created_paths.append(temp_override)
    for path in created_paths:
        _ensure_dir(path)
        _chown_if_requested(path)
    _ensure_dir(Path(env_settings.duplicates_root), allow_failure=True)
    await init_db()
    async with SessionLocal() as session:
        saved_settings = await get_settings(session)
        if saved_settings.debug_logging != env_settings.debug_logging:
            reconfigure_logging(Path(env_settings.config_root), saved_settings.debug_logging)
    start_worker()
    start_auto_scan_thread()


def _ui_file(name: str) -> Path:
    return UI_DIR / name


@app.get("/")
async def ui_root():
    return FileResponse(_ui_file("index.html"))


@app.get("/sources")
async def ui_sources():
    return FileResponse(_ui_file("sources.html"))


@app.get("/logs")
async def ui_logs():
    return FileResponse(_ui_file("logs.html"))


@app.get("/duplicates")
async def ui_duplicates():
    return FileResponse(_ui_file("duplicates.html"))


@app.get("/galleries")
async def ui_galleries():
    return FileResponse(_ui_file("galleries.html"))


@app.get("/settings")
async def ui_settings():
    return FileResponse(_ui_file("settings.html"))


app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

app.include_router(sources_router, prefix="/api")
app.include_router(scan_router, prefix="/api")
app.include_router(activity_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(system_router, prefix="/api")
app.include_router(logs_router, prefix="/api")
app.include_router(galleries_router, prefix="/api")
app.include_router(status_router, prefix="/api")
app.include_router(exclusions_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(fs_router, prefix="/api")

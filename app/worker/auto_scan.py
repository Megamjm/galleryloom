import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

from sqlalchemy import select

from app.core.config import settings as env_settings
from app.core.db import SessionLocal
from app.core import models
from app.services.settings_service import get_settings
from app.services.scan_service import perform_scan
from app.worker.jobs import enqueue
from app.worker.queue import job_status

logger = logging.getLogger("galleryloom.auto")

_thread: threading.Thread | None = None
_stop_event = threading.Event()


@dataclass
class SourceSnapshot:
    latest_mtime: float = 0.0


def _iter_files(base: Path, exts: Iterable[str]) -> Iterable[Path]:
    extset = {e.lower().lstrip(".") for e in exts}
    for root, _, files in os.walk(base):
        files.sort()
        for name in files:
            p = Path(root) / name
            if p.is_file() and p.suffix.lower().lstrip(".") in extset:
                yield p


def _latest_mtime(base: Path, exts: Iterable[str]) -> float:
    newest = 0.0
    for p in _iter_files(base, exts):
        try:
            m = p.stat().st_mtime
            if m > newest:
                newest = m
        except FileNotFoundError:
            continue
    return newest


def _any_job_running() -> bool:
    return any(status == "running" for status in job_status.values())


def _enqueue_scan(reason: str):
    async def _job():
        async with SessionLocal() as session:
            await perform_scan(session, dry_run=False)

    job_id = enqueue(f"scan_auto_{reason}", lambda: asyncio.run(_job()))
    logger.info("Auto scan enqueued (reason=%s) job_id=%s", reason, job_id)
    return job_id


def start_auto_scan_thread():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    logger.info("Auto-scan thread started")


def stop_auto_scan_thread():
    _stop_event.set()
    if _thread:
        _thread.join(timeout=2)


def _loop():
    last_full_scan = 0.0
    source_snapshots: Dict[int, SourceSnapshot] = {}
    last_mtime_check = 0.0
    while not _stop_event.is_set():
        try:
            if _any_job_running():
                time.sleep(5)
                continue

            settings, sources = asyncio.run(_load_settings_and_sources())
            if not settings.auto_scan_enabled:
                time.sleep(10)
                continue

            now = time.time()
            interval_secs = max(settings.auto_scan_interval_minutes, 1) * 60
            need_full = now - last_full_scan >= interval_secs

            trigger_reason = None

            if need_full:
                trigger_reason = "interval"

            if trigger_reason is None and now - last_mtime_check > 20:
                # detect changes in input files
                last_mtime_check = now
                for src in sources:
                    base = Path(env_settings.data_root) / src.path
                    if not base.exists():
                        continue
                    latest = _latest_mtime(base, list(settings.image_extensions) + list(settings.archive_extensions))
                    snap = source_snapshots.get(src.id) or SourceSnapshot(latest_mtime=latest)
                    if latest > snap.latest_mtime:
                        trigger_reason = f"change_source_{src.id}"
                        source_snapshots[src.id] = SourceSnapshot(latest_mtime=latest)
                        logger.debug("Change detected for source %s (mtime %.2f -> %.2f)", src.path, snap.latest_mtime, latest)
                        break
                    source_snapshots[src.id] = SourceSnapshot(latest_mtime=latest)

            if trigger_reason and not _any_job_running():
                job_id = _enqueue_scan(trigger_reason)
                last_full_scan = now
                logger.debug("Scheduled auto scan (%s) job_id=%s", trigger_reason, job_id)

        except Exception:
            logger.error("Auto-scan loop error", exc_info=True)
        time.sleep(5)


async def _load_settings_and_sources():
    async with SessionLocal() as session:
        settings = await get_settings(session)
        result = await session.execute(select(models.Source).where(models.Source.enabled == True))  # noqa: E712
        sources = result.scalars().all()
        return settings, sources

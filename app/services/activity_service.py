import json
import logging
from typing import Any, Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import models
from app.worker.jobs import get_current_job_id

logger = logging.getLogger("galleryloom")
_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


async def log_activity(session: AsyncSession, level: str, message: str, payload: Any | None = None):
    payload_obj = payload or {}
    if not isinstance(payload_obj, dict):
        payload_obj = {"data": payload_obj}
    job_id = payload_obj.get("job_id") or get_current_job_id()
    if job_id:
        payload_obj["job_id"] = job_id
    payload_json = json.dumps(payload_obj)
    entry = models.Activity(level=level.upper(), message=message, payload_json=payload_json)
    session.add(entry)
    await session.commit()
    logger.log(_LEVELS.get(level.upper(), logging.INFO), "%s :: %s", message, payload_json)


async def fetch_recent_activity(session: AsyncSession, limit: int = 100) -> Sequence[models.Activity]:
    stmt = select(models.Activity).order_by(desc(models.Activity.ts)).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()

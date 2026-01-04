from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import Exclusion, ExclusionCreate, ExclusionResult
from app.core import models
from app.core.config import settings as env_settings
from app.core.db import get_session

router = APIRouter(prefix="/exclusions", tags=["exclusions"])


def _sanitize(path: str) -> Path:
    cleaned = path.strip().lstrip("/")
    candidate = Path(cleaned)
    if ".." in candidate.parts:
        raise HTTPException(status_code=400, detail="Path must not contain ..")
    return candidate


async def _remove_outputs_for_path(session: AsyncSession, rel_path: Path) -> int:
    data_root = Path(env_settings.data_root)
    target_root = Path(env_settings.output_root)
    abs_path = data_root / rel_path
    result = await session.execute(select(models.ArchiveRecord))
    records = result.scalars().all()
    removed = 0
    for rec in records:
        try:
            src = Path(rec.source_path)
            if not src.is_relative_to(abs_path):
                continue
        except Exception:
            continue
        target = Path(rec.target_path)
        try:
            target.relative_to(target_root)
        except Exception:
            continue
        if target.exists():
            if target.is_dir():
                import shutil

                shutil.rmtree(target, ignore_errors=True)
            else:
                try:
                    target.unlink()
                except Exception:
                    pass
        await session.delete(rec)
        removed += 1
    await session.commit()
    return removed


@router.get("/", response_model=List[Exclusion])
async def list_exclusions(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(models.Exclusion).order_by(models.Exclusion.created_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=ExclusionResult)
async def add_exclusion(payload: ExclusionCreate, session: AsyncSession = Depends(get_session)):
    rel = _sanitize(payload.path)
    exists = await session.execute(select(models.Exclusion).where(models.Exclusion.path == str(rel)))
    if existing := exists.scalars().first():
        removed = await _remove_outputs_for_path(session, rel)
        return ExclusionResult(exclusion=existing, removed=removed)
    exclusion = models.Exclusion(path=str(rel))
    session.add(exclusion)
    await session.commit()
    await session.refresh(exclusion)
    removed = await _remove_outputs_for_path(session, rel)
    return ExclusionResult(exclusion=exclusion, removed=removed)


@router.delete("/{exclusion_id}")
async def delete_exclusion(exclusion_id: int, session: AsyncSession = Depends(get_session)):
    exclusion = await session.get(models.Exclusion, exclusion_id)
    if not exclusion:
        raise HTTPException(status_code=404, detail="Not found")
    await session.delete(exclusion)
    await session.commit()
    return {"status": "deleted"}

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.schemas import SourceCreate, SourceUpdate, SourceOut
from app.core import models
from app.core.db import get_session

router = APIRouter(prefix="/sources", tags=["sources"])

def _sanitize_path(path: str) -> str:
    cleaned = path.strip()
    while cleaned.startswith("/"):
        cleaned = cleaned[1:]
    if ".." in cleaned.split("/"):
        raise HTTPException(status_code=400, detail="Path must be under /data without .. components")
    return cleaned

@router.get("/", response_model=list[SourceOut])
async def list_sources(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(models.Source).order_by(models.Source.created_at.desc()))
    return result.scalars().all()

@router.post("/", response_model=SourceOut)
async def create_source(payload: SourceCreate, session: AsyncSession = Depends(get_session)):
    cleaned_path = _sanitize_path(payload.path)
    source = models.Source(
        name=payload.name,
        path=cleaned_path,
        enabled=payload.enabled,
        scan_mode=payload.scan_mode,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source

@router.patch("/{source_id}", response_model=SourceOut)
async def update_source(source_id: int, payload: SourceUpdate, session: AsyncSession = Depends(get_session)):
    source = await session.get(models.Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if payload.name is not None:
        source.name = payload.name
    if payload.path is not None:
        source.path = _sanitize_path(payload.path)
    if payload.enabled is not None:
        source.enabled = payload.enabled
    if payload.scan_mode is not None:
        source.scan_mode = payload.scan_mode
    await session.commit()
    await session.refresh(source)
    return source

@router.delete("/{source_id}")
async def delete_source(source_id: int, session: AsyncSession = Depends(get_session)):
    source = await session.get(models.Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await session.delete(source)
    await session.commit()
    return {"status": "deleted"}

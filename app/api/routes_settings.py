from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.schemas import SettingsOut, SettingsUpdate
from app.core import models
from app.core.db import get_session
from app.services.settings_service import get_settings, update_settings

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("/", response_model=SettingsOut)
async def read_settings(session: AsyncSession = Depends(get_session)):
    settings = await get_settings(session)
    row = (await session.execute(select(models.SettingsRow).limit(1))).scalars().first()
    return SettingsOut(**settings.model_dump(), updated_at=row.updated_at if row else None)

@router.put("/", response_model=SettingsOut)
async def put_settings(payload: SettingsUpdate, session: AsyncSession = Depends(get_session)):
    updated = await update_settings(session, payload)
    row = (await session.execute(select(models.SettingsRow).limit(1))).scalars().first()
    return SettingsOut(**updated.model_dump(), updated_at=row.updated_at if row else None)

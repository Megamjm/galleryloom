from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.schemas import ActivityOut
from app.core.db import get_session
from app.services.activity_service import fetch_recent_activity

router = APIRouter(prefix="/activity", tags=["activity"])

@router.get("/", response_model=list[ActivityOut])
async def recent_activity(limit: int = Query(default=50, ge=1, le=500), session: AsyncSession = Depends(get_session)):
    entries = await fetch_recent_activity(session, limit=limit)
    return entries

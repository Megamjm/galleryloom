import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.schemas import DiffResult, LastScans, ScanResult
from app.core.db import get_session, SessionLocal
from app.services.scan_service import compute_diff, get_last_results, perform_scan
from app.worker.jobs import enqueue, job_status

router = APIRouter(prefix="/scan", tags=["scan"])

@router.post("/dryrun", response_model=ScanResult)
async def dry_run_scan(session: AsyncSession = Depends(get_session)):
    return await perform_scan(session, dry_run=True)

@router.post("/diff", response_model=DiffResult)
async def diff_scan(session: AsyncSession = Depends(get_session)):
    return await compute_diff(session)

@router.get("/last", response_model=LastScans)
async def last_scans():
    return get_last_results()

@router.post("/run")
async def run_scan():
    async def _job():
        async with SessionLocal() as job_session:
            await perform_scan(job_session, dry_run=False)

    job_id = enqueue("scan_run", lambda: asyncio.run(_job()))
    return {"job_id": job_id, "status": "queued"}

@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    status = job_status(job_id)
    return {"job_id": job_id, "status": status or "unknown"}

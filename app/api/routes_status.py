from fastapi import APIRouter

from app.api.schemas import LastScans
from app.services.scan_service import get_last_results
from app.services.status_service import get_status
from app.worker.queue import job_status, job_queue

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/")
async def current_status():
    status = get_status()
    last = get_last_results()
    queue_depth = job_queue.qsize()
    running_jobs = [jid for jid, st in job_status.items() if st == "running"]
    return {
        "status": status,
        "queue_depth": queue_depth,
        "running_jobs": running_jobs,
        "last_results": LastScans(**last).model_dump(),
    }

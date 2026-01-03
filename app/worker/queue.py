import logging
import queue
import threading
from dataclasses import dataclass
from typing import Callable, Any
from uuid import uuid4

logger = logging.getLogger("galleryloom.worker")

@dataclass
class Job:
    id: str
    name: str
    fn: Callable[[], Any]

job_queue: "queue.Queue[Job]" = queue.Queue()
job_status: dict[str, str] = {}
_status_lock = threading.Lock()

def enqueue_job(name: str, fn: Callable[[], Any]) -> str:
    job_id = str(uuid4())
    with _status_lock:
        job_status[job_id] = "queued"
    job_queue.put(Job(id=job_id, name=name, fn=fn))
    logger.debug("Enqueued job %s (%s)", job_id, name)
    return job_id

def set_status(job_id: str, status: str):
    with _status_lock:
        job_status[job_id] = status

def get_status(job_id: str) -> str | None:
    with _status_lock:
        return job_status.get(job_id)

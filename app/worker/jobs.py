import logging
import threading
import traceback
from .queue import job_queue, Job, set_status, get_status, enqueue_job

logger = logging.getLogger("galleryloom.worker")
_worker_started = False
_job_ctx = threading.local()


def get_current_job_id() -> str | None:
    return getattr(_job_ctx, "job_id", None)

def start_worker():
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    def run():
        while True:
            job: Job = job_queue.get()
            set_status(job.id, "running")
            logger.debug("Worker starting job %s (%s)", job.id, job.name)
            try:
                _job_ctx.job_id = job.id
                job.fn()
                set_status(job.id, "done")
                logger.debug("Worker completed job %s", job.id)
            except Exception:
                set_status(job.id, "failed")
                logger.error("Job failed %s: %s", job.name, traceback.format_exc())
            finally:
                _job_ctx.job_id = None
                job_queue.task_done()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    logger.info("Worker started")

def enqueue(name: str, fn):
    return enqueue_job(name, fn)

def job_status(job_id: str) -> str | None:
    return get_status(job_id)

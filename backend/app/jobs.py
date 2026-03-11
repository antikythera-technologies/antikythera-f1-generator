"""Job enqueue utilities for the RQ task queue.

Provides a simple interface to enqueue pipeline jobs onto the Redis-backed
RQ queue. The actual work is executed by the worker process defined in
``app.worker``.
"""

import logging
from typing import Optional

from redis import Redis
from rq import Queue
from rq.job import Job

from app.config import settings

logger = logging.getLogger(__name__)

# Queue name used across the project
PIPELINE_QUEUE = "f1-pipeline"

# Pipeline jobs can run for up to 2 hours (image gen + stitching is slow)
DEFAULT_JOB_TIMEOUT = 7200  # seconds


def get_redis_connection() -> Redis:
    """Get a Redis connection from settings."""
    return Redis.from_url(settings.REDIS_URL)


def get_queue() -> Queue:
    """Get the pipeline RQ queue."""
    return Queue(PIPELINE_QUEUE, connection=get_redis_connection())


def enqueue_pipeline(episode_id: int, job_timeout: int = DEFAULT_JOB_TIMEOUT) -> str:
    """
    Enqueue a video pipeline job for the given episode.

    Args:
        episode_id: ID of the Episode record to process.
        job_timeout: Maximum seconds the job may run (default 2 hours).

    Returns:
        The RQ job ID (a UUID string).
    """
    queue = get_queue()

    # The function path that the worker will import and call.
    # It must be a top-level function importable by the worker process.
    job: Job = queue.enqueue(
        "app.jobs._run_pipeline",
        episode_id,
        job_timeout=job_timeout,
        result_ttl=86400,       # keep result for 24 h
        failure_ttl=604800,     # keep failure info for 7 days
        meta={"episode_id": episode_id},
    )

    logger.info(
        f"Enqueued pipeline job {job.id} for episode {episode_id} "
        f"(timeout={job_timeout}s)"
    )
    return job.id


def get_job_status(job_id: str) -> Optional[dict]:
    """
    Get the status of an RQ job.

    Returns a dict with keys ``status``, ``meta``, ``result``, ``error``
    or ``None`` if the job does not exist.
    """
    try:
        job = Job.fetch(job_id, connection=get_redis_connection())
        return {
            "id": job.id,
            "status": job.get_status(),
            "meta": job.meta,
            "result": job.result,
            "error": job.exc_info if job.is_failed else None,
            "enqueued_at": str(job.enqueued_at) if job.enqueued_at else None,
            "started_at": str(job.started_at) if job.started_at else None,
            "ended_at": str(job.ended_at) if job.ended_at else None,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# The function that the RQ worker actually executes.
# It MUST be importable as a top-level function — RQ pickles the dotted path.
# Because VideoPipeline.run() is async, we bridge with asyncio.run().
# ---------------------------------------------------------------------------

def _run_pipeline(episode_id: int) -> str:
    """
    Synchronous wrapper executed by the RQ worker.

    Bridges into the async VideoPipeline via ``asyncio.run()``.
    Creates a fresh DB engine to avoid issues with forked asyncpg
    connections from the parent process.
    """
    import asyncio
    import sys

    # Ensure child process logs go to stdout (captured by docker)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )

    logger.info(f"RQ worker starting pipeline for episode {episode_id}")

    # Replace the module-level engine with a fresh one.
    # The forked child inherits stale asyncpg connections that deadlock
    # when disposed. Creating a fresh engine is safer.
    import app.database as db_module
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.config import settings

    db_module.engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )
    db_module.async_session_maker = async_sessionmaker(
        db_module.engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    from app.pipeline.video_pipeline import VideoPipeline

    pipeline = VideoPipeline(episode_id)
    result = asyncio.run(pipeline.run())

    logger.info(f"RQ worker completed pipeline for episode {episode_id}: {result}")
    return result

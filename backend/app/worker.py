"""RQ Worker for persistent background job processing.

Runs as a standalone process (``python -m app.worker``) that:
1. Connects to Redis and listens on the ``f1-pipeline`` queue.
2. Executes enqueued video-pipeline jobs that survive API restarts.
3. Periodically polls for ScheduledJob records whose ``scheduled_for``
   time has passed and enqueues them automatically.

Usage::

    # Inside the Docker worker container (or locally for development)
    python -m app.worker
"""

import asyncio
import logging
import signal
import sys
import threading
import time
from datetime import datetime

from redis import Redis
from rq import Worker

from app.config import settings
from app.jobs import PIPELINE_QUEUE, get_redis_connection, enqueue_pipeline

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("f1.worker")


# ---------------------------------------------------------------------------
# Scheduler poll loop — runs in a background thread
# ---------------------------------------------------------------------------

# Flag to signal a clean shutdown
_shutdown_event = threading.Event()


def _scheduler_poll_loop(interval_seconds: int = 60) -> None:
    """
    Background thread that checks for pending ScheduledJob records.

    Every *interval_seconds* it queries the database for jobs whose
    ``scheduled_for`` has passed and status is SCHEDULED, creates an
    Episode record, enqueues the pipeline, and marks the job RUNNING.
    """
    logger.info(
        f"Scheduler poll loop started (interval={interval_seconds}s)"
    )

    while not _shutdown_event.is_set():
        try:
            asyncio.run(_process_pending_jobs())
        except Exception as exc:
            logger.error(f"Scheduler poll error: {exc}", exc_info=True)

        # Sleep in small increments so we respond to shutdown quickly
        for _ in range(interval_seconds):
            if _shutdown_event.is_set():
                break
            time.sleep(1)

    logger.info("Scheduler poll loop stopped")


async def _process_pending_jobs() -> None:
    """Find and enqueue any ScheduledJob records that are due."""
    from app.database import async_session_maker
    from app.models import ScheduledJob, JobStatus, Episode, EpisodeStatus
    from app.services.scheduler import SchedulerService

    async with async_session_maker() as session:
        service = SchedulerService(session)
        pending_jobs = await service.get_pending_jobs(limit=10)

        if not pending_jobs:
            return

        logger.info(f"Found {len(pending_jobs)} pending scheduled job(s)")

        for job in pending_jobs:
            try:
                # Determine episode type from trigger
                episode_type = service.map_trigger_to_episode_type(job.trigger_type)

                # Build a title
                title = job.description or f"Scheduled {episode_type.value} episode"

                # Create an Episode record
                episode = Episode(
                    race_id=job.race_id,
                    episode_type=episode_type,
                    title=title,
                    status=EpisodeStatus.PENDING,
                )
                session.add(episode)

                # Link episode and mark job running in one commit
                await session.flush()  # get episode.id
                job.status = JobStatus.RUNNING
                job.started_at = datetime.utcnow()
                job.episode_id = episode.id
                await session.commit()

                # Enqueue the pipeline (after DB is consistent)
                rq_job_id = enqueue_pipeline(episode.id)

                logger.info(
                    f"Scheduled job {job.id} -> episode {episode.id}, "
                    f"RQ job {rq_job_id}"
                )
            except Exception as exc:
                logger.error(
                    f"Failed to enqueue scheduled job {job.id}: {exc}",
                    exc_info=True,
                )
                await session.rollback()
                # Mark the job as failed so it can be retried or inspected
                try:
                    await service.mark_job_failed(job, str(exc))
                except Exception:
                    logger.error(
                        f"Could not mark job {job.id} as failed", exc_info=True
                    )


# ---------------------------------------------------------------------------
# Worker entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the RQ worker with the scheduler poll loop."""

    conn: Redis = get_redis_connection()

    # Verify Redis is reachable
    try:
        conn.ping()
        logger.info(f"Connected to Redis at {settings.REDIS_URL}")
    except Exception as exc:
        logger.error(f"Cannot reach Redis at {settings.REDIS_URL}: {exc}")
        sys.exit(1)

    # Start the scheduler poll thread
    poll_interval = settings.TRIGGER_CHECK_INTERVAL_MINUTES * 60
    poll_thread = threading.Thread(
        target=_scheduler_poll_loop,
        args=(poll_interval,),
        daemon=True,
        name="scheduler-poll",
    )
    poll_thread.start()

    # Graceful shutdown handler
    def _handle_signal(signum, frame):
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        _shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Create and start the RQ worker
    logger.info(f"Starting RQ worker on queue '{PIPELINE_QUEUE}'")
    worker = Worker(
        queues=[PIPELINE_QUEUE],
        connection=conn,
        name=f"f1-worker-{settings.APP_ENV}",
    )

    worker.work(
        with_scheduler=False,  # We use our own poll loop, not RQ's scheduler
        logging_level=settings.LOG_LEVEL,
    )

    # If worker.work() returns (e.g. on shutdown signal), clean up
    _shutdown_event.set()
    poll_thread.join(timeout=5)
    logger.info("Worker shut down cleanly")


if __name__ == "__main__":
    main()

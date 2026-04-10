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

    Uses a PERSISTENT event loop to avoid connection leaks.
    asyncio.run() creates/destroys event loops each call, which
    orphans DB connections as "idle in transaction". A persistent
    loop reuses the same connection pool properly.
    """
    logger.info(
        f"Scheduler poll loop started (interval={interval_seconds}s)"
    )

    # Create a persistent event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        while not _shutdown_event.is_set():
            try:
                loop.run_until_complete(_process_pending_jobs())
            except Exception as exc:
                logger.error(f"Scheduler poll error: {exc}", exc_info=True)

            # Sleep in small increments so we respond to shutdown quickly
            for _ in range(interval_seconds):
                if _shutdown_event.is_set():
                    break
                time.sleep(1)
    finally:
        # Clean up: close the event loop and any remaining connections
        try:
            # Dispose the engine to release all pooled connections
            from app.database import engine
            loop.run_until_complete(engine.dispose())
            logger.info("Scheduler: DB engine disposed")
        except Exception:
            pass
        loop.close()
        logger.info("Scheduler poll loop stopped")


async def _process_pending_jobs() -> None:
    """Find and enqueue any ScheduledJob records that are due."""
    from sqlalchemy import select

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

                # Check if episode already exists for this race + type
                existing_stmt = select(Episode).where(
                    Episode.race_id == job.race_id,
                    Episode.episode_type == episode_type,
                )
                existing_result = await session.execute(existing_stmt)
                existing_episode = existing_result.scalar_one_or_none()

                if existing_episode:
                    logger.info(
                        f"Episode already exists for race {job.race_id} "
                        f"type {episode_type.value}: episode {existing_episode.id} "
                        f"(status={existing_episode.status.value}) — skipping"
                    )
                    job.status = JobStatus.COMPLETED
                    job.completed_at = datetime.utcnow()
                    job.episode_id = existing_episode.id
                    await session.commit()
                    continue

                # Guard: NEVER create an episode without a race_id
                # Weekly recaps with no race context produce garbage scripts
                if job.race_id is None:
                    logger.warning(
                        f"Scheduled job {job.id} has no race_id — skipping. "
                        f"Episodes require a race for circuit/driver context."
                    )
                    job.status = JobStatus.FAILED
                    job.error_message = "No race_id — cannot generate without race context"
                    job.completed_at = datetime.utcnow()
                    await session.commit()
                    continue

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

"""Dispatch of deferred file processing.

With `GEOAPI_REDIS_URL` set, jobs go to a Redis-backed RQ queue and run in separate worker
processes (`rq worker file-processing`), so queued work survives API restarts and scales
horizontally. Without it, FastAPI's in-process BackgroundTasks are used, which keeps local
development free of extra services.
"""

import logging
import uuid
from functools import lru_cache

from fastapi import BackgroundTasks
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import create_session_factory
from app.errors import QueueUnavailableError
from app.services import processing

logger = logging.getLogger(__name__)

QUEUE_NAME = "file-processing"


def dispatch_processing(
    file_id: uuid.UUID,
    settings: Settings,
    session_factory: sessionmaker[Session],
    background_tasks: BackgroundTasks,
) -> None:
    if settings.redis_url is None:
        background_tasks.add_task(
            processing.process_in_background, session_factory, file_id, settings
        )
        return
    try:
        get_queue(settings.redis_url).enqueue(
            run_processing_job,
            str(file_id),
            job_id=f"process-{file_id}",
            job_timeout=settings.job_timeout_seconds,
        )
    except RedisError as exc:
        logger.error("Could not enqueue file %s: %s", file_id, exc)
        raise QueueUnavailableError(
            "The processing queue is unavailable; try again later.",
            details={"file_id": str(file_id)},
        ) from None


@lru_cache(maxsize=4)
def get_queue(redis_url: str) -> Queue:
    return Queue(QUEUE_NAME, connection=Redis.from_url(redis_url))


def run_processing_job(file_id: str) -> None:
    """RQ job entry point. Runs in the worker process, configured from GEOAPI_* env vars."""
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    processing.process_in_background(
        _session_factory(settings.resolved_database_url), uuid.UUID(file_id), settings
    )


@lru_cache(maxsize=4)
def _session_factory(database_url: str) -> sessionmaker[Session]:
    return create_session_factory(database_url)

"""Runtime settings stored in Redis — shared between API and worker processes.

The API process updates these via the settings endpoint.
The worker process reads them at job execution time.
Falls back to config.py defaults if Redis key doesn't exist.
"""

import json
import logging
from typing import Optional

import redis

from app.config import settings

logger = logging.getLogger(__name__)

REDIS_SETTINGS_KEY = "f1:pipeline:settings"


def _get_redis() -> redis.Redis:
    """Get a Redis connection using the app's configured URL."""
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_runtime_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a runtime setting from Redis, falling back to default."""
    try:
        r = _get_redis()
        data = r.hget(REDIS_SETTINGS_KEY, key)
        if data is not None:
            return data
    except Exception as e:
        logger.warning(f"Redis read failed for {key}: {e}")
    return default


def set_runtime_setting(key: str, value: str) -> None:
    """Write a runtime setting to Redis."""
    try:
        r = _get_redis()
        r.hset(REDIS_SETTINGS_KEY, key, value)
        logger.info(f"Runtime setting updated: {key}={value}")
    except Exception as e:
        logger.warning(f"Redis write failed for {key}: {e}")


def get_image_generator() -> str:
    """Get the current image generator backend."""
    return get_runtime_setting("image_generator", settings.IMAGE_GENERATOR_DEFAULT)


def get_video_generator() -> str:
    """Get the current video generator backend."""
    return get_runtime_setting("video_generator", settings.VIDEO_GENERATOR_DEFAULT)

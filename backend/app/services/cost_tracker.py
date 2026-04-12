"""Shared cost tracking for the F1 video pipeline.

Single source of truth for API cost logging and episode cost aggregation.
Called by both video_pipeline.py and jobs.py — never duplicate this logic.
"""

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.logs import APIProvider, APIUsage
from app.models.scene import Scene

logger = logging.getLogger(__name__)


async def log_api_cost(
    db: AsyncSession,
    episode_id: int,
    provider: APIProvider | str,
    endpoint: str,
    cost_usd: float,
    scene_id: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    response_time_ms: int = 0,
) -> None:
    """Log an API usage record for cost tracking.

    Args:
        db: Active database session.
        episode_id: Episode this cost belongs to.
        provider: API provider (enum or string).
        endpoint: Specific API endpoint called.
        cost_usd: Cost in USD.
        scene_id: Optional scene this cost belongs to.
        input_tokens: Token count for LLM calls.
        output_tokens: Token count for LLM calls.
        response_time_ms: Response time in milliseconds.
    """
    try:
        if isinstance(provider, str):
            provider = APIProvider(provider)

        usage = APIUsage(
            episode_id=episode_id,
            scene_id=scene_id,
            provider=provider,
            endpoint=endpoint,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=Decimal(str(cost_usd)),
            response_time_ms=response_time_ms,
        )
        db.add(usage)
        await db.flush()
        logger.debug(f"Logged API cost: {provider.value} ${cost_usd:.4f} ({endpoint})")
    except Exception as e:
        logger.warning(f"Failed to log API cost: {e}")


async def update_episode_costs(db: AsyncSession, episode_id: int) -> None:
    """Sum all scene image + video costs and update episode total.

    Uses SQL aggregate for efficiency. Includes anthropic_cost_usd from
    script generation (stored on the episode directly).
    """
    result = await db.execute(
        select(
            func.coalesce(func.sum(Scene.image_cost_usd), 0),
            func.coalesce(func.sum(Scene.video_cost_usd), 0),
        ).where(Scene.episode_id == episode_id)
    )
    img_total, vid_total = result.one()

    episode = await db.get(Episode, episode_id)
    if episode:
        anthropic_cost = episode.anthropic_cost_usd or Decimal(0)
        episode.total_cost_usd = img_total + vid_total + anthropic_cost
        await db.flush()
        logger.info(
            f"Episode {episode_id}: costs — "
            f"images=${float(img_total):.3f}, "
            f"videos=${float(vid_total):.3f}, "
            f"script=${float(anthropic_cost):.3f}, "
            f"total=${float(episode.total_cost_usd):.3f}"
        )

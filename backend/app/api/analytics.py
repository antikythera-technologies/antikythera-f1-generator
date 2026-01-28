"""Analytics API endpoints."""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode, EpisodeStatus
from app.models.logs import APIUsage, APIProvider
from app.schemas.analytics import CostAnalytics, CostBreakdown, PerformanceMetrics

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/costs", response_model=list[CostAnalytics])
async def get_costs(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    group_by: str = Query(default="day", regex="^(day|week|month|episode)$"),
    db: AsyncSession = Depends(get_db),
):
    """Get cost breakdown by period."""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()

    # Get API usage data
    stmt = select(APIUsage).where(
        APIUsage.created_at >= datetime.combine(start_date, datetime.min.time()),
        APIUsage.created_at <= datetime.combine(end_date, datetime.max.time()),
    )
    result = await db.execute(stmt)
    usage_records = result.scalars().all()

    # Aggregate by provider
    anthropic_cost = sum(
        (r.cost_usd or Decimal(0)) for r in usage_records if r.provider == APIProvider.ANTHROPIC
    )
    total_tokens = sum(
        ((r.input_tokens or 0) + (r.output_tokens or 0))
        for r in usage_records
        if r.provider == APIProvider.ANTHROPIC
    )

    # Count episodes
    episode_stmt = select(func.count(Episode.id)).where(
        Episode.created_at >= datetime.combine(start_date, datetime.min.time()),
        Episode.created_at <= datetime.combine(end_date, datetime.max.time()),
    )
    episode_result = await db.execute(episode_stmt)
    episodes_count = episode_result.scalar() or 0

    return [
        CostAnalytics(
            period=f"{start_date} to {end_date}",
            total_cost_usd=anthropic_cost,  # Ovi is free
            breakdown=CostBreakdown(
                anthropic=anthropic_cost,
                ovi=Decimal(0),  # Ovi is free
                youtube=Decimal(0),  # YouTube API is free
                storage=Decimal(0),  # TODO: Calculate MinIO costs
            ),
            episodes_generated=episodes_count,
            total_tokens=total_tokens,
        )
    ]


@router.get("/performance", response_model=PerformanceMetrics)
async def get_performance(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get generation performance metrics."""
    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()

    # Get episode stats
    stmt = select(Episode).where(
        Episode.created_at >= datetime.combine(start_date, datetime.min.time()),
        Episode.created_at <= datetime.combine(end_date, datetime.max.time()),
    )
    result = await db.execute(stmt)
    episodes = result.scalars().all()

    total = len(episodes)
    successful = sum(1 for e in episodes if e.status == EpisodeStatus.PUBLISHED)
    failed = sum(1 for e in episodes if e.status == EpisodeStatus.FAILED)

    # Calculate averages
    generation_times = [e.generation_time_seconds for e in episodes if e.generation_time_seconds]
    avg_time = sum(generation_times) / len(generation_times) / 60 if generation_times else None

    scene_counts = [e.scene_count for e in episodes]
    avg_scenes = sum(scene_counts) / len(scene_counts) if scene_counts else 0

    costs = [e.total_cost_usd for e in episodes]
    avg_cost = sum(costs) / len(costs) if costs else Decimal(0)

    return PerformanceMetrics(
        total_episodes=total,
        successful_episodes=successful,
        failed_episodes=failed,
        success_rate=(successful / total * 100) if total > 0 else 0,
        avg_generation_time_minutes=avg_time,
        avg_scenes_per_episode=avg_scenes,
        avg_cost_per_episode_usd=avg_cost,
    )


@router.get("/daily-costs")
async def get_daily_costs(
    days: int = Query(default=7, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Get daily cost breakdown."""
    start_date = date.today() - timedelta(days=days)

    stmt = select(APIUsage).where(
        APIUsage.created_at >= datetime.combine(start_date, datetime.min.time()),
    ).order_by(APIUsage.created_at)

    result = await db.execute(stmt)
    records = result.scalars().all()

    # Group by date and provider
    daily_data = {}
    for record in records:
        day = record.created_at.date().isoformat()
        provider = record.provider.value

        key = (day, provider)
        if key not in daily_data:
            daily_data[key] = {
                "date": day,
                "provider": provider,
                "api_calls": 0,
                "total_cost_usd": Decimal(0),
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "response_times": [],
            }

        daily_data[key]["api_calls"] += 1
        daily_data[key]["total_cost_usd"] += record.cost_usd or Decimal(0)
        daily_data[key]["total_input_tokens"] += record.input_tokens or 0
        daily_data[key]["total_output_tokens"] += record.output_tokens or 0
        if record.response_time_ms:
            daily_data[key]["response_times"].append(record.response_time_ms)

    # Calculate averages and format response
    results = []
    for data in daily_data.values():
        response_times = data.pop("response_times")
        data["avg_response_time_ms"] = sum(response_times) / len(response_times) if response_times else 0
        data["total_cost_usd"] = float(data["total_cost_usd"])
        results.append(data)

    return sorted(results, key=lambda x: (x["date"], x["provider"]), reverse=True)

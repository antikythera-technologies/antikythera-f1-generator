"""Analytics schemas."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class CostBreakdown(BaseModel):
    """Cost breakdown by provider."""
    anthropic: Decimal
    ovi: Decimal
    youtube: Decimal
    storage: Decimal


class CostAnalytics(BaseModel):
    """Cost analytics response."""
    period: str
    total_cost_usd: Decimal
    breakdown: CostBreakdown
    episodes_generated: int
    total_tokens: int


class PerformanceMetrics(BaseModel):
    """Performance metrics response."""
    total_episodes: int
    successful_episodes: int
    failed_episodes: int
    success_rate: float
    avg_generation_time_minutes: Optional[float]
    avg_scenes_per_episode: float
    avg_cost_per_episode_usd: Decimal


class DailyCostSummary(BaseModel):
    """Daily cost summary."""
    date: str
    provider: str
    api_calls: int
    total_cost_usd: Decimal
    total_input_tokens: int
    total_output_tokens: int
    avg_response_time_ms: float

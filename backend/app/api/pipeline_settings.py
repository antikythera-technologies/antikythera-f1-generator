"""Pipeline settings API — runtime-configurable pipeline parameters."""

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.services.runtime_settings import set_runtime_setting, get_image_generator, get_video_generator

router = APIRouter()


class PipelineSettingsResponse(BaseModel):
    """Current pipeline settings."""

    image_generator: str  # flux-lora, instant-character
    video_generator: str  # fal-ovi, fal-ltx, fal-kling-std, fal-kling-std-audio, fal-kling-pro, fal-kling-pro-audio
    tts_enabled: bool
    video_scene_count: int
    video_scene_duration_seconds: int
    ovi_quality: str
    ltx_enabled: bool


class PipelineSettingsUpdate(BaseModel):
    """Updatable pipeline settings."""

    image_generator: Optional[str] = None  # flux-lora, instant-character
    video_generator: Optional[str] = None  # Any valid backend ID
    tts_enabled: Optional[bool] = None
    ovi_quality: Optional[str] = None


@router.get("", response_model=PipelineSettingsResponse)
async def get_pipeline_settings():
    """Get current pipeline settings."""
    return PipelineSettingsResponse(
        image_generator=get_image_generator(),
        video_generator=get_video_generator(),
        tts_enabled=settings.TTS_ENABLED,
        video_scene_count=settings.VIDEO_SCENE_COUNT,
        video_scene_duration_seconds=settings.VIDEO_SCENE_DURATION_SECONDS,
        ovi_quality=settings.OVI_QUALITY,
        ltx_enabled=settings.LTX23_ENABLED,
    )


@router.put("", response_model=PipelineSettingsResponse)
async def update_pipeline_settings(update: PipelineSettingsUpdate):
    """Update pipeline settings at runtime.

    Changes are applied immediately and persist until the backend restarts.
    For permanent changes, update the .env file.
    """
    if update.image_generator is not None:
        settings.IMAGE_GENERATOR_DEFAULT = update.image_generator
        set_runtime_setting("image_generator", update.image_generator)
    if update.video_generator is not None:
        settings.VIDEO_GENERATOR_DEFAULT = update.video_generator
        set_runtime_setting("video_generator", update.video_generator)
    if update.tts_enabled is not None:
        settings.TTS_ENABLED = update.tts_enabled
    if update.ovi_quality is not None:
        settings.OVI_QUALITY = update.ovi_quality

    return PipelineSettingsResponse(
        image_generator=get_image_generator(),
        video_generator=get_video_generator(),
        tts_enabled=settings.TTS_ENABLED,
        video_scene_count=settings.VIDEO_SCENE_COUNT,
        video_scene_duration_seconds=settings.VIDEO_SCENE_DURATION_SECONDS,
        ovi_quality=settings.OVI_QUALITY,
        ltx_enabled=settings.LTX23_ENABLED,
    )


class ServiceBalances(BaseModel):
    """External service account balances."""

    runpod_balance: float | None = None
    runpod_spend_per_hr: float | None = None
    runpod_pod_status: str | None = None
    fal_balance_url: str = "https://fal.ai/dashboard/billing"
    fal_status: str = "unknown"


@router.get("/balances", response_model=ServiceBalances)
async def get_service_balances():
    """Get current balances for external AI services."""
    import httpx
    import os

    result = ServiceBalances()

    # RunPod balance
    runpod_key = settings.RUNPOD_API_KEY
    if runpod_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.runpod.io/graphql",
                    headers={"Authorization": f"Bearer {runpod_key}", "Content-Type": "application/json"},
                    json={"query": "{ myself { clientBalance currentSpendPerHr pods { id desiredStatus } } }"},
                )
                data = resp.json().get("data", {}).get("myself", {})
                result.runpod_balance = data.get("clientBalance")
                result.runpod_spend_per_hr = data.get("currentSpendPerHr")
                pods = data.get("pods", [])
                if pods:
                    result.runpod_pod_status = pods[0].get("desiredStatus", "UNKNOWN")
        except Exception:
            pass

    # fal.ai — no balance API, just check if key is set
    fal_key = os.environ.get("FAL_KEY", "")
    if fal_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Quick health check — submit a tiny request to see if auth works
                resp = await client.get(
                    "https://rest.alpha.fal.ai/",
                    headers={"Authorization": f"Key {fal_key}"},
                )
                result.fal_status = "active" if resp.status_code != 401 else "invalid_key"
        except Exception:
            result.fal_status = "unreachable"
    else:
        result.fal_status = "no_key"

    return result


class CostBreakdown(BaseModel):
    """Cost breakdown by provider."""
    provider: str
    call_count: int
    total_cost: float


class CostSummary(BaseModel):
    """Cost tracking summary."""
    total_cost: float
    total_calls: int
    this_month_cost: float
    this_month_calls: int
    by_provider: list[CostBreakdown]
    by_episode: list[dict]


@router.get("/costs", response_model=CostSummary)
async def get_cost_summary():
    """Get cost tracking summary from api_usage table."""
    from sqlalchemy import text
    from app.database import async_session_maker

    async with async_session_maker() as db:
        # Total costs
        result = await db.execute(text(
            "SELECT COALESCE(COUNT(*), 0), COALESCE(SUM(cost_usd), 0) FROM api_usage"
        ))
        row = result.fetchone()
        total_calls = row[0]
        total_cost = float(row[1])

        # This month
        result = await db.execute(text(
            "SELECT COALESCE(COUNT(*), 0), COALESCE(SUM(cost_usd), 0) FROM api_usage "
            "WHERE created_at >= date_trunc('month', CURRENT_DATE)"
        ))
        row = result.fetchone()
        month_calls = row[0]
        month_cost = float(row[1])

        # By provider
        result = await db.execute(text(
            "SELECT provider, COUNT(*), COALESCE(SUM(cost_usd), 0) "
            "FROM api_usage GROUP BY provider ORDER BY SUM(cost_usd) DESC"
        ))
        by_provider = [
            CostBreakdown(provider=r[0], call_count=r[1], total_cost=float(r[2]))
            for r in result.fetchall()
        ]

        # By episode
        result = await db.execute(text(
            "SELECT a.episode_id, e.title, COUNT(*), COALESCE(SUM(a.cost_usd), 0) "
            "FROM api_usage a LEFT JOIN episodes e ON a.episode_id = e.id "
            "GROUP BY a.episode_id, e.title ORDER BY a.episode_id"
        ))
        by_episode = [
            {"episode_id": r[0], "title": r[1], "calls": r[2], "cost": float(r[3])}
            for r in result.fetchall()
        ]

    return CostSummary(
        total_cost=total_cost,
        total_calls=total_calls,
        this_month_cost=month_cost,
        this_month_calls=month_calls,
        by_provider=by_provider,
        by_episode=by_episode,
    )

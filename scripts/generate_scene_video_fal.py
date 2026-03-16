"""Generate a video for a single scene via fal.ai."""

import asyncio
import os
import sys
import tempfile
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import settings
from app.database import async_session_maker
from app.models.scene import Scene, SceneStatus
from app.models.logs import APIProvider, APIUsage
from app.services.fal_video_generator import FalVideoGenerator
from app.services.storage import StorageService
from sqlalchemy import select
from sqlalchemy.orm import selectinload

EPISODE_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1
SCENE_NUMBER = int(sys.argv[2]) if len(sys.argv) > 2 else 2
BACKEND = sys.argv[3] if len(sys.argv) > 3 else "fal-ltx"


async def main():
    storage = StorageService()
    fal_gen = FalVideoGenerator(backend=BACKEND)

    print(f"Generating video for Episode {EPISODE_ID}, Scene {SCENE_NUMBER}")
    print(f"Backend: {fal_gen.display_name} ({fal_gen.model_id})")

    async with async_session_maker() as db:
        stmt = (
            select(Scene)
            .options(selectinload(Scene.character))
            .where(Scene.episode_id == EPISODE_ID, Scene.scene_number == SCENE_NUMBER)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene:
            print(f"ERROR: Scene {SCENE_NUMBER} not found")
            return

        if not scene.source_image_path:
            print(f"ERROR: Scene {SCENE_NUMBER} has no source image")
            return

        print(f"Image: {scene.source_image_path}")
        print(f"Video prompt: {(scene.video_prompt or scene.start_frame_prompt or 'N/A')[:100]}...")
        print(f"Dialogue: {(scene.dialogue or 'N/A')[:80]}")

        # Download image from MinIO
        local_image = os.path.join(tempfile.gettempdir(), f"f1_video_input_{SCENE_NUMBER:02d}.png")
        bucket, obj_name = scene.source_image_path.split("/", 1)
        await storage.download_file(bucket, obj_name, local_image)

        # Upload to fal CDN
        image_url = await fal_gen.upload_image(local_image)
        print(f"Image uploaded to fal CDN")

        # Generate video
        start_time = datetime.utcnow()
        print(f"Generating video...")

        clip = await fal_gen.generate_clip(
            scene_number=SCENE_NUMBER,
            image_url=image_url,
            prompt=scene.video_prompt or scene.start_frame_prompt or "",
            dialogue=scene.dialogue,
            audio_description=scene.audio_description,
        )

        gen_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Upload to MinIO
        clip_path = await storage.upload_video_clip(
            race_id=1,
            episode_id=EPISODE_ID,
            scene_number=SCENE_NUMBER,
            file_path=clip.video_path,
        )

        # Update scene
        scene.video_clip_path = clip_path
        scene.video_generator = BACKEND
        scene.status = SceneStatus.COMPLETED
        scene.generation_completed_at = datetime.utcnow()

        # Cost tracking
        cost_map = {
            "fal-ovi": 0.20, "fal-ltx": 0.30,
            "fal-kling-std": 0.42, "fal-kling-std-audio": 0.63,
            "fal-kling-pro": 0.42, "fal-kling-pro-audio": 0.84,
        }
        cost = cost_map.get(BACKEND, 0.20)
        provider_map = {
            "fal-ovi": APIProvider.FAL_OVI, "fal-ltx": APIProvider.FAL_LTX,
            "fal-kling-std": APIProvider.FAL_KLING_STD,
        }
        usage = APIUsage(
            episode_id=EPISODE_ID,
            scene_id=scene.id,
            provider=provider_map.get(BACKEND, APIProvider.FAL_LTX),
            endpoint=f"fal.ai/{fal_gen.model_id}",
            cost_usd=Decimal(str(cost)),
            response_time_ms=gen_time_ms,
        )
        db.add(usage)
        await db.commit()

        print(f"\nSUCCESS!")
        print(f"  Video: {clip_path}")
        print(f"  Time: {gen_time_ms}ms ({gen_time_ms/1000:.0f}s)")
        print(f"  Cost: ${cost:.2f}")
        print(f"  Local path: {clip.video_path}")


if __name__ == "__main__":
    asyncio.run(main())

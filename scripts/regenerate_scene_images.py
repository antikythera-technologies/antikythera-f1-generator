"""Regenerate scene images for Episode 1, scenes 2-24 via fal.ai."""

import asyncio
import os
import sys
import tempfile
from datetime import datetime

import httpx

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.config import settings
from app.database import async_session_maker
from app.models.scene import Scene, SceneStatus
from app.models.logs import APIProvider, APIUsage
from app.services.personality import load_personality_traits_from_db
from app.services.storage import StorageService
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from decimal import Decimal

LORA_URL = "https://v3b.fal.media/files/b/0a918355/tJadbfWJuPFPPcrwOQ_3W_pytorch_lora_weights.safetensors"
FAL_KEY = os.environ.get("FAL_KEY", settings.FAL_KEY)
EPISODE_ID = 1
START_SCENE = int(sys.argv[1]) if len(sys.argv) > 1 else 2
END_SCENE = int(sys.argv[2]) if len(sys.argv) > 2 else 24


async def generate_scene_image(scene_number: int) -> dict:
    """Generate a single scene image via fal.ai."""
    
    storage = StorageService()

    async with async_session_maker() as db:
        stmt = (
            select(Scene)
            .options(selectinload(Scene.character))
            .where(Scene.episode_id == EPISODE_ID, Scene.scene_number == scene_number)
        )
        result = await db.execute(stmt)
        scene = result.scalar_one_or_none()

        if not scene:
            return {"scene": scene_number, "status": "error", "error": "Scene not found"}

        if scene.status == SceneStatus.COMPLETED and scene.source_image_path:
            return {"scene": scene_number, "status": "skipped", "reason": "already completed"}

        # Load character traits
        character_traits = {}
        character_name = "generic"

        if scene.character:
            character = scene.character
            character_name = character.name
            if character.personality:
                try:
                    character_traits = load_personality_traits_from_db(character.personality)
                except Exception:
                    character_traits = {"display_name": character.display_name, "team": character.team}

            # No face reference — flux-general IP-Adapter warps faces.
            # Character consistency via LoRA + prompt description only.

        # Build prompt
        frame_prompt = scene.start_frame_prompt or scene.action_description or "Character speaking"
        physical = character_traits.get("physical_features", "")
        prompt_parts = ["ANTKF1STYLE", frame_prompt]
        if physical:
            prompt_parts.append(f"Character physical traits: {physical}")
        prompt_parts.append(
            "Satirical caricature style with oversized head, "
            "photorealistic skin with visible pores. Dramatic lighting with deep shadows. "
            "No text, no words, no letters, no logos, no watermarks on clothing or background."
        )
        full_prompt = " ".join(prompt_parts)

        endpoint = "fal-ai/flux-lora"
        print(f"  Scene {scene_number}: Submitting to {endpoint} (char: {character_name})")

        fal_payload = {
            "prompt": full_prompt,
            "image_size": {"width": 1280, "height": 720},
            "num_images": 1,
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
            "loras": [{"path": LORA_URL, "scale": 1.0}],
            "output_format": "png",
        }
        # No face reference — LoRA handles style consistency

        # Update status
        scene.status = SceneStatus.GENERATING
        scene.generation_started_at = datetime.utcnow()
        await db.flush()

        start_time = datetime.utcnow()

        async with httpx.AsyncClient(timeout=300) as client:
            # Submit
            submit_resp = await client.post(
                f"https://queue.fal.run/{endpoint}",
                headers={"Authorization": f"Key {FAL_KEY}", "Content-Type": "application/json"},
                json=fal_payload,
            )
            submit_resp.raise_for_status()
            submit_data = submit_resp.json()
            request_id = submit_data.get("request_id")
            status_url = submit_data.get("status_url", f"https://queue.fal.run/{endpoint}/requests/{request_id}/status")
            response_url = submit_data.get("response_url", f"https://queue.fal.run/{endpoint}/requests/{request_id}")

            # Poll
            for i in range(60):
                await asyncio.sleep(5)
                status_resp = await client.get(status_url, headers={"Authorization": f"Key {FAL_KEY}"})
                status_data = status_resp.json()
                status = status_data.get("status", "")

                if status == "COMPLETED":
                    break
                elif status in ("FAILED", "CANCELLED"):
                    error_msg = status_data.get("error", "failed")
                    scene.status = SceneStatus.FAILED
                    scene.last_error = str(error_msg)[:500]
                    await db.commit()
                    return {"scene": scene_number, "status": "failed", "error": error_msg}
            else:
                scene.status = SceneStatus.FAILED
                scene.last_error = "Timeout"
                await db.commit()
                return {"scene": scene_number, "status": "failed", "error": "timeout"}

            # Get result
            result_resp = await client.get(response_url, headers={"Authorization": f"Key {FAL_KEY}"})
            result_resp.raise_for_status()
            result_data = result_resp.json()
            images = result_data.get("images", [])
            if not images:
                scene.status = SceneStatus.FAILED
                scene.last_error = "No images returned"
                await db.commit()
                return {"scene": scene_number, "status": "failed", "error": "no images"}

            # Download
            img_resp = await client.get(images[0]["url"])
            img_resp.raise_for_status()

        gen_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Save locally
        tmp_path = os.path.join(tempfile.gettempdir(), f"f1_scene_{EPISODE_ID}_{scene_number:02d}_start.png")
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(img_resp.content)

        # Upload to MinIO
        image_path = await storage.upload_scene_image(
            race_id=1,  # Australian GP
            episode_id=EPISODE_ID,
            scene_number=scene_number,
            file_path=tmp_path,
        )

        # Update scene
        scene.source_image_path = image_path
        scene.start_frame_path = image_path
        scene.status = SceneStatus.COMPLETED
        scene.generation_completed_at = datetime.utcnow()
        scene.generation_time_ms = gen_time_ms
        scene.last_error = None

        # Log cost
        cost = 0.035
        usage = APIUsage(
            episode_id=EPISODE_ID,
            scene_id=scene.id,
            provider=APIProvider.FAL_IMAGE,
            endpoint=f"fal.ai/{endpoint}",
            cost_usd=Decimal(str(cost)),
            response_time_ms=gen_time_ms,
        )
        db.add(usage)
        await db.commit()

        return {
            "scene": scene_number,
            "status": "success",
            "character": character_name,
            "time_ms": gen_time_ms,
            "cost": cost,
            
            "path": image_path,
        }


async def main():
    print(f"=" * 60)
    print(f"Regenerating Episode {EPISODE_ID} scene images ({START_SCENE}-{END_SCENE})")
    print(f"Using fal.ai flux-lora / flux-general with ANTKF1STYLE LoRA")
    print(f"=" * 60)

    total_cost = 0
    results = []

    for scene_num in range(START_SCENE, END_SCENE + 1):
        print(f"\n--- Scene {scene_num}/{END_SCENE} ---")
        try:
            result = await generate_scene_image(scene_num)
            results.append(result)

            if result["status"] == "success":
                total_cost += result["cost"]
                print(f"  OK: {result['character']}, {result['time_ms']}ms, "
                      f"${result['cost']:.3f}")
            elif result["status"] == "skipped":
                print(f"  SKIPPED: {result['reason']}")
            else:
                print(f"  FAILED: {result.get('error', 'unknown')}")
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"scene": scene_num, "status": "error", "error": str(e)})

    # Summary
    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] in ("failed", "error"))
    skipped = sum(1 for r in results if r["status"] == "skipped")

    print(f"\n{'=' * 60}")
    print(f"DONE: {success} success, {failed} failed, {skipped} skipped")
    print(f"Total cost: ${total_cost:.2f}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())

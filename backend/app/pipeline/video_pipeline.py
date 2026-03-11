"""Main video generation pipeline."""

import asyncio
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session_maker
from app.exceptions import SceneGenerationError, VideoStitchError
from app.models.character import Character, CharacterImage
from app.models.episode import Episode, EpisodeStatus
from app.models.logs import APIProvider, APIUsage, GenerationLog, LogComponent, LogLevel
from app.models.race import Race
from app.models.scene import Scene, SceneStatus
from app.services.personality import find_personality_file, load_personality_traits
from app.services.script_generator import ScriptGenerator
from app.services.image_generator import ImageGenerator
from app.services.ovi_video_generator import OviVideoGenerator
from app.services.ovi_space_manager import OviSpaceManager
from app.services.stitcher import VideoStitcher
from app.services.youtube_uploader import YouTubeUploader
from app.services.storage import StorageService


class VideoPipeline:
    """Main video generation pipeline orchestrator.

    Supports two video generation backends:
    - "ltx": LTX 2.3 via ComfyUI (dual start/end frame → video interpolation)
    - "ovi": Ovi via Gradio (single image → video, legacy)

    Controlled by settings.VIDEO_GENERATOR_DEFAULT.
    """

    MAX_SCENE_RETRIES = 3

    def __init__(self, episode_id: int):
        self.episode_id = episode_id
        self.logger = logging.getLogger(f"pipeline.episode.{episode_id}")

        # Services
        self.script_generator = ScriptGenerator()
        self.image_generator = ImageGenerator()
        self.ovi_generator = OviVideoGenerator(quality=settings.OVI_QUALITY)
        self.stitcher = VideoStitcher()
        self.uploader = YouTubeUploader()
        self.storage = StorageService()

        # State
        self.episode: Optional[Episode] = None
        self.race: Optional[Race] = None

    @property
    def _use_ltx(self) -> bool:
        """Whether the current configuration uses LTX for video."""
        return settings.VIDEO_GENERATOR_DEFAULT == "ltx"

    async def run(self) -> str:
        """
        Execute full video generation pipeline.

        Returns:
            YouTube URL of the published video
        """
        self.logger.info("=" * 60)
        self.logger.info(f"STARTING PIPELINE FOR EPISODE {self.episode_id}")
        self.logger.info(f"Video generator: {settings.VIDEO_GENERATOR_DEFAULT}")
        self.logger.info("=" * 60)

        async with async_session_maker() as db:
            try:
                # Load episode
                await self._load_episode(db)

                # Phase 1: Generate script
                self.logger.info("PHASE 1: Script Generation")
                await self._update_status(db, EpisodeStatus.GENERATING)
                scenes = await self._generate_script(db)

                # Phase 2: Generate video clips
                self.logger.info("PHASE 2: Video Clip Generation")
                await self._generate_video_clips(db, scenes)

                # Phase 3: Stitch final video
                self.logger.info("PHASE 3: Video Stitching")
                await self._update_status(db, EpisodeStatus.STITCHING)
                final_path = await self._stitch_video(db)

                # Phase 4: Upload to YouTube
                self.logger.info("PHASE 4: YouTube Upload")
                await self._update_status(db, EpisodeStatus.UPLOADING)
                youtube_url = await self._upload_to_youtube(db, final_path)

                # Phase 5: Cleanup old assets
                self.logger.info("PHASE 5: Cleanup")
                await self._cleanup_old_assets(db)

                # Mark as published
                await self._update_status(db, EpisodeStatus.PUBLISHED)
                self.episode.published_at = datetime.utcnow()
                self.episode.youtube_url = youtube_url

                await db.commit()

                self.logger.info("=" * 60)
                self.logger.info(f"PIPELINE COMPLETE: {youtube_url}")
                self.logger.info("=" * 60)

                return youtube_url

            except Exception as e:
                self.logger.error(f"PIPELINE FAILED: {str(e)}")
                await self._handle_failure(db, e)
                raise

    async def _load_episode(self, db: AsyncSession) -> None:
        """Load episode and race from database."""
        stmt = (
            select(Episode)
            .options(selectinload(Episode.race), selectinload(Episode.scenes))
            .where(Episode.id == self.episode_id)
        )
        result = await db.execute(stmt)
        self.episode = result.scalar_one_or_none()

        if not self.episode:
            raise ValueError(f"Episode {self.episode_id} not found")

        self.race = self.episode.race
        self.episode.generation_started_at = datetime.utcnow()

        self.logger.info(f"Loaded episode: {self.episode.title}")
        if self.race:
            self.logger.info(f"Race: {self.race.race_name}")

    async def _update_status(self, db: AsyncSession, status: EpisodeStatus) -> None:
        """Update episode status."""
        self.episode.status = status
        await db.flush()
        self.logger.info(f"Status updated to: {status.value}")

    async def _generate_script(self, db: AsyncSession) -> List[Scene]:
        """Generate script and create scene records.

        If scenes already exist (e.g. from a previous failed run), returns
        the existing scenes instead of regenerating.

        Now stores dual-frame prompts (start_frame_prompt, end_frame_prompt,
        camera_direction, video_prompt) for the new pipeline.
        """
        # Check for existing scenes (resume support)
        existing_stmt = (
            select(Scene)
            .where(Scene.episode_id == self.episode_id)
            .order_by(Scene.scene_number)
        )
        existing_result = await db.execute(existing_stmt)
        existing_scenes = existing_result.scalars().all()

        if existing_scenes:
            self.logger.info(
                f"Found {len(existing_scenes)} existing scenes — skipping script generation"
            )
            return list(existing_scenes)

        # Get available characters
        stmt = select(Character).where(Character.is_active == True)
        result = await db.execute(stmt)
        characters = result.scalars().all()

        character_data = [
            {
                "name": c.name,
                "personality": c.personality,
                "voice_description": c.voice_description,
            }
            for c in characters
        ]

        # Build race context
        race_context = self._build_race_context()

        # Generate script
        script = await self.script_generator.generate_script(
            race_context=race_context,
            characters=character_data,
            episode_type=self.episode.episode_type.value,
        )

        # Update episode with script metadata
        self.episode.title = script.title
        self.episode.anthropic_tokens_used = script.input_tokens + script.output_tokens
        self.episode.anthropic_cost_usd = Decimal(str(script.cost_usd))

        # Log API usage
        await self._log_api_usage(
            db,
            provider=APIProvider.ANTHROPIC,
            endpoint="/messages",
            input_tokens=script.input_tokens,
            output_tokens=script.output_tokens,
            cost_usd=script.cost_usd,
        )

        # Create scene records with full prompt traceability
        scenes = []
        for scene_script in script.scenes:
            # Find character
            character = next(
                (c for c in characters if c.name == scene_script.character),
                None,
            )

            scene = Scene(
                episode_id=self.episode_id,
                scene_number=scene_script.scene_number,
                character_id=character.id if character else None,
                dialogue=scene_script.dialogue,
                action_description=scene_script.action,
                audio_description=scene_script.audio_description,
                # New dual-frame prompts
                start_frame_prompt=scene_script.start_frame_prompt or None,
                end_frame_prompt=scene_script.end_frame_prompt or None,
                camera_direction=scene_script.camera_direction or None,
                video_prompt=scene_script.video_prompt or None,
                status=SceneStatus.PENDING,
            )
            db.add(scene)
            scenes.append(scene)

        await db.flush()
        self.logger.info(f"Created {len(scenes)} scene records with dual-frame prompts")

        return scenes

    def _build_race_context(self) -> str:
        """Build race context for script generation."""
        if not self.race:
            return "General F1 commentary"

        return f"""Race: {self.race.race_name}
Circuit: {self.race.circuit_name or 'Unknown'}
Country: {self.race.country or 'Unknown'}
Date: {self.race.race_date}
Season: {self.race.season} Round {self.race.round_number}
"""

    # ------------------------------------------------------------------
    # Character trait loading (shared by both image gen paths)
    # ------------------------------------------------------------------

    async def _load_character_context(
        self, db: AsyncSession, scene: Scene
    ) -> tuple[str, dict, str | None]:
        """Load character name, traits, and face reference for a scene.

        Returns:
            (character_name, character_traits, face_image_filename)
        """
        character_name = "generic_commentator"
        character_traits: dict = {}
        face_image: str | None = None

        if scene.character_id:
            stmt = select(Character).where(Character.id == scene.character_id)
            result = await db.execute(stmt)
            character = result.scalar_one_or_none()

            if character:
                character_name = character.name

                # Load rich traits from personality JSON
                personality_path = find_personality_file(character.name)
                if personality_path:
                    try:
                        character_traits = load_personality_traits(personality_path)
                        self.logger.debug(
                            f"Loaded personality traits for {character.name} "
                            f"from {personality_path.name}"
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"Could not load personality for {character.name}: {e}"
                        )
                        character_traits = {
                            "display_name": character.display_name,
                            "team": character.team,
                        }
                else:
                    character_traits = {
                        "display_name": character.display_name,
                        "team": character.team,
                    }

                # Ensure face reference is in ComfyUI
                face_image = await self.image_generator.ensure_face_reference(character.name)

        return character_name, character_traits, face_image

    # ------------------------------------------------------------------
    # Phase 2: Video clip generation
    # ------------------------------------------------------------------

    async def _generate_video_clips(self, db: AsyncSession, scenes: List[Scene]) -> None:
        """Generate video clips for all scenes.

        Routes to LTX or OVI pipeline based on VIDEO_GENERATOR_DEFAULT.
        """
        if self._use_ltx:
            await self._generate_video_clips_ltx(db, scenes)
        else:
            await self._generate_video_clips_ovi(db, scenes)

    # ------------------------------------------------------------------
    # LTX pipeline (dual start/end frames)
    # ------------------------------------------------------------------

    async def _generate_video_clips_ltx(
        self, db: AsyncSession, scenes: List[Scene]
    ) -> None:
        """Generate video clips using LTX 2.3 via ComfyUI.

        Two-phase process on the SAME ComfyUI instance (no Ovi swap):
        Phase 2a: Generate start + end frame images (Flux + LoRA + PuLID)
        Phase 2b: Free VRAM → Generate videos (LTX 2.3)
        """
        from app.services.comfyui_client import ComfyUIClient
        from app.services.ltx_video_generator import LTXVideoGenerator

        # ----- Phase 2a: Generate dual frame images via ComfyUI -----
        self.logger.info("PHASE 2a: Dual-Frame Image Generation (ComfyUI)")

        # Track local paths for video generation
        start_frame_paths: dict[int, str] = {}  # scene_number -> path
        end_frame_paths: dict[int, str] = {}

        for scene in scenes:
            if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)} fully complete — skipping"
                )
                continue

            # Load character context once per scene
            character_name, character_traits, face_image = (
                await self._load_character_context(db, scene)
            )

            # --- Generate START frame ---
            if not scene.start_frame_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)}: Generating start frame"
                )
                try:
                    scene.status = SceneStatus.GENERATING
                    scene.generation_started_at = datetime.utcnow()
                    await db.flush()

                    generated = await self.image_generator.generate_scene_image(
                        scene_number=scene.scene_number,
                        episode_id=self.episode_id,
                        character_name=character_name,
                        frame_prompt=scene.start_frame_prompt,
                        frame_type="start",
                        character_traits=character_traits,
                        face_image=face_image,
                    )

                    # Upload to MinIO
                    storage_path = await self.storage.upload_scene_image(
                        race_id=self.race.id if self.race else 0,
                        episode_id=self.episode_id,
                        scene_number=scene.scene_number,
                        file_path=generated.image_path,
                        suffix="start",
                    )

                    scene.start_frame_path = storage_path
                    scene.start_frame_prompt_final = generated.prompt_used
                    start_frame_paths[scene.scene_number] = generated.image_path
                    await db.flush()

                    self.logger.info(
                        f"Scene {scene.scene_number}: Start frame done "
                        f"({generated.generation_time_ms}ms)"
                    )

                except Exception as e:
                    self.logger.error(
                        f"Scene {scene.scene_number} start frame failed: {e}"
                    )
                    scene.status = SceneStatus.FAILED
                    scene.last_error = f"Start frame: {e}"
                    scene.retry_count += 1
                    await db.flush()
                    continue
            else:
                # Resume: download existing start frame
                local_path = f"/tmp/f1-images/ep{self.episode_id}_s{scene.scene_number:02d}_start.png"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                bucket, obj = scene.start_frame_path.split("/", 1)
                await self.storage.download_file(bucket, obj, local_path)
                start_frame_paths[scene.scene_number] = local_path

            # --- Generate END frame ---
            if not scene.end_frame_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)}: Generating end frame"
                )
                try:
                    generated = await self.image_generator.generate_scene_image(
                        scene_number=scene.scene_number,
                        episode_id=self.episode_id,
                        character_name=character_name,
                        frame_prompt=scene.end_frame_prompt,
                        frame_type="end",
                        character_traits=character_traits,
                        face_image=face_image,
                    )

                    storage_path = await self.storage.upload_scene_image(
                        race_id=self.race.id if self.race else 0,
                        episode_id=self.episode_id,
                        scene_number=scene.scene_number,
                        file_path=generated.image_path,
                        suffix="end",
                    )

                    scene.end_frame_path = storage_path
                    scene.end_frame_prompt_final = generated.prompt_used
                    end_frame_paths[scene.scene_number] = generated.image_path
                    await db.flush()

                    self.logger.info(
                        f"Scene {scene.scene_number}: End frame done "
                        f"({generated.generation_time_ms}ms)"
                    )

                except Exception as e:
                    self.logger.error(
                        f"Scene {scene.scene_number} end frame failed: {e}"
                    )
                    scene.status = SceneStatus.FAILED
                    scene.last_error = f"End frame: {e}"
                    scene.retry_count += 1
                    await db.flush()
                    continue
            else:
                local_path = f"/tmp/f1-images/ep{self.episode_id}_s{scene.scene_number:02d}_end.png"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                bucket, obj = scene.end_frame_path.split("/", 1)
                await self.storage.download_file(bucket, obj, local_path)
                end_frame_paths[scene.scene_number] = local_path

        # Commit all images before switching to video generation
        await db.commit()
        self.logger.info(
            f"Phase 2a complete: {len(start_frame_paths)} start + "
            f"{len(end_frame_paths)} end frames committed"
        )

        # ----- Free ComfyUI VRAM for LTX 2.3 -----
        self.logger.info("Freeing ComfyUI VRAM for LTX 2.3 video generation...")
        comfyui_client = ComfyUIClient()
        await comfyui_client.free_vram()

        # ----- Phase 2b: Generate video clips via LTX 2.3 -----
        self.logger.info("PHASE 2b: Video Generation (LTX 2.3)")
        ltx_generator = LTXVideoGenerator(quality="caricature")

        try:
            for scene in scenes:
                if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                    continue

                sn = scene.scene_number
                if sn not in start_frame_paths or sn not in end_frame_paths:
                    self.logger.warning(
                        f"Scene {sn} missing frames — skipping video"
                    )
                    continue

                self.logger.info(
                    f"Generating video for scene {sn}/{len(scenes)}"
                )

                try:
                    video_prompt = scene.video_prompt or (
                        scene.action_description or "Character speaking to camera"
                    )

                    clip = await ltx_generator.generate_clip(
                        scene_number=sn,
                        start_frame_path=start_frame_paths[sn],
                        end_frame_path=end_frame_paths[sn],
                        video_prompt=video_prompt,
                        dialogue=scene.dialogue,
                        audio_description=scene.audio_description,
                    )

                    # Upload to MinIO
                    clip_storage_path = await self.storage.upload_video_clip(
                        race_id=self.race.id if self.race else 0,
                        episode_id=self.episode_id,
                        scene_number=sn,
                        file_path=clip.video_path,
                    )

                    scene.video_clip_path = clip_storage_path
                    scene.video_generator = "ltx"
                    scene.status = SceneStatus.COMPLETED
                    scene.generation_completed_at = datetime.utcnow()
                    scene.generation_time_ms = clip.generation_time_ms

                    self.logger.info(
                        f"Scene {sn} complete: {clip.generation_time_ms}ms (LTX 2.3)"
                    )
                    await db.commit()

                except Exception as e:
                    self.logger.error(f"Scene {sn} video failed: {e}")
                    scene.status = SceneStatus.FAILED
                    scene.last_error = str(e)
                    scene.retry_count += 1
                    await db.flush()

                    if scene.retry_count >= self.MAX_SCENE_RETRIES:
                        raise SceneGenerationError(
                            sn,
                            f"Failed after {self.MAX_SCENE_RETRIES} retries",
                        )
        finally:
            await ltx_generator.close()
            await comfyui_client.close()

        self.logger.info("Phase 2b complete — all video clips generated (LTX 2.3)")

    # ------------------------------------------------------------------
    # OVI pipeline (legacy single-frame)
    # ------------------------------------------------------------------

    async def _generate_video_clips_ovi(
        self, db: AsyncSession, scenes: List[Scene]
    ) -> None:
        """Generate video clips using OVI (legacy single-frame pipeline).

        ComfyUI (image gen) and Ovi (video gen) share a single GPU.
        Running them simultaneously causes CUDA OOM.
        """
        import httpx

        # ----- Ensure Ovi is stopped so ComfyUI has full GPU -----
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{settings.COMFYUI_URL}/ovi/status")
                ovi_status = resp.json()
                if ovi_status.get("running"):
                    self.logger.info("Stopping Ovi to free GPU for image generation...")
                    await client.post(f"{settings.COMFYUI_URL}/ovi/stop")
                    await asyncio.sleep(5)
                    self.logger.info("Ovi stopped, GPU available for ComfyUI")
                else:
                    self.logger.info("Ovi not running, GPU available for ComfyUI")
        except Exception as e:
            self.logger.warning(f"Could not check/stop Ovi: {e}")

        # ----- Phase 2a: Generate all scene images via ComfyUI -----
        self.logger.info("PHASE 2a: Image Generation (ComfyUI — legacy single-frame)")

        image_paths: dict[int, str] = {}

        for scene in scenes:
            if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)} fully complete — skipping"
                )
                continue

            if scene.source_image_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)} already has image — skipping"
                )
                local_path = f"/tmp/f1-images/episode_{self.episode_id}_scene_{scene.scene_number:02d}_resume.png"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                bucket, object_name = scene.source_image_path.split("/", 1)
                await self.storage.download_file(bucket, object_name, local_path)
                image_paths[scene.scene_number] = local_path
                continue

            self.logger.info(f"Generating image for scene {scene.scene_number}/{len(scenes)}")

            try:
                scene.status = SceneStatus.GENERATING
                scene.generation_started_at = datetime.utcnow()
                await db.flush()

                source_image = await self._get_scene_image_legacy(db, scene)
                image_paths[scene.scene_number] = source_image

                self.logger.info(f"Scene {scene.scene_number}: Image ready")
                await db.flush()

            except Exception as e:
                self.logger.error(f"Scene {scene.scene_number} image failed: {e}")
                scene.status = SceneStatus.FAILED
                scene.last_error = f"Image generation: {e}"
                scene.retry_count += 1
                await db.flush()

        await db.commit()
        self.logger.info(f"Phase 2a complete: {len(image_paths)} images committed to DB")

        # ----- Free ComfyUI VRAM and start Ovi -----
        self.logger.info("Freeing ComfyUI VRAM for Ovi video generation...")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"{settings.COMFYUI_URL}/free",
                    json={"unload_models": True, "free_memory": True},
                )
            self.logger.info("ComfyUI models unloaded from VRAM")
        except Exception as e:
            self.logger.warning(f"Could not free ComfyUI VRAM: {e}")

        self.logger.info("Starting Ovi for video generation...")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{settings.COMFYUI_URL}/ovi/status")
                if not resp.json().get("running"):
                    await client.post(f"{settings.COMFYUI_URL}/ovi/start")
                    self.logger.info("Ovi start command sent, waiting for model load...")
                else:
                    self.logger.info("Ovi already running")
        except Exception as e:
            self.logger.warning(f"Could not start Ovi via GPU manager: {e}")

        # ----- Phase 2b: Generate all video clips via Ovi -----
        self.logger.info("PHASE 2b: Video Generation (Ovi)")

        async with OviSpaceManager(quality=settings.OVI_QUALITY) as ovi_manager:
            for scene in scenes:
                if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                    continue

                if scene.scene_number not in image_paths:
                    self.logger.warning(
                        f"Scene {scene.scene_number} has no image — skipping video"
                    )
                    continue

                self.logger.info(f"Generating video for scene {scene.scene_number}/{len(scenes)}")

                try:
                    source_image = image_paths[scene.scene_number]
                    prompt = self._build_ovi_prompt(scene)

                    start_time = datetime.utcnow()
                    video_path = await ovi_manager.generate_video(
                        image_path=source_image,
                        prompt=prompt,
                    )
                    generation_time_ms = int(
                        (datetime.utcnow() - start_time).total_seconds() * 1000
                    )

                    clip_path = await self.storage.upload_video_clip(
                        race_id=self.race.id if self.race else 0,
                        episode_id=self.episode_id,
                        scene_number=scene.scene_number,
                        file_path=video_path,
                    )

                    scene.video_clip_path = clip_path
                    scene.video_generator = "ovi"
                    scene.status = SceneStatus.COMPLETED
                    scene.generation_completed_at = datetime.utcnow()
                    scene.generation_time_ms = generation_time_ms

                    self.episode.ovi_calls += 1

                    self.logger.info(
                        f"Scene {scene.scene_number} complete: {generation_time_ms}ms"
                    )
                    await db.commit()

                except Exception as e:
                    self.logger.error(f"Scene {scene.scene_number} video failed: {e}")
                    scene.status = SceneStatus.FAILED
                    scene.last_error = str(e)
                    scene.retry_count += 1
                    await db.flush()

                    if scene.retry_count >= self.MAX_SCENE_RETRIES:
                        raise SceneGenerationError(
                            scene.scene_number,
                            f"Failed after {self.MAX_SCENE_RETRIES} retries",
                        )

        self.logger.info("Phase 2b complete — all video clips generated (Ovi)")

    def _build_ovi_prompt(self, scene: Scene) -> str:
        """Build Ovi prompt with special tokens."""
        parts = [scene.action_description or "Character speaking to camera"]

        if scene.dialogue:
            parts.append(f"<S>{scene.dialogue}<E>")

        if scene.audio_description:
            parts.append(f"<AUDCAP>{scene.audio_description}<ENDAUDCAP>")

        return " ".join(parts)

    async def _get_scene_image_legacy(self, db: AsyncSession, scene: Scene) -> str:
        """Generate scene image using legacy single-frame pipeline."""
        character_name, character_traits, face_image = (
            await self._load_character_context(db, scene)
        )

        generated = await self.image_generator.generate_scene_image(
            scene_number=scene.scene_number,
            episode_id=self.episode_id,
            character_name=character_name,
            action_description=scene.action_description or "Character speaking to camera",
            character_traits=character_traits,
            face_image=face_image,
        )

        # Upload generated image to MinIO
        image_storage_path = await self.storage.upload_scene_image(
            race_id=self.race.id if self.race else 0,
            episode_id=self.episode_id,
            scene_number=scene.scene_number,
            file_path=generated.image_path,
        )

        scene.source_image_path = image_storage_path

        self.logger.info(
            f"Scene {scene.scene_number}: Generated image in {generated.generation_time_ms}ms"
            f" (face={'yes' if face_image else 'no'})"
        )

        return generated.image_path

    # ------------------------------------------------------------------
    # Phases 3-5 (unchanged)
    # ------------------------------------------------------------------

    async def _stitch_video(self, db: AsyncSession) -> str:
        """Stitch all scene clips into final video."""
        stmt = (
            select(Scene)
            .where(Scene.episode_id == self.episode_id, Scene.status == SceneStatus.COMPLETED)
            .order_by(Scene.scene_number)
        )
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        if len(scenes) != settings.VIDEO_SCENE_COUNT:
            self.logger.warning(f"Expected {settings.VIDEO_SCENE_COUNT} scenes, got {len(scenes)}")

        clip_paths = []
        for scene in scenes:
            if scene.video_clip_path:
                local_path = f"/tmp/videos/episode_{self.episode_id}/clip_{scene.scene_number:02d}.mp4"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                bucket, object_name = scene.video_clip_path.split("/", 1)
                await self.storage.download_file(bucket, object_name, local_path)
                clip_paths.append(local_path)

        result = await self.stitcher.stitch(self.episode_id, clip_paths)

        final_path = await self.storage.upload_final_video(
            race_id=self.race.id if self.race else 0,
            episode_id=self.episode_id,
            file_path=result.output_path,
        )

        self.episode.final_video_path = final_path
        self.episode.duration_seconds = result.duration_seconds
        self.episode.generation_completed_at = datetime.utcnow()

        if self.episode.generation_started_at:
            gen_time = (datetime.utcnow() - self.episode.generation_started_at).total_seconds()
            self.episode.generation_time_seconds = int(gen_time)

        return result.output_path

    async def _upload_to_youtube(self, db: AsyncSession, video_path: str) -> str:
        """Upload video to YouTube."""
        self.episode.upload_started_at = datetime.utcnow()

        title = self.episode.title
        description = self._build_youtube_description()
        tags = ["F1", "Formula 1", "racing", "motorsport", "satire", "comedy"]

        if self.race:
            tags.extend([self.race.race_name, self.race.circuit_name or ""])

        result = await self.uploader.upload(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
        )

        self.episode.youtube_video_id = result.video_id
        self.episode.youtube_url = result.youtube_url

        return result.youtube_url

    def _build_youtube_description(self) -> str:
        """Build YouTube video description."""
        description = f"""{self.episode.title}

Satirical F1 commentary brought to you by Antikythera Technologies.

#F1 #Formula1 #Racing #Motorsport #Satire
"""
        if self.race:
            description += f"""
Race: {self.race.race_name}
Circuit: {self.race.circuit_name or 'Unknown'}
Season: {self.race.season} Round {self.race.round_number}
"""
        return description

    async def _cleanup_old_assets(self, db: AsyncSession) -> None:
        """Clean up scene assets older than retention policy."""
        if not self.race or self.race.round_number <= settings.STORAGE_RETENTION_RACES:
            self.logger.info("No cleanup needed")
            return

        target_race = self.race.round_number - settings.STORAGE_RETENTION_RACES
        files_deleted, bytes_freed = await self.storage.cleanup_old_race(target_race)

        self.logger.info(f"Cleanup: {files_deleted} files, {bytes_freed / 1024 / 1024:.2f} MB freed")

    async def _log_api_usage(
        self,
        db: AsyncSession,
        provider: APIProvider,
        endpoint: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0,
        response_time_ms: int = 0,
    ) -> None:
        """Log API usage for tracking."""
        usage = APIUsage(
            episode_id=self.episode_id,
            provider=provider,
            endpoint=endpoint,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=Decimal(str(cost_usd)),
            response_time_ms=response_time_ms,
        )
        db.add(usage)

    async def _handle_failure(self, db: AsyncSession, error: Exception) -> None:
        """Handle pipeline failure."""
        if self.episode is None:
            self.logger.error(f"Cannot update episode status — episode not loaded: {error}")
            return
        self.episode.status = EpisodeStatus.FAILED
        self.episode.last_error = str(error)
        self.episode.retry_count += 1

        log = GenerationLog(
            episode_id=self.episode_id,
            level=LogLevel.ERROR,
            component=LogComponent.VIDEO,
            message=f"Pipeline failed: {error}",
            details={"error_type": type(error).__name__},
        )
        db.add(log)

        await db.commit()

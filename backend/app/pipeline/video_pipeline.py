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
from app.models.gag import GagStatus, GagUsage, RunningGag
from app.models.logs import APIProvider, APIUsage, GenerationLog, LogComponent, LogLevel
from app.models.race import Race
from app.models.scene import Scene, SceneStatus
# Personality traits loaded from DB via load_personality_traits_from_db()
from app.services.script_generator import ScriptGenerator
from app.services.image_generator import ImageGenerator
from app.services.ovi_video_generator import OviVideoGenerator
from app.services.ovi_space_manager import OviSpaceManager
from app.services.tts_generator import TTSGenerator
from app.services.audio_mixer import AudioMixer
from app.services.stitcher import VideoStitcher
from app.services.youtube_uploader import YouTubeUploader
from app.services.storage import StorageService


class VideoPipeline:
    """Main video generation pipeline orchestrator.

    Supports two video generation backends:
    - "ltx": LTX 2.3 via ComfyUI (single start frame → AV video with native audio)
    - "ovi": Ovi via Gradio (single image → video, legacy, needs TTS mux)

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
        self.tts_generator = TTSGenerator(
            default_voice=settings.TTS_DEFAULT_VOICE,
        )
        self.audio_mixer = AudioMixer()
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

                # Phase 2c: Generate TTS speech audio and mux onto video clips.
                # Always runs — LTX AV produces ambient sounds only, not speech.
                # TTS gives each character a distinct voice with correct dialogue.
                if settings.TTS_ENABLED:
                    self.logger.info("PHASE 2c: Audio Generation (TTS + Mux)")
                    await self._generate_audio(db, scenes)

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

        # Look up next race for outro teaser
        if self.race:
            next_race_stmt = (
                select(Race)
                .where(Race.round_number == self.race.round_number + 1)
                .where(Race.season == self.race.season)
            )
            next_race_result = await db.execute(next_race_stmt)
            next_race = next_race_result.scalar_one_or_none()
            if next_race:
                sprint_tag = " (Sprint Weekend)" if next_race.is_sprint_weekend else ""
                self._next_race_info = f"{next_race.race_name} in {next_race.country}{sprint_tag}"
                self.logger.info(f"Next race: {self._next_race_info}")
            else:
                self._next_race_info = None
        else:
            self._next_race_info = None

        # Build race context
        race_context = self._build_race_context()

        # Fetch available running gags for this episode
        running_gags = await self._fetch_running_gags(db, characters)
        if running_gags:
            self.logger.info(f"Loaded {len(running_gags)} running gags for script generation")

        # Generate script
        script = await self.script_generator.generate_script(
            race_context=race_context,
            characters=character_data,
            episode_type=self.episode.episode_type.value,
            running_gags=running_gags,
        )

        # Update episode with script metadata
        self.episode.title = script.title
        self.episode.anthropic_tokens_used = script.input_tokens + script.output_tokens
        self.episode.anthropic_cost_usd = Decimal(str(script.cost_usd))

        # Store character appearances for visual consistency across all scenes
        if script.character_appearances:
            self.episode.character_appearances = script.character_appearances
            self.logger.info(
                f"Stored character appearances for: {list(script.character_appearances.keys())}"
            )

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

        # Track running gag usage from the generated script
        if script.gags_referenced:
            await self._record_gag_usage(db, script.gags_referenced)

        return scenes

    def _build_race_context(self) -> str:
        """Build race context for script generation.

        Includes season year, round context, and explicit timeline
        awareness so the LLM knows what's current vs. old news.
        """
        from datetime import date

        current_year = date.today().year

        if not self.race:
            return (
                f"General F1 commentary for the {current_year} season.\n"
                f"IMPORTANT: We are in the {current_year} F1 season. "
                f"Reference current events, not previous seasons."
            )

        season = self.race.season
        round_num = self.race.round_number

        context = f"""Race: {self.race.race_name}
Circuit: {self.race.circuit_name or 'Unknown'}
Country: {self.race.country or 'Unknown'}
Date: {self.race.race_date}
Season: {season} Round {round_num}

CRITICAL TIMELINE CONTEXT — You are writing for the {season} F1 season:
- It is currently {current_year}. All content must reflect the {season} season.
- Lewis Hamilton joined Ferrari in 2025. By {season}, he is an ESTABLISHED Ferrari driver — this is NOT new. Do NOT treat his Ferrari move as fresh news.
- Max Verstappen is at Red Bull Racing (as of {season}).
- Kimi Antonelli replaced Hamilton at Mercedes for {season}.
- Reference CURRENT {season} season drama, standings, and rivalries — not previous season storylines.
- If this is Round {round_num}, reference how the season has developed up to this point.
"""

        if round_num == 1:
            context += "- This is the SEASON OPENER. Focus on new season anticipation, pre-season testing drama, and predictions.\n"
        elif round_num <= 5:
            context += f"- Early season (Round {round_num}). Championship picture is still forming. Focus on early form, surprises, and emerging storylines.\n"
        elif round_num <= 15:
            context += f"- Mid-season (Round {round_num}). Championship battle should be heating up. Reference standings, momentum shifts.\n"
        else:
            context += f"- Late season (Round {round_num}). Championship could be on the line. Maximum drama and tension.\n"

        # Add next race info for outro teaser
        from sqlalchemy import select as _select
        from app.models.race import Race as _Race
        import asyncio

        try:
            # Sync lookup — we're in a sync method but have access to self.race
            # Find next race by round number
            # This is populated by the caller if available
            if hasattr(self, '_next_race_info') and self._next_race_info:
                context += f"\nNEXT RACE: {self._next_race_info}\n"
                context += "- The outro/teaser scene (scene 26) MUST reference the NEXT race listed above, NOT any other race.\n"
        except Exception:
            pass

        return context

    # ------------------------------------------------------------------
    # Running gags
    # ------------------------------------------------------------------

    async def _fetch_running_gags(
        self, db: AsyncSession, characters: list
    ) -> Optional[list[dict]]:
        """Fetch active running gags relevant to this episode's characters."""
        try:
            char_ids = [c.id for c in characters if hasattr(c, "id")]

            stmt = (
                select(RunningGag)
                .where(RunningGag.is_active == True)
                .where(RunningGag.status.in_([GagStatus.ACTIVE, GagStatus.COOLING_DOWN]))
                .order_by(RunningGag.humor_rating.desc())
            )
            result = await db.execute(stmt)
            all_gags = result.scalars().all()

            if not all_gags:
                self.logger.info("No active running gags found in database")
                return None

            # Convert to dicts for the script generator
            gag_dicts = []
            for gag in all_gags:
                gag_dicts.append({
                    "title": gag.title,
                    "description": gag.description,
                    "category": gag.category.value if gag.category else "",
                    "primary_character": "",  # Resolved below if available
                    "setup": gag.setup or "",
                    "punchline": gag.punchline or "",
                    "variations": gag.variations or "",
                    "times_used": gag.times_used,
                })

            return gag_dicts

        except Exception as e:
            self.logger.warning(f"Could not fetch running gags: {e}")
            return None

    async def _record_gag_usage(
        self, db: AsyncSession, gag_titles: list[str]
    ) -> None:
        """Record which running gags were used in the generated script."""
        from datetime import datetime as dt

        for title in gag_titles:
            stmt = select(RunningGag).where(RunningGag.title == title)
            result = await db.execute(stmt)
            gag = result.scalar_one_or_none()

            if gag:
                usage = GagUsage(
                    gag_id=gag.id,
                    episode_id=self.episode_id,
                    usage_context=f"Used in script generation for episode {self.episode_id}",
                )
                db.add(usage)

                gag.times_used += 1
                gag.last_used_at = dt.utcnow()
                gag.last_used_in_episode_id = self.episode_id
                gag.audience_familiarity = min(10, gag.audience_familiarity + 1)

                if gag.max_uses and gag.times_used >= gag.max_uses:
                    gag.status = GagStatus.EXHAUSTED

                self.logger.info(f"Tracked gag usage: '{title}' (used {gag.times_used}x)")
            else:
                self.logger.debug(f"Gag referenced in script but not in DB: '{title}'")

        await db.flush()

    # ------------------------------------------------------------------
    # Character trait loading (shared by both image gen paths)
    # ------------------------------------------------------------------

    async def _load_character_context(
        self, db: AsyncSession, scene: Scene
    ) -> tuple[str, dict, str | None]:
        """Load character name, traits, and face reference for a scene.

        Also injects episode-level character appearance (clothing/outfit) into
        character_traits so that all scenes in an episode use the same outfit.

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

                # Load rich traits from database personality column
                if character.personality:
                    try:
                        from app.services.personality import load_personality_traits_from_db
                        character_traits = load_personality_traits_from_db(
                            character.personality
                        )
                        self.logger.debug(
                            f"Loaded personality traits for {character.name} from DB"
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"Could not parse personality for {character.name}: {e}"
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

                # Inject episode-level appearance for clothing consistency
                appearances = self.episode.character_appearances or {}
                episode_appearance = appearances.get(character.name)
                if episode_appearance:
                    character_traits["episode_appearance"] = episode_appearance
                    self.logger.debug(
                        f"Injected episode appearance for {character.name}"
                    )

                # Ensure face reference is in ComfyUI
                face_image = await self.image_generator.ensure_face_reference(character.name)

        return character_name, character_traits, face_image

    # ------------------------------------------------------------------
    # Phase 2: Video clip generation
    # ------------------------------------------------------------------

    async def _generate_video_clips(self, db: AsyncSession, scenes: List[Scene]) -> None:
        """Generate video clips for all scenes.

        Routes to the configured video backend:
        - ovi / runpod-ovi: Self-hosted Ovi on RunPod (Gradio)
        - ltx / runpod-ltx: Self-hosted LTX 2.3 on RunPod (ComfyUI)
        - fal-*: Hosted via fal.ai API (Ovi, LTX 2.3, Kling 3.0)
        """
        backend = settings.VIDEO_GENERATOR_DEFAULT
        if backend in ("ltx", "runpod-ltx"):
            await self._generate_video_clips_ltx(db, scenes)
        elif backend.startswith("fal-"):
            await self._generate_video_clips_fal(db, scenes)
        else:
            # Default: RunPod Ovi (handles "ovi", "runpod-ovi", and any unknown)
            await self._generate_video_clips_ovi(db, scenes)

    # ------------------------------------------------------------------
    # LTX pipeline (single start frame + AV native audio)
    # ------------------------------------------------------------------

    async def _generate_video_clips_ltx(
        self, db: AsyncSession, scenes: List[Scene]
    ) -> None:
        """Generate video clips using LTX 2.3 AV via ComfyUI.

        Two-phase process on the SAME ComfyUI instance:
        Phase 2a: Generate start frame images (Flux + LoRA + PuLID)
        Phase 2b: Free VRAM → Generate AV videos (LTX 2.3 with native audio)

        End frames are NOT generated — the AV workflow uses a single start
        frame with LTXVImgToVideo, eliminating flickering/ghosting artifacts.
        """
        from app.services.comfyui_client import ComfyUIClient
        from app.services.ltx_video_generator import LTXVideoGenerator

        # ----- Phase 2a: Generate start frame images via ComfyUI -----
        self.logger.info("PHASE 2a: Start-Frame Image Generation (ComfyUI)")

        start_frame_paths: dict[int, str] = {}  # scene_number -> path

        for scene in scenes:
            if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)} fully complete — skipping"
                )
                continue

            character_name, character_traits, face_image = (
                await self._load_character_context(db, scene)
            )

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
                local_path = f"/tmp/f1-images/ep{self.episode_id}_s{scene.scene_number:02d}_start.png"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                bucket, obj = scene.start_frame_path.split("/", 1)
                await self.storage.download_file(bucket, obj, local_path)
                start_frame_paths[scene.scene_number] = local_path

        await db.commit()
        self.logger.info(
            f"Phase 2a complete: {len(start_frame_paths)} start frames committed"
        )

        # ----- Free ComfyUI VRAM for LTX 2.3 -----
        self.logger.info("Freeing ComfyUI VRAM for LTX 2.3 AV generation...")
        comfyui_client = ComfyUIClient()
        await comfyui_client.free_vram()

        # ----- Phase 2b: Generate AV video clips via LTX 2.3 -----
        self.logger.info("PHASE 2b: AV Video Generation (LTX 2.3 + native audio)")
        ltx_generator = LTXVideoGenerator(quality="production")

        try:
            for scene in scenes:
                if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                    continue

                sn = scene.scene_number
                if sn not in start_frame_paths:
                    self.logger.warning(
                        f"Scene {sn} missing start frame — skipping video"
                    )
                    continue

                self.logger.info(
                    f"Generating AV video for scene {sn}/{len(scenes)}"
                )

                try:
                    video_prompt = scene.video_prompt or (
                        scene.action_description or "Character speaking to camera"
                    )

                    clip = await ltx_generator.generate_clip(
                        scene_number=sn,
                        start_frame_path=start_frame_paths[sn],
                        video_prompt=video_prompt,
                        dialogue=scene.dialogue,
                        audio_description=scene.audio_description,
                        use_av=True,
                    )

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
                        f"Scene {sn} complete: {clip.generation_time_ms}ms (LTX AV)"
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

        self.logger.info("Phase 2b complete — all AV video clips generated (LTX 2.3)")

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

                source_image = await self._get_scene_image_fal(db, scene)
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

    async def _generate_video_clips_fal(
        self, db: AsyncSession, scenes: List[Scene]
    ) -> None:
        """Generate video clips using fal.ai API (Ovi, LTX 2.3, or Kling 3.0).

        Images are still generated via ComfyUI on RunPod. Only the video
        generation step uses fal.ai's hosted API. No GPU management needed.
        """
        from app.services.fal_video_generator import FalVideoGenerator

        backend = settings.VIDEO_GENERATOR_DEFAULT
        fal_gen = FalVideoGenerator(backend=backend)

        # ----- Phase 2a: Generate all scene images via ComfyUI -----
        self.logger.info("PHASE 2a: Image Generation (ComfyUI)")

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
                local_path = (
                    f"/tmp/f1-images/episode_{self.episode_id}"
                    f"_scene_{scene.scene_number:02d}_resume.png"
                )
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                bucket, object_name = scene.source_image_path.split("/", 1)
                await self.storage.download_file(bucket, object_name, local_path)
                image_paths[scene.scene_number] = local_path
                continue

            self.logger.info(
                f"Generating image for scene {scene.scene_number}/{len(scenes)}"
            )

            try:
                scene.status = SceneStatus.GENERATING
                scene.generation_started_at = datetime.utcnow()
                await db.flush()

                source_image = await self._get_scene_image_fal(db, scene)
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
        self.logger.info(f"Phase 2a complete: {len(image_paths)} images")

        # ----- Phase 2b: Generate video clips via fal.ai -----
        self.logger.info(
            f"PHASE 2b: Video Generation ({fal_gen.display_name})"
        )

        for scene in scenes:
            if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                continue

            if scene.scene_number not in image_paths:
                self.logger.warning(
                    f"Scene {scene.scene_number} has no image — skipping video"
                )
                continue

            self.logger.info(
                f"Generating video for scene {scene.scene_number}/{len(scenes)}"
            )

            try:
                # Upload image to fal.ai CDN
                local_image = image_paths[scene.scene_number]
                image_url = await fal_gen.upload_image(local_image)

                # Generate video
                start_time = datetime.utcnow()
                # Build rich audio prompt with character voice description
                voice_desc = None
                if scene.character_id:
                    _, char_traits, _ = await self._load_character_context(db, scene)
                    accent = char_traits.get("speaking_style", {}).get("accent_hints") if isinstance(char_traits.get("speaking_style"), dict) else None
                    tone = char_traits.get("speaking_style", {}).get("tone") if isinstance(char_traits.get("speaking_style"), dict) else None
                    nationality = char_traits.get("nationality")
                    voice_parts = []
                    if nationality:
                        voice_parts.append(f"{nationality} accent")
                    if accent:
                        voice_parts.append(accent)
                    if tone:
                        voice_parts.append(tone)
                    voice_desc = ", ".join(voice_parts) if voice_parts else None

                from app.services.fal_video_generator import FalVideoGenerator as FVG
                rich_audio = FVG.build_audio_prompt(scene.audio_description, voice_desc)

                clip = await fal_gen.generate_clip(
                    scene_number=scene.scene_number,
                    image_url=image_url,
                    prompt=(scene.video_prompt or scene.start_frame_prompt or "").replace("ANTKF1STYLE", "").strip(),
                    dialogue=scene.dialogue,
                    audio_description=rich_audio,
                )
                generation_time_ms = int(
                    (datetime.utcnow() - start_time).total_seconds() * 1000
                )

                # Upload video to MinIO
                clip_path = await self.storage.upload_video_clip(
                    race_id=self.race.id if self.race else 0,
                    episode_id=self.episode_id,
                    scene_number=scene.scene_number,
                    file_path=clip.video_path,
                )

                scene.video_clip_path = clip_path
                scene.video_generator = backend
                scene.status = SceneStatus.COMPLETED
                scene.generation_completed_at = datetime.utcnow()
                scene.generation_time_ms = generation_time_ms

                # Log fal.ai cost (per-video pricing)
                fal_cost_map = {
                    "fal-ovi": 0.20,
                    "fal-ltx": 0.30,
                    "fal-kling-std": 0.42,
                    "fal-kling-std-audio": 0.63,
                    "fal-kling-pro": 0.42,
                    "fal-kling-pro-audio": 0.84,
                }
                cost = fal_cost_map.get(backend, 0.20)
                provider_map = {
                    "fal-ovi": APIProvider.FAL_OVI,
                    "fal-ltx": APIProvider.FAL_LTX,
                    "fal-kling-std": APIProvider.FAL_KLING_STD,
                    "fal-kling-std-audio": APIProvider.FAL_KLING_STD_AUDIO,
                    "fal-kling-pro": APIProvider.FAL_KLING_PRO,
                    "fal-kling-pro-audio": APIProvider.FAL_KLING_PRO_AUDIO,
                }
                await self._log_api_usage(
                    db,
                    provider=provider_map.get(backend, APIProvider.FAL_OVI),
                    endpoint=f"fal.ai/{fal_gen.model_id}",
                    cost_usd=cost,
                    response_time_ms=generation_time_ms,
                )

                self.logger.info(
                    f"Scene {scene.scene_number} complete: "
                    f"{generation_time_ms}ms, ${cost:.2f} ({fal_gen.display_name})"
                )
                await db.commit()

            except Exception as e:
                self.logger.error(
                    f"Scene {scene.scene_number} video failed: {e}"
                )
                scene.status = SceneStatus.FAILED
                scene.last_error = str(e)
                scene.retry_count += 1
                await db.flush()

                if scene.retry_count >= self.MAX_SCENE_RETRIES:
                    raise SceneGenerationError(
                        scene.scene_number,
                        f"Failed after {self.MAX_SCENE_RETRIES} retries",
                    )

        self.logger.info(
            f"Phase 2b complete — all video clips generated "
            f"({fal_gen.display_name})"
        )

    def _build_ovi_prompt(self, scene: Scene) -> str:
        """Build Ovi prompt with special tokens."""
        parts = [scene.action_description or "Character speaking to camera"]

        if scene.dialogue:
            parts.append(f"<S>{scene.dialogue}<E>")

        if scene.audio_description:
            parts.append(f"<AUDCAP>{scene.audio_description}<ENDAUDCAP>")

        return " ".join(parts)

    async def _generate_audio(
        self, db: AsyncSession, scenes: List[Scene]
    ) -> None:
        """Generate TTS audio for dialogue and mux onto video clips.

        Phase 2c: For each completed scene with a video clip:
        1. Generate TTS speech from dialogue (if present)
        2. Mux audio onto the video clip
        3. Validate the output has an audio track
        4. Re-upload the audio-enriched video to storage

        Audio failures are FATAL — a video without dialogue audio is broken.
        """
        self.logger.info(f"Generating audio for {len(scenes)} scenes")

        audio_success = 0
        audio_silent = 0
        audio_failed = 0

        for scene in scenes:
            if scene.status != SceneStatus.COMPLETED or not scene.video_clip_path:
                self.logger.debug(
                    f"Scene {scene.scene_number}: Skipping audio "
                    f"(status={scene.status}, clip={bool(scene.video_clip_path)})"
                )
                continue

            if scene.audio_clip_path:
                self.logger.info(
                    f"Scene {scene.scene_number}: Audio already generated — skipping"
                )
                audio_success += 1
                continue

            try:
                # Download the silent video clip to local disk
                local_video = (
                    f"/tmp/f1-audio/ep{self.episode_id}"
                    f"_scene_{scene.scene_number:02d}_video.mp4"
                )
                os.makedirs(os.path.dirname(local_video), exist_ok=True)
                bucket, obj = scene.video_clip_path.split("/", 1)
                await self.storage.download_file(bucket, obj, local_video)

                # Resolve character name for voice selection
                character_name = None
                if scene.character_id:
                    stmt = select(Character).where(
                        Character.id == scene.character_id
                    )
                    result = await db.execute(stmt)
                    character = result.scalar_one_or_none()
                    if character:
                        character_name = character.name

                # Generate TTS audio (or None for silence)
                audio_path = None
                if scene.dialogue and scene.dialogue.strip():
                    tts_result = await self.tts_generator.generate_speech(
                        text=scene.dialogue,
                        character_name=character_name,
                        scene_number=scene.scene_number,
                        episode_id=self.episode_id,
                    )
                    audio_path = tts_result.audio_path
                    self.logger.info(
                        f"Scene {scene.scene_number}: TTS generated "
                        f"({tts_result.duration_seconds:.2f}s, "
                        f"voice={tts_result.voice_used})"
                    )
                else:
                    audio_silent += 1

                # Mux audio onto video
                mix_result = await self.audio_mixer.mux_audio_onto_video(
                    video_path=local_video,
                    audio_path=audio_path,
                    scene_number=scene.scene_number,
                    episode_id=self.episode_id,
                )

                # Validate output has audio track
                await self._validate_audio_track(mix_result.output_path, scene.scene_number)

                # Upload the audio-enriched video, replacing the old clip
                new_clip_path = await self.storage.upload_video_clip(
                    race_id=self.race.id if self.race else 0,
                    episode_id=self.episode_id,
                    scene_number=scene.scene_number,
                    file_path=mix_result.output_path,
                )

                scene.video_clip_path = new_clip_path
                scene.audio_clip_path = new_clip_path  # Mark audio as done
                await db.flush()

                audio_success += 1
                self.logger.info(
                    f"Scene {scene.scene_number}: Audio muxed "
                    f"(tempo={mix_result.tempo_factor:.2f}x, "
                    f"{mix_result.generation_time_ms}ms)"
                )

            except Exception as e:
                audio_failed += 1
                self.logger.error(
                    f"Scene {scene.scene_number} audio FAILED: {e}"
                )
                scene.last_error = f"Audio: {e}"
                await db.flush()
                raise RuntimeError(
                    f"Audio generation failed for scene {scene.scene_number}: {e}. "
                    f"Pipeline halted — fix the issue before retrying."
                ) from e

        await db.commit()
        self.logger.info(
            f"Phase 2c complete — {audio_success} scenes with audio, "
            f"{audio_silent} silent (no dialogue), {audio_failed} failed"
        )

    async def _validate_audio_track(self, video_path: str, scene_number: int) -> None:
        """Validate that the muxed video actually contains an audio track."""
        import asyncio as _asyncio

        proc = await _asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            video_path,
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if b"audio" not in stdout:
            raise RuntimeError(
                f"Scene {scene_number}: Post-mux validation failed — "
                f"output video has NO audio track. Path: {video_path}"
            )

    async def _get_scene_image_legacy(self, db: AsyncSession, scene: Scene) -> str:
        """Generate scene image for a single scene.

        Uses the scene's start_frame_prompt (from the script generator) for
        cinematic landscape framing. Falls back to action_description only
        if no start_frame_prompt exists.
        """
        character_name, character_traits, face_image = (
            await self._load_character_context(db, scene)
        )

        generated = await self.image_generator.generate_scene_image(
            scene_number=scene.scene_number,
            episode_id=self.episode_id,
            character_name=character_name,
            action_description=scene.action_description or "Character speaking to camera",
            frame_prompt=scene.start_frame_prompt,  # Use cinematic prompt from script generator
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


    # LoRA URL for ANTKF1STYLE (hosted on fal CDN)
    FAL_LORA_URL = "https://v3b.fal.media/files/b/0a918355/tJadbfWJuPFPPcrwOQ_3W_pytorch_lora_weights.safetensors"

    async def _get_scene_image_fal(self, db: AsyncSession, scene: Scene) -> str:
        """Generate scene image via fal.ai flux-lora (LoRA only, no face ref).

        Uses fal-ai/flux-lora with ANTKF1STYLE LoRA. No face reference —
        flux-general's IP-Adapter warps faces badly. Character consistency
        comes from LoRA + detailed prompt descriptions instead.
        """
        import tempfile
        import httpx

        from app.services.personality import load_personality_traits_from_db

        # Load character context
        character_name = "generic_commentator"
        character_traits: dict = {}

        if scene.character_id:
            stmt = select(Character).where(Character.id == scene.character_id)
            result = await db.execute(stmt)
            character = result.scalar_one_or_none()

            if character:
                character_name = character.name
                if character.personality:
                    try:
                        character_traits = load_personality_traits_from_db(character.personality)
                    except Exception as e:
                        self.logger.warning(f"Could not parse personality for {character.name}: {e}")
                        character_traits = {"display_name": character.display_name, "team": character.team}
                else:
                    character_traits = {"display_name": character.display_name, "team": character.team}

                # No face reference — flux-general IP-Adapter warps faces.
                # Character consistency via LoRA + prompt description only.

        # Build prompt with LoRA trigger + scene description + character traits
        frame_prompt = scene.start_frame_prompt or scene.action_description or "Character speaking to camera"
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
        self.logger.info(f"Scene {scene.scene_number}: Submitting to {endpoint}")

        fal_payload = {
            "prompt": full_prompt,
            "image_size": {"width": 1280, "height": 720},
            "num_images": 1,
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
            "loras": [{"path": self.FAL_LORA_URL, "scale": 1.0}],
            "output_format": "png",
        }
        fal_key = settings.FAL_KEY
        if not fal_key:
            raise RuntimeError("FAL_KEY not configured")

        start_time = datetime.utcnow()

        async with httpx.AsyncClient(timeout=300) as client:
            # Submit request
            submit_resp = await client.post(
                f"https://queue.fal.run/{endpoint}",
                headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
                json=fal_payload,
            )
            submit_resp.raise_for_status()
            submit_data = submit_resp.json()
            request_id = submit_data.get("request_id")
            status_url = submit_data.get("status_url", f"https://queue.fal.run/{endpoint}/requests/{request_id}/status")
            response_url = submit_data.get("response_url", f"https://queue.fal.run/{endpoint}/requests/{request_id}")

            self.logger.info(f"Scene {scene.scene_number}: fal.ai request {request_id} submitted")

            # Poll for completion (max 5 minutes)
            for i in range(60):
                await asyncio.sleep(5)
                status_resp = await client.get(status_url, headers={"Authorization": f"Key {fal_key}"})
                status_data = status_resp.json()
                status = status_data.get("status", "")

                if status == "COMPLETED":
                    break
                elif status in ("FAILED", "CANCELLED"):
                    error_msg = status_data.get("error", "fal.ai generation failed")
                    raise RuntimeError(f"fal.ai image: {error_msg}")

                if (i + 1) % 6 == 0:
                    self.logger.info(f"Scene {scene.scene_number}: Waiting for fal.ai... {(i+1)*5}s")
            else:
                raise RuntimeError("fal.ai image generation timed out after 5 minutes")

            # Get result
            result_resp = await client.get(response_url, headers={"Authorization": f"Key {fal_key}"})
            result_resp.raise_for_status()
            result_data = result_resp.json()

            images = result_data.get("images", [])
            if not images:
                raise RuntimeError("fal.ai returned no images")

            # Download image
            img_resp = await client.get(images[0]["url"])
            img_resp.raise_for_status()

        generation_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Save to temp file
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"f1_scene_{self.episode_id}_{scene.scene_number:02d}_start.png",
        )
        os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(img_resp.content)

        # Upload to MinIO
        image_storage_path = await self.storage.upload_scene_image(
            race_id=self.race.id if self.race else 0,
            episode_id=self.episode_id,
            scene_number=scene.scene_number,
            file_path=tmp_path,
        )

        scene.source_image_path = image_storage_path
        scene.start_frame_path = image_storage_path

        # Log cost (~$0.035/megapixel, 1280x720 = 0.92MP ≈ $0.035)
        cost = 0.035
        await self._log_api_usage(
            db,
            provider=APIProvider.FAL_IMAGE,
            endpoint=f"fal.ai/{endpoint}",
            cost_usd=cost,
            response_time_ms=generation_time_ms,
        )

        self.logger.info(
            f"Scene {scene.scene_number}: fal.ai image generated in {generation_time_ms}ms "
            f"(flux-lora, ${cost:.3f})"
        )

        return tmp_path


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

"""Main video generation pipeline."""

import logging
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
from app.models.episode import Episode, EpisodeStatus, EpisodeType
from app.models.gag import GagStatus, GagUsage, RunningGag
from app.models.logs import APIProvider, APIUsage, GenerationLog, LogComponent, LogLevel
from app.models.news import NewsArticle
from app.models.race import Race
from app.models.scene import Scene, SceneStatus
from app.models.scheduler import JobTriggerType
from app.services.script_generator import ScriptGenerator
from app.services.image_generator import ImageGenerator
from app.services.news_scraper import NewsScraperService
from app.services.video_generator import VideoGenerator
from app.services.ovi_space_manager import OviSpaceManager
from app.services.stitcher import VideoStitcher
from app.services.youtube_uploader import YouTubeUploader
from app.services.storage import StorageService


class VideoPipeline:
    """Main video generation pipeline orchestrator."""

    MAX_SCENE_RETRIES = 3

    def __init__(self, episode_id: int):
        self.episode_id = episode_id
        self.logger = logging.getLogger(f"pipeline.episode.{episode_id}")

        # Services
        self.script_generator = ScriptGenerator()
        self.image_generator = ImageGenerator()
        self.video_generator = VideoGenerator(quality=settings.OVI_QUALITY)
        self.stitcher = VideoStitcher()
        self.uploader = YouTubeUploader()
        self.storage = StorageService()

        # State
        self.episode: Optional[Episode] = None
        self.race: Optional[Race] = None

    async def run(self) -> str:
        """
        Execute full video generation pipeline.

        Returns:
            YouTube URL of the published video
        """
        self.logger.info("=" * 60)
        self.logger.info(f"STARTING PIPELINE FOR EPISODE {self.episode_id}")
        self.logger.info("=" * 60)

        async with async_session_maker() as db:
            try:
                # Load episode
                await self._load_episode(db)

                # Phase 0: Scrape latest news for context
                self.logger.info("PHASE 0: News Scraping")
                await self._scrape_news(db)

                # Phase 1: Generate script (with news + gags context)
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

    async def _scrape_news(self, db: AsyncSession) -> None:
        """Scrape latest F1 news relevant to this episode's race/context."""
        try:
            scraper = NewsScraperService(session=db)

            # Build scrape context based on episode type
            scrape_context = self._build_scrape_context()

            self.logger.info(f"Scraping news with context: {scrape_context.get('type', 'unknown')}")
            articles = await scraper.scrape_for_context(
                scrape_context=scrape_context,
                max_articles=20,
            )

            self.logger.info(f"Scraped {len(articles)} relevant articles")
            await scraper.close()

        except Exception as e:
            # News scraping failure is non-fatal — log and continue
            self.logger.warning(f"News scraping failed (non-fatal): {e}")

    def _build_scrape_context(self) -> dict:
        """Build scrape context configuration based on episode type."""
        episode_type = self.episode.episode_type

        if episode_type == EpisodeType.WEEKLY_RECAP:
            return {
                "type": "off-week",
                "date_range_days": 7,
                "focus": [
                    "paddock_news", "transfers", "technical_developments",
                    "paddock_gossip", "driver_quotes",
                ],
            }

        # Race weekend context
        focus_map = {
            EpisodeType.POST_FP2: [
                "fp1_results", "fp2_results", "driver_quotes",
                "track_conditions", "team_drama",
            ],
            EpisodeType.POST_SPRINT: [
                "sprint_results", "driver_battles", "penalties",
                "driver_quotes", "championship_implications",
            ],
            EpisodeType.POST_RACE: [
                "race_results", "driver_battles", "penalties",
                "post_race_interviews", "championship_implications",
                "team_drama",
            ],
            EpisodeType.PRE_RACE: [
                "track_conditions", "driver_quotes", "team_drama",
                "championship_implications",
            ],
        }

        return {
            "type": "race-weekend",
            "date_range_hours": 48,
            "focus": focus_map.get(episode_type, ["race_results", "driver_quotes"]),
        }

    async def _generate_script(self, db: AsyncSession) -> List[Scene]:
        """Generate script and create scene records."""
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

        # Fetch news articles for script context
        news_context = await self._fetch_news_for_script(db)

        # Fetch active running gags
        running_gags_data, gag_records = await self._fetch_running_gags(db)

        # Generate script with news + gags context
        script = await self.script_generator.generate_script(
            race_context=race_context,
            characters=character_data,
            episode_type=self.episode.episode_type.value,
            news_context=news_context,
            running_gags=running_gags_data,
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

        # Record gag usage for any gags referenced in the script
        await self._record_gag_usage(db, script.gags_referenced, gag_records)

        # Mark news articles as used in this episode
        await self._mark_news_used(db, news_context)

        # Create scene records
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
                status=SceneStatus.PENDING,
            )
            db.add(scene)
            scenes.append(scene)

        await db.flush()
        self.logger.info(f"Created {len(scenes)} scene records")

        return scenes

    async def _fetch_news_for_script(self, db: AsyncSession) -> List[dict]:
        """Fetch recent news articles formatted for the script generator."""
        try:
            # Map episode type to trigger type for the news scraper query
            trigger_map = {
                EpisodeType.POST_FP2: JobTriggerType.POST_FP2,
                EpisodeType.POST_SPRINT: JobTriggerType.POST_SPRINT,
                EpisodeType.POST_RACE: JobTriggerType.POST_RACE,
                EpisodeType.PRE_RACE: JobTriggerType.POST_RACE,
                EpisodeType.WEEKLY_RECAP: JobTriggerType.WEEKLY_RECAP,
            }
            trigger_type = trigger_map.get(
                self.episode.episode_type, JobTriggerType.POST_RACE
            )

            scraper = NewsScraperService(session=db)
            articles = await scraper.get_articles_for_episode(
                trigger_type=trigger_type,
                race_id=self.race.id if self.race else None,
                limit=10,
            )
            await scraper.close()

            if not articles:
                self.logger.info("No news articles available for script context")
                return []

            # Convert to dicts for the script generator
            news_context = []
            for article in articles:
                news_context.append({
                    "id": article.id,
                    "title": article.title,
                    "summary": article.summary or "",
                    "mentioned_drivers": article.mentioned_drivers or [],
                    "mentioned_teams": article.mentioned_teams or [],
                })

            self.logger.info(f"Fetched {len(news_context)} news articles for script context")
            return news_context

        except Exception as e:
            self.logger.warning(f"Failed to fetch news for script (non-fatal): {e}")
            return []

    async def _fetch_running_gags(self, db: AsyncSession) -> tuple:
        """
        Fetch active running gags for script generation.

        Returns:
            Tuple of (gag_data_for_prompt, gag_records_for_usage_tracking)
        """
        try:
            stmt = (
                select(RunningGag)
                .where(
                    RunningGag.is_active == True,
                    RunningGag.status == GagStatus.ACTIVE,
                )
                .order_by(RunningGag.humor_rating.desc())
                .limit(10)
            )
            result = await db.execute(stmt)
            gag_records = list(result.scalars().all())

            if not gag_records:
                self.logger.info("No active running gags available")
                return [], []

            # Build gag data for the script generator prompt
            gag_data = []
            for gag in gag_records:
                # Resolve primary character name if linked
                primary_character_name = ""
                if gag.primary_character_id:
                    char_stmt = select(Character.name).where(
                        Character.id == gag.primary_character_id
                    )
                    char_result = await db.execute(char_stmt)
                    char_name = char_result.scalar_one_or_none()
                    if char_name:
                        primary_character_name = char_name

                gag_data.append({
                    "title": gag.title,
                    "description": gag.description,
                    "category": gag.category.value if gag.category else "",
                    "primary_character": primary_character_name,
                    "setup": gag.setup or "",
                    "punchline": gag.punchline or "",
                    "variations": gag.variations or "",
                    "times_used": gag.times_used,
                })

            self.logger.info(f"Fetched {len(gag_data)} running gags for script context")
            return gag_data, gag_records

        except Exception as e:
            self.logger.warning(f"Failed to fetch running gags (non-fatal): {e}")
            return [], []

    async def _record_gag_usage(
        self,
        db: AsyncSession,
        gags_referenced: List[str],
        gag_records: List[RunningGag],
    ) -> None:
        """Record GagUsage for any running gags referenced in the generated script."""
        if not gags_referenced or not gag_records:
            return

        # Build a lookup by title (case-insensitive)
        gag_lookup = {gag.title.lower(): gag for gag in gag_records}

        used_count = 0
        for gag_title in gags_referenced:
            gag = gag_lookup.get(gag_title.lower())
            if not gag:
                self.logger.debug(f"Gag title '{gag_title}' not found in records — skipping")
                continue

            # Create usage record
            usage = GagUsage(
                gag_id=gag.id,
                episode_id=self.episode_id,
                usage_context=f"Referenced in {self.episode.episode_type.value} script",
            )
            db.add(usage)

            # Update gag tracking
            gag.times_used += 1
            gag.last_used_in_episode_id = self.episode_id
            gag.last_used_at = datetime.utcnow()
            if self.race:
                gag.last_used_in_race = self.race.race_name

            # Check if gag should be retired
            if gag.max_uses and gag.times_used >= gag.max_uses:
                gag.status = GagStatus.EXHAUSTED
                self.logger.info(f"Gag '{gag.title}' exhausted after {gag.times_used} uses")

            used_count += 1

        if used_count > 0:
            self.logger.info(f"Recorded {used_count} gag usages for this episode")
        await db.flush()

    async def _mark_news_used(
        self,
        db: AsyncSession,
        news_context: List[dict],
    ) -> None:
        """Mark news articles as used in this episode."""
        if not news_context:
            return

        article_ids = [a["id"] for a in news_context if "id" in a]
        if not article_ids:
            return

        try:
            for article_id in article_ids:
                stmt = select(NewsArticle).where(NewsArticle.id == article_id)
                result = await db.execute(stmt)
                article = result.scalar_one_or_none()
                if article:
                    article.used_in_episode_id = self.episode_id
                    article.used_at = datetime.utcnow()

            await db.flush()
            self.logger.info(f"Marked {len(article_ids)} articles as used in episode")
        except Exception as e:
            self.logger.warning(f"Failed to mark articles as used (non-fatal): {e}")

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

    async def _generate_video_clips(self, db: AsyncSession, scenes: List[Scene]) -> None:
        """
        Generate video clips for all scenes.
        
        Uses OviSpaceManager to handle space lifecycle:
        1. Starts the HuggingFace space if sleeping
        2. Waits for full initialization
        3. Generates all videos while keeping space alive
        4. Pauses space after completion to save costs
        """
        self.logger.info("Starting Ovi space for video generation...")
        
        # Use OviSpaceManager for automatic lifecycle management
        async with OviSpaceManager(quality=settings.OVI_QUALITY) as ovi_manager:
            for scene in scenes:
                self.logger.info(f"Processing scene {scene.scene_number}/{len(scenes)}")

                try:
                    scene.status = SceneStatus.GENERATING
                    scene.generation_started_at = datetime.utcnow()
                    await db.flush()

                    # Generate scene image with Nano Banana Pro (character consistent)
                    source_image = await self._get_scene_image(db, scene)

                    # Build Ovi prompt with special tokens
                    prompt = self._build_ovi_prompt(scene)
                    
                    # Generate video clip using OviSpaceManager
                    start_time = datetime.utcnow()
                    video_path = await ovi_manager.generate_video(
                        image_path=source_image,
                        prompt=prompt,
                    )
                    generation_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                    # Upload to storage
                    clip_path = await self.storage.upload_video_clip(
                        race_id=self.race.id if self.race else 0,
                        episode_id=self.episode_id,
                        scene_number=scene.scene_number,
                        file_path=video_path,
                    )

                    # Update scene
                    scene.video_clip_path = clip_path
                    scene.status = SceneStatus.COMPLETED
                    scene.generation_completed_at = datetime.utcnow()
                    scene.generation_time_ms = generation_time_ms

                    self.episode.ovi_calls += 1

                    self.logger.info(f"Scene {scene.scene_number} complete: {generation_time_ms}ms")

                    await db.flush()

                except Exception as e:
                    self.logger.error(f"Scene {scene.scene_number} failed: {e}")
                    scene.status = SceneStatus.FAILED
                    scene.last_error = str(e)
                    scene.retry_count += 1
                    await db.flush()

                    if scene.retry_count >= self.MAX_SCENE_RETRIES:
                        raise SceneGenerationError(
                            scene.scene_number,
                            f"Failed after {self.MAX_SCENE_RETRIES} retries",
                        )
        
        # Space is automatically paused after context manager exits
        self.logger.info("Ovi space paused to save GPU costs")
    
    def _build_ovi_prompt(self, scene: Scene) -> str:
        """
        Build Ovi prompt with special tokens.
        
        Ovi uses:
        - <S>...<E> for speech/dialogue
        - <AUDCAP>...<ENDAUDCAP> for audio description
        """
        parts = [scene.action_description or "Character speaking to camera"]
        
        if scene.dialogue:
            parts.append(f"<S>{scene.dialogue}<E>")
        
        if scene.audio_description:
            parts.append(f"<AUDCAP>{scene.audio_description}<ENDAUDCAP>")
        
        return " ".join(parts)

    async def _get_scene_image(self, db: AsyncSession, scene: Scene) -> str:
        """
        Generate scene image using Gemini with character consistency.

        Character consistency is maintained through:
        1. Style reference images fed as multi-modal input to Gemini
        2. Character traits from database (physical features, comedy angle, etc.)
        3. Master style template baked into every prompt
        """
        # Get character info
        character_name = "generic_commentator"
        reference_image_path = None
        character_traits = {}
        style_reference_paths = []

        if scene.character_id:
            stmt = select(Character).where(Character.id == scene.character_id)
            result = await db.execute(stmt)
            character = result.scalar_one_or_none()

            if character:
                character_name = character.name

                # Build character traits dict for prompt generation
                character_traits = {
                    "display_name": character.display_name,
                    "role": character.role,
                    "team": character.team,
                    "nationality": character.nationality,
                    "physical_features": character.physical_features,
                    "comedy_angle": character.comedy_angle,
                    "signature_expression": character.signature_expression,
                    "signature_pose": character.signature_pose,
                    "props": character.props,
                    "background_type": character.background_type,
                    "background_detail": character.background_detail,
                    "clothing_description": character.clothing_description,
                }

                # Check for reference image in MinIO
                if character.primary_image_path:
                    try:
                        reference_image_path = await self.storage.download_character_image(
                            character.primary_image_path
                        )
                        self.logger.debug(f"Using reference image: {reference_image_path}")
                    except Exception as e:
                        self.logger.warning(f"Could not load reference image: {e}")

                # Load style reference images (gold standard caricatures)
                style_ref_stmt = (
                    select(CharacterImage)
                    .where(CharacterImage.is_style_reference == True)
                    .limit(settings.GEMINI_STYLE_REFERENCE_COUNT)
                )
                style_result = await db.execute(style_ref_stmt)
                style_refs = style_result.scalars().all()

                for ref in style_refs:
                    try:
                        local_path = await self.storage.download_character_image(ref.image_path)
                        style_reference_paths.append(local_path)
                    except Exception as e:
                        self.logger.warning(f"Could not load style ref {ref.image_path}: {e}")

                if style_reference_paths:
                    self.logger.info(f"Loaded {len(style_reference_paths)} style references")

        # Generate scene image with Gemini + style references + character traits
        generated = await self.image_generator.generate_scene_image(
            scene_number=scene.scene_number,
            episode_id=self.episode_id,
            character_name=character_name,
            action_description=scene.action_description or "Character speaking to camera",
            reference_image_path=reference_image_path,
            style_reference_paths=style_reference_paths,
            character_traits=character_traits,
            resolution=settings.GEMINI_IMAGE_RESOLUTION,
        )
        
        # Upload generated image to MinIO for archival
        image_storage_path = await self.storage.upload_scene_image(
            race_id=self.race.id if self.race else 0,
            episode_id=self.episode_id,
            scene_number=scene.scene_number,
            file_path=generated.image_path,
        )
        
        # Update scene record with image path
        scene.source_image_path = image_storage_path
        
        self.logger.info(
            f"Scene {scene.scene_number}: Generated image in {generated.generation_time_ms}ms"
        )
        
        return generated.image_path

    async def _stitch_video(self, db: AsyncSession) -> str:
        """Stitch all scene clips into final video."""
        # Get completed scenes in order
        stmt = (
            select(Scene)
            .where(Scene.episode_id == self.episode_id, Scene.status == SceneStatus.COMPLETED)
            .order_by(Scene.scene_number)
        )
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        if len(scenes) != settings.VIDEO_SCENE_COUNT:
            self.logger.warning(f"Expected {settings.VIDEO_SCENE_COUNT} scenes, got {len(scenes)}")

        # Download clips from storage
        clip_paths = []
        for scene in scenes:
            if scene.video_clip_path:
                local_path = f"/tmp/videos/episode_{self.episode_id}/clip_{scene.scene_number:02d}.mp4"
                # TODO: Download from MinIO
                clip_paths.append(local_path)

        # Stitch
        result = await self.stitcher.stitch(self.episode_id, clip_paths)

        # Upload final video
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

        # Build YouTube metadata
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

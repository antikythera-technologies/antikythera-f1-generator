"""Main video generation pipeline."""

import asyncio
import json
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
from app.models.team import Team
# Personality traits loaded from DB via load_personality_traits_from_db()
from app.services.script_generator import ScriptGenerator, sanitize_dialogue
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
                # Only runs for scenes WITHOUT native audio (non-AV backends).
                # Audio-capable backends (fal-ltx, fal-ovi, etc.) produce native
                # audio from the prompt — TTS would overwrite that.
                if settings.TTS_ENABLED:
                    self.logger.info("PHASE 2c: Audio Generation (TTS + Mux)")
                    await self._generate_audio(db, scenes)

                # Update episode total costs from all scene costs
                await self._update_total_costs(db)

                # Phase 3: Stitch final video
                self.logger.info("PHASE 3: Video Stitching")
                await self._update_status(db, EpisodeStatus.STITCHING)
                final_path = await self._stitch_video(db)

                # Phase 4: YouTube Upload — DISABLED (manual only via dashboard)
                # YouTube upload must be triggered explicitly by the user.
                # Use POST /episodes/{id}/upload-youtube from the dashboard.
                self.logger.info("PHASE 4: Skipped — YouTube upload is manual only")

                # Phase 5: Cleanup old assets
                self.logger.info("PHASE 5: Cleanup")
                await self._cleanup_old_assets(db)

                # Mark as completed (ready for manual YouTube upload)
                await self._update_status(db, EpisodeStatus.COMPLETED)

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

        # Look up next session for outro teaser — calendar-aware
        self._next_race_info = None
        if self.race:
            ep_type = self.episode.episode_type if self.episode else ""
            if ep_type in ("post-sprint",):
                # Sprint race done → next is qualifying/main race at SAME circuit
                self._next_race_info = (
                    f"{self.race.race_name} Qualifying and Main Race "
                    f"at {self.race.circuit_name or self.race.country}"
                )
            elif ep_type in ("post-fp2", "post-fp1"):
                # Practice done → next is qualifying at same circuit
                self._next_race_info = (
                    f"{self.race.race_name} Qualifying "
                    f"at {self.race.circuit_name or self.race.country}"
                )
            elif ep_type in ("post-qualifying",):
                # Qualifying done → next is race at same circuit
                self._next_race_info = (
                    f"{self.race.race_name} Race "
                    f"at {self.race.circuit_name or self.race.country}"
                )
            else:
                # Post-race or unknown → next is the next round on the calendar
                next_race_stmt = (
                    select(Race)
                    .where(Race.round_number == self.race.round_number + 1)
                    .where(Race.season == self.race.season)
                )
                next_race_result = await db.execute(next_race_stmt)
                next_race = next_race_result.scalar_one_or_none()
                if next_race:
                    sprint_tag = " (Sprint Weekend)" if next_race.is_sprint_weekend else ""
                    self._next_race_info = (
                        f"{next_race.race_name} in {next_race.country}{sprint_tag}"
                    )
            if self._next_race_info:
                self.logger.info(f"Next session: {self._next_race_info}")

        # Build race context + load actual results from DB
        race_context = self._build_race_context()
        results_context = await self._load_race_results_context(db)
        if results_context:
            race_context += results_context
            self.logger.info("Loaded actual race results for script context")
        else:
            self.logger.warning("No race results in DB — script may have inaccurate positions!")

        # Fetch available running gags for this episode
        running_gags = await self._fetch_running_gags(db, characters)
        if running_gags:
            self.logger.info(f"Loaded {len(running_gags)} running gags for script generation")

        # Load team data for livery injection
        teams_stmt = select(Team).where(Team.is_active == True)
        teams_result = await db.execute(teams_stmt)
        teams_list = [
            {
                "name": t.name,
                "short_name": t.short_name,
                "car_description": t.car_description,
                "overalls_description": t.overalls_description,
                "livery_description": t.livery_description,
            }
            for t in teams_result.scalars().all()
        ]
        if teams_list:
            self.logger.info(f"Loaded {len(teams_list)} teams for livery injection")

        # Load news articles for topical comedy material
        news_context = None
        try:
            from app.services.news_scraper import NewsScraperService
            from app.models.scheduler import JobTriggerType
            news_service = NewsScraperService(db)
            # Map episode type to trigger type for news filtering
            trigger_map = {
                "post-race": JobTriggerType.POST_RACE,
                "post-sprint": JobTriggerType.POST_SPRINT,
                "post-qualifying": JobTriggerType.POST_QUALIFYING,
                "post-fp2": JobTriggerType.POST_FP2,
                "weekly-recap": JobTriggerType.WEEKLY_RECAP,
            }
            trigger_type = trigger_map.get(
                self.episode.episode_type.value, JobTriggerType.POST_RACE
            )
            articles = await news_service.get_articles_for_episode(
                trigger_type=trigger_type,
                race_id=self.race.id if self.race else None,
                limit=10,
            )
            if articles:
                news_context = [
                    {
                        "title": a.title,
                        "summary": a.summary or "",
                        "source": str(a.source_id or ""),
                        "published_at": a.published_at.isoformat() if a.published_at else "",
                    }
                    for a in articles
                ]
                self.logger.info(f"Loaded {len(news_context)} news articles for script context")
            else:
                self.logger.info("No recent news articles found for this episode")
        except Exception as e:
            self.logger.warning(f"Failed to load news articles: {e} — proceeding without news")

        # Load active storylines for narrative continuity
        storylines_context = None
        try:
            from app.models.storyline import Storyline
            from sqlalchemy.orm import selectinload
            storylines_stmt = (
                select(Storyline)
                .options(selectinload(Storyline.characters))
                .where(Storyline.is_active == True, Storyline.status == "active")
                .order_by(Storyline.priority.desc())
            )
            storylines_result = await db.execute(storylines_stmt)
            active_storylines = storylines_result.scalars().all()
            if active_storylines:
                storylines_context = [
                    {
                        "id": s.id,
                        "title": s.title,
                        "description": s.description,
                        "type": s.storyline_type.value if s.storyline_type else "general",
                        "comedy_notes": s.comedy_notes or "",
                        "current_beat": s.current_beat,
                        "plot_points": s.plot_points or [],
                        "character_slugs": [c.name for c in s.characters] if s.characters else [],
                    }
                    for s in active_storylines
                ]
                self.logger.info(f"Loaded {len(storylines_context)} active storylines for script context")
            else:
                self.logger.info("No active storylines found")
        except Exception as e:
            self.logger.warning(f"Failed to load storylines: {e} — proceeding without storylines")

        # Generate script
        script = await self.script_generator.generate_script(
            race_context=race_context,
            characters=character_data,
            episode_type=self.episode.episode_type.value,
            news_context=news_context,
            running_gags=running_gags,
            teams=teams_list,
            storylines=storylines_context,
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

            # Determine face visibility and character assignment
            face_visible = getattr(scene_script, "face_visible", True)
            voiceover_slug = getattr(scene_script, "voiceover_character", None)
            voiceover_char = next(
                (c for c in characters if c.name == voiceover_slug),
                None,
            ) if voiceover_slug else None

            scene = Scene(
                episode_id=self.episode_id,
                scene_number=scene_script.scene_number,
                # character_id = who is VISIBLE (face on screen)
                character_id=character.id if character and face_visible else None,
                dialogue=sanitize_dialogue(scene_script.dialogue) if scene_script.dialogue else None,
                action_description=scene_script.action,
                audio_description=scene_script.audio_description,
                # New dual-frame prompts
                start_frame_prompt=scene_script.start_frame_prompt or None,
                end_frame_prompt=scene_script.end_frame_prompt or None,
                camera_direction=scene_script.camera_direction or None,
                video_prompt=scene_script.video_prompt or None,
                scene_type=getattr(scene_script, "scene_type", None),
                face_visible=face_visible,
                voiceover_character_id=voiceover_char.id if voiceover_char else None,
                status=SceneStatus.PENDING,
            )
            db.add(scene)
            scenes.append(scene)

        await db.flush()
        self.logger.info(f"Created {len(scenes)} scene records with dual-frame prompts")

        # Track running gag usage from the generated script
        if script.gags_referenced:
            await self._record_gag_usage(db, script.gags_referenced)

        # Advance storyline beats for storylines referenced in this episode
        if storylines_context:
            try:
                for sl in storylines_context:
                    sl_id = sl.get("id")
                    if sl_id:
                        from app.models.storyline import Storyline
                        from sqlalchemy import update as sql_update
                        await db.execute(
                            sql_update(Storyline)
                            .where(Storyline.id == sl_id)
                            .values(current_beat=Storyline.current_beat + 1)
                        )
                        self.logger.info(
                            f"Advanced storyline \'{sl.get('title')}\' to next beat"
                        )
            except Exception as e:
                self.logger.warning(f"Failed to advance storyline beats: {e}")

        return scenes

    async def _load_race_results_context(self, db) -> str:
        """Load race results from DB for accurate script generation.

        Automatically selects the correct session type based on episode type:
        - post-sprint → sprint results + sprint qualifying
        - post-race → race results + qualifying
        - post-fp2 → FP2 results (practice)
        """
        from sqlalchemy import select as _sel
        from app.models.race_result import RaceResult, RaceSessionSummary, SessionType

        if not self.race:
            return ""

        # Determine which session results to load based on episode type
        episode_type = self.episode.episode_type.value if self.episode else "post-race"

        if episode_type == "post-sprint":
            primary_session = SessionType.SPRINT
            quali_session = SessionType.SPRINT_QUALIFYING
            session_label = "SPRINT RACE"
            quali_label = "SPRINT QUALIFYING"
        elif episode_type == "post-qualifying":
            # Qualifying episode: qualifying is the PRIMARY result, no race results yet
            primary_session = SessionType.QUALIFYING
            quali_session = None  # No secondary session
            session_label = "QUALIFYING"
            quali_label = None
        else:
            primary_session = SessionType.RACE
            quali_session = SessionType.QUALIFYING
            session_label = "RACE"
            quali_label = "QUALIFYING"

        self.logger.info(
            f"Loading {session_label} results for episode type '{episode_type}'"
        )

        lines = []

        # Get primary session results
        stmt = (
            _sel(RaceResult)
            .where(RaceResult.race_id == self.race.id)
            .where(RaceResult.session_type == primary_session)
            .order_by(RaceResult.position)
        )
        result = await db.execute(stmt)
        race_results = result.scalars().all()

        if race_results:
            lines.append(f"\nACTUAL {session_label} RESULTS (use these EXACT positions — do NOT invent results):")
            for r in race_results[:20]:
                status = f" ({r.status})" if r.status != "Finished" else ""
                grid = f" (started P{r.grid_position})" if r.grid_position else ""
                gained = f" [{r.positions_gained:+d} places]" if r.positions_gained else ""
                lines.append(
                    f"  P{r.position}: {r.driver_display_name or r.driver_name} "
                    f"({r.team or '?'}){grid}{gained}{status}"
                )
                if r.fastest_lap:
                    lines.append(f"    ^ Fastest lap: {r.fastest_lap_time or 'yes'}")
        else:
            self.logger.warning(
                f"No {session_label} results found for race {self.race.id}"
            )

        # Get qualifying results (skip if no secondary session, e.g. post-qualifying)
        if quali_session is not None:
            stmt = (
                _sel(RaceResult)
                .where(RaceResult.race_id == self.race.id)
                .where(RaceResult.session_type == quali_session)
                .order_by(RaceResult.position)
            )
            result = await db.execute(stmt)
            quali_results = result.scalars().all()

            if quali_results:
                lines.append(f"\n{quali_label} GRID:")
                for r in quali_results[:10]:
                    lines.append(
                        f"  P{r.position}: {r.driver_display_name or r.driver_name}"
                    )

        # Get session summary
        stmt = (
            _sel(RaceSessionSummary)
            .where(RaceSessionSummary.race_id == self.race.id)
            .where(RaceSessionSummary.session_type == primary_session)
        )
        result = await db.execute(stmt)
        summary = result.scalar_one_or_none()

        if summary:
            lines.append(f"\n{session_label} SUMMARY:")
            lines.append(f"  Podium: P1 {summary.winner}, P2 {summary.second}, P3 {summary.third}")
            if summary.total_overtakes:
                lines.append(f"  Total overtakes: {summary.total_overtakes}")
            if summary.safety_car_periods:
                lines.append(f"  Safety car periods: {summary.safety_car_periods}")
            if summary.vsc_periods:
                lines.append(f"  Virtual safety car periods: {summary.vsc_periods}")
            if summary.total_dnfs:
                lines.append(f"  DNFs: {summary.total_dnfs}")

        if lines:
            lines.append(f"\nCRITICAL: Use ONLY the {session_label.lower()} results above. Do NOT invent or guess positions.")

        return "\n".join(lines)

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
        """Fetch active running gags with cooldown enforcement.

        Gags within their cooldown period are skipped. Overused gags get
        freshness warnings. Limited to 8 gags per episode to avoid
        overwhelming the script with callbacks.
        """
        try:
            # Get current race round for cooldown calculation
            current_round = 1
            if self.race:
                current_round = self.race.round_number

            char_ids = [c.id for c in characters if hasattr(c, "id")]

            from sqlalchemy import or_
            stmt = (
                select(RunningGag)
                .where(RunningGag.is_active == True)
                .where(RunningGag.status.in_([GagStatus.ACTIVE, GagStatus.COOLING_DOWN]))
            )
            if char_ids:
                stmt = stmt.where(
                    or_(
                        RunningGag.primary_character_id.in_(char_ids),
                        RunningGag.secondary_character_id.in_(char_ids),
                        RunningGag.primary_character_id.is_(None),
                    )
                )
            stmt = stmt.order_by(RunningGag.humor_rating.desc())
            result = await db.execute(stmt)
            all_gags = result.scalars().all()

            if not all_gags:
                self.logger.info("No active running gags found in database")
                return None

            # Enforce cooldowns and filter
            gag_dicts = []
            skipped = []
            for gag in all_gags:
                # Check cooldown: if gag was used recently, skip it
                if gag.last_used_in_episode_id and gag.cooldown_races > 0:
                    from app.models.episode import Episode as _EpGag
                    last_ep = await db.get(_EpGag, gag.last_used_in_episode_id)
                    if last_ep and last_ep.race_id:
                        from app.models.race import Race as _RaceGag
                        last_race = await db.get(_RaceGag, last_ep.race_id)
                        if last_race:
                            races_since = current_round - last_race.round_number
                            if races_since < gag.cooldown_races:
                                skipped.append(f"{gag.title} ({gag.cooldown_races - races_since}r remaining)")
                                continue

                # Check exhaustion
                if gag.max_uses and gag.times_used >= gag.max_uses:
                    gag.status = GagStatus.EXHAUSTED
                    await db.flush()
                    skipped.append(f"{gag.title} (exhausted)")
                    continue

                # Add freshness indicator
                freshness = ""
                if gag.times_used == 0:
                    freshness = "FRESH"
                elif gag.times_used >= 4:
                    freshness = f"OVERUSED ({gag.times_used}x)"
                elif gag.times_used >= 2:
                    freshness = f"FAMILIAR ({gag.times_used}x)"

                gag_dicts.append({
                    "title": gag.title,
                    "description": gag.description,
                    "category": gag.category.value if gag.category else "",
                    "primary_character": "",
                    "setup": gag.setup or "",
                    "punchline": gag.punchline or "",
                    "variations": gag.variations or "",
                    "times_used": gag.times_used,
                    "freshness": freshness,
                })

            if skipped:
                self.logger.info(f"Gags on cooldown/exhausted: {skipped}")

            # Limit to 8 gags — prioritize FRESH ones, then by humor_rating
            if len(gag_dicts) > 8:
                fresh = [g for g in gag_dicts if g.get("freshness") == "FRESH"]
                others = [g for g in gag_dicts if g.get("freshness") != "FRESH"]
                gag_dicts = fresh[:4] + others[:(8 - len(fresh[:4]))]
                self.logger.info(f"Limited gags to 8 (from {len(fresh) + len(others)} available)")

            self.logger.info(f"Selected {len(gag_dicts)} gags for episode")
            return gag_dicts if gag_dicts else None

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
                else:
                    # Set cooling down status so next episode skips this gag
                    gag.status = GagStatus.COOLING_DOWN

                # Track which race this was used in
                if self.race:
                    gag.last_used_in_race = self.race.race_name

                # Dynamically increase cooldown for overused gags
                if gag.times_used > 4 and gag.cooldown_races < 3:
                    gag.cooldown_races = 3
                    self.logger.info(f"Gag '{title}' cooldown increased to 3 races (overused)")

                self.logger.info(f"Tracked gag usage: '{title}' (used {gag.times_used}x, cooling down)")
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

                # Load face reference — only via ComfyUI for self-hosted backends
                # For fal.ai backends, face refs are uploaded directly to fal CDN
                # in _get_scene_image_fal and _async_scene_image
                backend = settings.VIDEO_GENERATOR_DEFAULT
                if backend.startswith("fal-"):
                    # fal.ai path: just get the local filename if it exists
                    face_image = await self.storage.download_face_reference(character.name)
                else:
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

                    # Log LTX video generation cost (RunPod self-hosted, ~$0.50/hr GPU)
                    await self._log_api_usage(
                        db,
                        provider=APIProvider.LTX,
                        endpoint="comfyui/ltx-2.3-av",
                        cost_usd=0.0,  # Self-hosted RunPod — cost is per-hour, not per-clip
                        response_time_ms=clip.generation_time_ms,
                    )

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
                    self.logger.error(
                        f"Scene {scene.scene_number} has no image — marking FAILED "
                        f"(status={scene.status}, last_error={scene.last_error})"
                    )
                    if scene.status != SceneStatus.FAILED:
                        scene.status = SceneStatus.FAILED
                        scene.last_error = "No start frame image available for video generation"
                        await db.flush()
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

                    # Log Ovi video generation cost (RunPod self-hosted)
                    await self._log_api_usage(
                        db,
                        provider=APIProvider.OVI,
                        endpoint="runpod/ovi",
                        cost_usd=0.0,  # Self-hosted RunPod — cost is per-hour, not per-clip
                        response_time_ms=generation_time_ms,
                    )

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
        from app.services.fal_video_generator import FalVideoGenerator, build_f1_video_prompt as _build_f1_prompt

        backend = settings.VIDEO_GENERATOR_DEFAULT
        fal_gen = FalVideoGenerator(backend=backend)

        # ----- Phase 2a: Generate all scene images via fal.ai -----
        # CRITICAL: Commit scenes from Phase 1 so _async_scene_image (which
        # opens its own DB session) can find them. Without this commit,
        # scenes are only flushed (visible in THIS session) but not committed
        # (visible to OTHER sessions), causing "Scene X not found" errors.
        await db.commit()
        self.logger.info("PHASE 2a: Image Generation (fal.ai)")

        from app.jobs import _async_scene_image

        image_paths: dict[int, str] = {}

        for scene in scenes:
            if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)} fully complete — skipping"
                )
                continue

            if scene.start_frame_path:
                self.logger.info(
                    f"Scene {scene.scene_number}/{len(scenes)} already has image — skipping"
                )
                local_path = (
                    f"/tmp/f1-images/episode_{self.episode_id}"
                    f"_scene_{scene.scene_number:02d}_resume.png"
                )
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                bucket, object_name = scene.start_frame_path.split("/", 1)
                await self.storage.download_file(bucket, object_name, local_path)
                image_paths[scene.scene_number] = local_path
                continue

            self.logger.info(
                f"Generating image for scene {scene.scene_number}/{len(scenes)}"
            )

            try:
                # Delegate to jobs._async_scene_image which handles both
                # flux-lora (landscape) and instant-character (face reference)
                await _async_scene_image(
                    self.episode_id, scene.scene_number,
                    frame_type="start", set_completed=False,
                )

                # Reload scene to get updated paths
                await db.refresh(scene)

                if scene.start_frame_path:
                    local_path = (
                        f"/tmp/f1-images/episode_{self.episode_id}"
                        f"_scene_{scene.scene_number:02d}_start.png"
                    )
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    bucket, obj = scene.start_frame_path.split("/", 1)
                    await self.storage.download_file(bucket, obj, local_path)
                    image_paths[scene.scene_number] = local_path
                    self.logger.info(f"Scene {scene.scene_number}: Image ready")
                else:
                    self.logger.error(
                        f"Scene {scene.scene_number}: _async_scene_image returned "
                        "but start_frame_path is still NULL — marking FAILED"
                    )
                    scene.status = SceneStatus.FAILED
                    scene.last_error = "Image generation completed but no image path was saved"
                    await db.flush()

            except Exception as e:
                self.logger.error(f"Scene {scene.scene_number} image failed: {e}")
                await db.refresh(scene)
                scene.status = SceneStatus.FAILED
                scene.last_error = f"Image generation: {e}"
                scene.retry_count += 1
                await db.flush()

        await db.commit()
        self.logger.info(f"Phase 2a complete: {len(image_paths)} images")

        # ----- Phase 2a-val: Image Validation (before expensive video gen) -----
        self.logger.info("PHASE 2a-val: Start Frame Validation")
        from app.services.scene_validator import SceneValidator, adapt_prompt_for_validation_failure

        validator = SceneValidator()
        MAX_IMAGE_RETRIES = 2

        for scene in scenes:
            if scene.scene_number not in image_paths:
                continue
            if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                continue

            local_image = image_paths[scene.scene_number]

            # Download face reference for comparison (if character scene)
            ref_path = None
            if scene.face_visible and scene.character_id:
                try:
                    char, _, _ = await self._load_character_context(db, scene)
                    if char:
                        ref_path = await self.storage.download_face_reference(char.name)
                except Exception:
                    pass

            # Load team context for validation
            _val_team_context = None
            if scene.character_id:
                from app.models.team import Team as _ValTeam
                from app.models.character import Character as _ValChar
                _val_char = await db.get(_ValChar, scene.character_id)
                if _val_char and hasattr(_val_char, 'team_id') and _val_char.team_id:
                    _val_team_obj = await db.get(_ValTeam, _val_char.team_id)
                    if _val_team_obj:
                        _val_team_context = {
                            "team_name": _val_team_obj.name,
                            "car_description": _val_team_obj.car_description,
                            "primary_colour": _val_team_obj.primary_colour,
                            "secondary_colour": _val_team_obj.secondary_colour,
                        }

            for img_attempt in range(1 + MAX_IMAGE_RETRIES):
                img_result = await validator.validate_image(
                    local_image, scene.scene_number,
                    scene_type=scene.scene_type,
                    face_visible=bool(scene.face_visible),
                    reference_image_path=ref_path,
                    prompt_text=scene.start_frame_prompt,
                    team_context=_val_team_context,
                )

                # Log validation cost (~$0.003 per call)
                await self._log_api_usage(
                    db, APIProvider.ANTHROPIC,
                    endpoint="claude-vision/image-validation",
                    cost_usd=0.003,
                )

                if img_result.passed:
                    scene.validation_status = "passed"
                    scene.validation_issues = None
                    await db.flush()
                    self.logger.info(
                        f"Scene {scene.scene_number}: Image validation PASSED "
                        f"(attempt {img_attempt + 1})"
                    )
                    break
                else:
                    issues = ", ".join(img_result.issues)
                    scene.validation_status = "failed"
                    scene.validation_issues = json.dumps(img_result.issues)
                    await db.flush()
                    self.logger.warning(
                        f"Scene {scene.scene_number}: Image validation FAILED "
                        f"(attempt {img_attempt + 1}): {issues}"
                    )

                    if img_attempt < MAX_IMAGE_RETRIES:
                        # Adapt prompt and regenerate image
                        adapted = adapt_prompt_for_validation_failure(
                            scene, img_result
                        )
                        if adapted:
                            scene.start_frame_path = None
                            await db.flush()
                            await db.commit()

                            try:
                                await _async_scene_image(
                                    self.episode_id, scene.scene_number,
                                    frame_type="start", set_completed=False,
                                )
                                await db.refresh(scene)

                                if scene.start_frame_path:
                                    bucket, obj = scene.start_frame_path.split("/", 1)
                                    new_local = (
                                        f"/tmp/f1-images/episode_{self.episode_id}"
                                        f"_scene_{scene.scene_number:02d}_retry.png"
                                    )
                                    os.makedirs(os.path.dirname(new_local), exist_ok=True)
                                    await self.storage.download_file(bucket, obj, new_local)
                                    image_paths[scene.scene_number] = new_local
                                    local_image = new_local
                                else:
                                    self.logger.error(
                                        f"Scene {scene.scene_number}: Retry image gen "
                                        "failed — no path saved"
                                    )
                                    break
                            except Exception as e:
                                self.logger.error(
                                    f"Scene {scene.scene_number}: Retry image gen "
                                    f"raised: {e}"
                                )
                                break
                        else:
                            self.logger.info(
                                f"Scene {scene.scene_number}: No prompt adaptation "
                                "possible, proceeding to video"
                            )
                            break
                    else:
                        # Check if any CRITICAL checks failed — these must block video gen
                        critical_fails = [
                            c for c in img_result.checks
                            if not c.passed and c.name in (
                                "car_count", "direction", "clothing", "anatomy"
                            )
                        ]
                        if critical_fails:
                            fail_names = [c.name for c in critical_fails]
                            scene.status = SceneStatus.FAILED
                            scene.validation_status = "failed_critical"
                            scene.validation_issues = json.dumps(img_result.issues)
                            scene.last_error = (
                                f"Critical image validation failures: {fail_names}. "
                                f"Blocking video generation."
                            )
                            await db.flush()
                            self.logger.error(
                                f"Scene {scene.scene_number}: CRITICAL image validation "
                                f"failures {fail_names} — BLOCKING video generation"
                            )
                            # Remove from image_paths so Phase 2b skips it
                            image_paths.pop(scene.scene_number, None)
                        else:
                            scene.validation_status = "failed_minor"
                            scene.validation_issues = json.dumps(img_result.issues)
                            await db.flush()
                            self.logger.warning(
                                f"Scene {scene.scene_number}: Minor image issues, "
                                "proceeding with current image"
                            )

        await db.commit()
        self.logger.info("Phase 2a-val complete")

        # ----- Phase 2a-bis: End Frame Generation (FLF) -----
        from app.services.fal_video_generator import FAL_FLF_CAPABLE
        from app.pipeline.flf_router import should_generate_end_frame

        end_image_paths: dict[int, str] = {}
        backend_enum = fal_gen.backend

        if backend_enum in FAL_FLF_CAPABLE:
            self.logger.info("PHASE 2a-bis: End Frame Generation (FLF)")

            for idx, scene in enumerate(scenes):
                if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                    continue

                if not should_generate_end_frame(
                    scene_type=scene.scene_type,
                    scene_index=idx,
                    total_scenes=len(scenes),
                    backend_supports_flf=True,
                ):
                    continue

                # Skip if no end frame prompt
                if not scene.end_frame_prompt:
                    self.logger.debug(
                        f"Scene {scene.scene_number}: No end_frame_prompt — skipping FLF"
                    )
                    continue

                # Skip if already has end frame
                if scene.end_frame_path:
                    self.logger.info(
                        f"Scene {scene.scene_number}: Already has end frame — reusing"
                    )
                    local_path = (
                        f"/tmp/f1-images/episode_{self.episode_id}"
                        f"_scene_{scene.scene_number:02d}_end_resume.png"
                    )
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    bucket, object_name = scene.end_frame_path.split("/", 1)
                    await self.storage.download_file(bucket, object_name, local_path)
                    end_image_paths[scene.scene_number] = local_path
                    continue

                self.logger.info(
                    f"Generating end frame for scene {scene.scene_number}/{len(scenes)} (FLF)"
                )

                try:
                    end_image = await self._get_scene_image_fal(db, scene, frame_type="end")
                    end_image_paths[scene.scene_number] = end_image
                    self.logger.info(f"Scene {scene.scene_number}: End frame ready")
                    await db.flush()
                except Exception as e:
                    self.logger.warning(
                        f"Scene {scene.scene_number} end frame failed: {e} — "
                        f"will proceed without FLF for this scene"
                    )

            await db.commit()
            self.logger.info(
                f"Phase 2a-bis complete: {len(end_image_paths)} end frames"
            )
        else:
            self.logger.info("Backend does not support FLF — skipping end frame generation")

        # ----- Phase 2b: Generate video clips via fal.ai -----
        self.logger.info(
            f"PHASE 2b: Video Generation ({fal_gen.display_name})"
        )

        for scene in scenes:
            if scene.status == SceneStatus.COMPLETED and scene.video_clip_path:
                continue

            if scene.scene_number not in image_paths:
                self.logger.error(
                    f"Scene {scene.scene_number} has no image — marking FAILED "
                    f"(status={scene.status}, last_error={scene.last_error})"
                )
                if scene.status != SceneStatus.FAILED:
                    scene.status = SceneStatus.FAILED
                    scene.last_error = "No start frame image available for video generation"
                    await db.flush()
                continue

            self.logger.info(
                f"Generating video for scene {scene.scene_number}/{len(scenes)}"
            )

            try:
                # Upload image to fal.ai CDN
                local_image = image_paths[scene.scene_number]
                image_url = await fal_gen.upload_image(local_image)

                # Load team data for video prompt context
                _scene_team = None
                if scene.character_id:
                    from app.models.character import Character as _CharModel
                    _char_obj = await db.get(_CharModel, scene.character_id)
                    if _char_obj and _char_obj.team_id:
                        from app.models.team import Team as _TeamModel
                        _scene_team = await db.get(_TeamModel, _char_obj.team_id)

                # Generate video
                start_time = datetime.utcnow()
                # Extract voice/accent from character personality for speech synthesis
                voice_desc = None
                char_traits = {}
                _voice_char_id = scene.character_id or scene.voiceover_character_id
                if _voice_char_id:
                    if scene.character_id:
                        _, char_traits, _ = await self._load_character_context(db, scene)
                    else:
                        # Voiceover narrator (e.g. Croft on ACTION_REPLAY)
                        from app.models.character import Character as _CharModel
                        _vo_char = await db.get(_CharModel, _voice_char_id)
                        char_traits = {}
                        if _vo_char and _vo_char.personality:
                            try:
                                from app.services.personality import load_personality_traits_from_db
                                char_traits = load_personality_traits_from_db(_vo_char.personality)
                            except Exception as e:
                                self.logger.warning(f"Scene {scene.scene_number}: Could not parse voiceover personality: {e}")
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

                # Audio prompt: ambient sounds only (voice goes into video prompt)
                rich_audio = scene.audio_description

                # Upload end frame if FLF available for this scene
                end_image_url = None
                if scene.scene_number in end_image_paths:
                    end_image_url = await fal_gen.upload_image(
                        end_image_paths[scene.scene_number]
                    )
                    self.logger.info(
                        f"Scene {scene.scene_number}: End frame uploaded for FLF"
                    )

                # Extract character animation from personality traits
                _char_anim = None
                if char_traits:
                    _char_anim = {
                        "signature_expression": char_traits.get("signature_expression"),
                        "signature_pose": char_traits.get("signature_pose"),
                        "comedy_angle": char_traits.get("comedy_angle"),
                    }

                clip = await fal_gen.generate_clip(
                    scene_number=scene.scene_number,
                    image_url=image_url,
                    prompt=_build_f1_prompt(
                        (scene.video_prompt or scene.start_frame_prompt or "").replace("ANTKF1STYLE", "").strip(),
                        scene_type=str(scene.scene_type) if scene.scene_type else None,
                        face_visible=bool(scene.face_visible),
                        dialogue=scene.dialogue,
                        team_name=_scene_team.name if _scene_team else None,
                        car_description=_scene_team.car_description if _scene_team else None,
                        overalls_description=_scene_team.overalls_description if _scene_team else None,
                        camera_direction=scene.camera_direction,
                        character_animation=_char_anim,
                        livery_description=_scene_team.livery_description if _scene_team else None,
                    ),
                    dialogue=scene.dialogue,
                    audio_description=rich_audio,
                    face_visible=bool(scene.face_visible),
                    end_image_url=end_image_url,
                    voice_description=voice_desc,
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

                # Track video cost on scene
                from decimal import Decimal as _VDec
                fal_cost_map = {
                    "fal-ovi": 0.20,
                    "fal-ltx": 0.30,
                    "fal-kling-std": 0.42,
                    "fal-kling-std-audio": 0.63,
                    "fal-kling-pro": 0.42,
                    "fal-kling-pro-audio": 0.84,
                    "fal-kling-o1-flf": 0.56,
                    "fal-vidu-q1-flf": 0.50,
                    "fal-wan-flf": 0.50,
                }
                cost = fal_cost_map.get(backend, 0.20)
                scene.video_cost_usd = _VDec(str(cost))  # Latest generation cost only
                provider_map = {
                    "fal-ovi": APIProvider.FAL_OVI,
                    "fal-ltx": APIProvider.FAL_LTX,
                    "fal-kling-std": APIProvider.FAL_KLING_STD,
                    "fal-kling-std-audio": APIProvider.FAL_KLING_STD_AUDIO,
                    "fal-kling-pro": APIProvider.FAL_KLING_PRO,
                    "fal-kling-pro-audio": APIProvider.FAL_KLING_PRO_AUDIO,
                    "fal-kling-o1-flf": APIProvider.FAL_KLING_O1_FLF,
                    "fal-vidu-q1-flf": APIProvider.FAL_VIDU_Q1_FLF,
                    "fal-wan-flf": APIProvider.FAL_WAN_FLF,
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

        # ----- Phase 2d: Video Validation + Auto-Retry -----
        self.logger.info("PHASE 2d: Video Validation & Auto-Retry")

        MAX_VIDEO_RETRIES = 1  # max 1 retry per scene (2 total attempts)

        for scene in scenes:
            if scene.status != SceneStatus.COMPLETED or not scene.video_clip_path:
                continue

            for vid_attempt in range(1 + MAX_VIDEO_RETRIES):
                # Download video for validation
                local_video = (
                    f"/tmp/f1-validate/ep{self.episode_id}"
                    f"_s{scene.scene_number:02d}.mp4"
                )
                os.makedirs(os.path.dirname(local_video), exist_ok=True)
                bucket, obj = scene.video_clip_path.split("/", 1)
                await self.storage.download_file(bucket, obj, local_video)

                # Quick motion check (no API cost)
                has_motion = await validator.check_video_motion(local_video)
                if not has_motion:
                    self.logger.warning(
                        f"Scene {scene.scene_number}: Video appears STATIC/FROZEN"
                    )
                    # Static video = fail, regenerate
                    if vid_attempt < MAX_VIDEO_RETRIES:
                        scene.video_clip_path = None
                        scene.status = SceneStatus.GENERATING
                        scene.video_prompt = (scene.video_prompt or "") + (
                            " CRITICAL: The subject must have visible continuous motion "
                            "throughout the entire clip. No static or frozen frames."
                        )
                        await db.flush()
                        await db.commit()

                        # Re-run video only (image is fine)
                        if scene.scene_number in image_paths:
                            try:
                                local_image = image_paths[scene.scene_number]
                                image_url = await fal_gen.upload_image(local_image)

                                _scene_team = None
                                if scene.character_id:
                                    from app.models.character import Character as _CharModel2
                                    _char_obj2 = await db.get(_CharModel2, scene.character_id)
                                    if _char_obj2 and _char_obj2.team_id:
                                        from app.models.team import Team as _TeamModel
                                        _scene_team = await db.get(_TeamModel, _char_obj2.team_id)

                                clip = await fal_gen.generate_clip(
                                    scene_number=scene.scene_number,
                                    image_url=image_url,
                                    prompt=_build_f1_prompt(
                                        (scene.video_prompt or "").replace("ANTKF1STYLE", "").strip(),
                                        scene_type=str(scene.scene_type) if scene.scene_type else None,
                                        face_visible=bool(scene.face_visible),
                                        dialogue=scene.dialogue,
                                        team_name=_scene_team.name if _scene_team else None,
                                        car_description=_scene_team.car_description if _scene_team else None,
                                        overalls_description=_scene_team.overalls_description if _scene_team else None,
                                        camera_direction=scene.camera_direction,
                                        livery_description=_scene_team.livery_description if _scene_team else None,
                                    ),
                                    dialogue=scene.dialogue,
                                    audio_description=scene.audio_description,
                                    face_visible=bool(scene.face_visible),
                                )

                                clip_path = await self.storage.upload_video_clip(
                                    race_id=self.race.id if self.race else 0,
                                    episode_id=self.episode_id,
                                    scene_number=scene.scene_number,
                                    file_path=clip.video_path,
                                )
                                scene.video_clip_path = clip_path
                                scene.status = SceneStatus.COMPLETED

                                from decimal import Decimal as _VRetryDec
                                fal_cost_map_retry = {
                                    "fal-ovi": 0.20, "fal-ltx": 0.30,
                                    "fal-kling-std": 0.42, "fal-kling-pro": 0.42,
                                }
                                retry_cost = fal_cost_map_retry.get(backend, 0.20)
                                scene.video_cost_usd = (
                                    (scene.video_cost_usd or _VRetryDec(0))
                                    + _VRetryDec(str(retry_cost))
                                )
                                await db.flush()
                                self.logger.info(
                                    f"Scene {scene.scene_number}: Video retry "
                                    f"complete (${retry_cost})"
                                )
                            except Exception as e:
                                self.logger.error(
                                    f"Scene {scene.scene_number}: Video retry "
                                    f"failed: {e}"
                                )
                                scene.status = SceneStatus.COMPLETED  # keep old
                                break
                    continue

                # Full Claude Vision validation
                vid_result = await validator.validate_scene(scene)

                await self._log_api_usage(
                    db, APIProvider.ANTHROPIC,
                    endpoint="claude-vision/video-validation",
                    cost_usd=0.015,  # ~$0.003 per check x5 frames
                )

                if vid_result.passed:
                    scene.validation_status = "passed"
                    scene.validation_issues = None
                    self.logger.info(
                        f"Scene {scene.scene_number}: Video validation PASSED"
                    )
                    await db.flush()
                    break
                else:
                    issues = ", ".join(vid_result.issues)
                    scene.validation_status = "failed"
                    scene.validation_issues = json.dumps(vid_result.issues)
                    self.logger.warning(
                        f"Scene {scene.scene_number}: Video validation FAILED: "
                        f"{issues}"
                    )

                    if vid_attempt < MAX_VIDEO_RETRIES:
                        adapted = adapt_prompt_for_validation_failure(scene, vid_result)
                        if adapted:
                            scene.start_frame_path = None
                            scene.video_clip_path = None
                            scene.status = SceneStatus.GENERATING
                            await db.flush()
                            await db.commit()

                            try:
                                await _async_scene_image(
                                    self.episode_id, scene.scene_number,
                                    frame_type="start", set_completed=False,
                                )
                                await db.refresh(scene)
                                if scene.start_frame_path:
                                    bucket2, obj2 = scene.start_frame_path.split("/", 1)
                                    new_path = (
                                        f"/tmp/f1-images/episode_{self.episode_id}"
                                        f"_scene_{scene.scene_number:02d}_vretry.png"
                                    )
                                    os.makedirs(os.path.dirname(new_path), exist_ok=True)
                                    await self.storage.download_file(bucket2, obj2, new_path)
                                    image_paths[scene.scene_number] = new_path

                                    image_url2 = await fal_gen.upload_image(new_path)
                                    _scene_team2 = None
                                    if scene.character_id:
                                        from app.models.character import Character as _CM3
                                        _co3 = await db.get(_CM3, scene.character_id)
                                        if _co3 and _co3.team_id:
                                            from app.models.team import Team as _TM2
                                            _scene_team2 = await db.get(_TM2, _co3.team_id)

                                    clip2 = await fal_gen.generate_clip(
                                        scene_number=scene.scene_number,
                                        image_url=image_url2,
                                        prompt=_build_f1_prompt(
                                            (scene.video_prompt or "").replace("ANTKF1STYLE", "").strip(),
                                            scene_type=str(scene.scene_type) if scene.scene_type else None,
                                            face_visible=bool(scene.face_visible),
                                            dialogue=scene.dialogue,
                                            team_name=_scene_team2.name if _scene_team2 else None,
                                            car_description=_scene_team2.car_description if _scene_team2 else None,
                                            overalls_description=_scene_team2.overalls_description if _scene_team2 else None,
                                            camera_direction=scene.camera_direction,
                                            livery_description=_scene_team2.livery_description if _scene_team2 else None,
                                        ),
                                        dialogue=scene.dialogue,
                                        audio_description=scene.audio_description,
                                        face_visible=bool(scene.face_visible),
                                    )

                                    clip_path2 = await self.storage.upload_video_clip(
                                        race_id=self.race.id if self.race else 0,
                                        episode_id=self.episode_id,
                                        scene_number=scene.scene_number,
                                        file_path=clip2.video_path,
                                    )
                                    scene.video_clip_path = clip_path2
                                    scene.status = SceneStatus.COMPLETED
                                    await db.flush()
                                    self.logger.info(
                                        f"Scene {scene.scene_number}: Full retry complete"
                                    )
                            except Exception as e:
                                self.logger.error(
                                    f"Scene {scene.scene_number}: Full retry failed: {e}"
                                )
                                scene.status = SceneStatus.COMPLETED
                                break
                    else:
                        self.logger.warning(
                            f"Scene {scene.scene_number}: Max video retries "
                            "reached, accepting with issues"
                        )
                        await db.flush()

            await db.commit()

        # ----- Phase 2d-audio: Audio Validation -----
        if self._use_ltx():  # LTX generates native audio
            self.logger.info("Phase 2d-audio: Running audio validation on all clips")
            for scene in scenes:
                if scene.status == SceneStatus.FAILED or not scene.video_clip_path:
                    continue
                try:
                    local_video = await self.storage.download_temp(scene.video_clip_path)
                    has_dialogue = bool(scene.dialogue and scene.dialogue.strip())
                    audio_result = await validator.validate_audio(
                        local_video,
                        has_dialogue=has_dialogue,
                        audio_description=scene.audio_description,
                    )
                    if not audio_result.passed:
                        self.logger.warning(
                            f"Scene {scene.scene_number}: Audio validation FAILED: "
                            f"{audio_result.issues}"
                        )
                        # Log issues but don't fail the scene — audio issues are
                        # less critical than missing video. Flag for manual review.
                        if scene.validation_issues is None:
                            scene.validation_issues = {}
                        scene.validation_issues["audio"] = audio_result.issues
                        await db.flush()
                    else:
                        self.logger.info(
                            f"Scene {scene.scene_number}: Audio validation PASSED"
                        )
                except Exception as e:
                    self.logger.warning(
                        f"Scene {scene.scene_number}: Audio validation error: {e}"
                    )

            await db.commit()

        self.logger.info("Phase 2d complete — validation finished")

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

        # Backends that produce native audio — skip TTS for these
        from app.services.fal_video_generator import FAL_AUDIO_BACKENDS, FalBackend
        native_audio_backends = {b.value for b in FAL_AUDIO_BACKENDS}

        for scene in scenes:
            if scene.status != SceneStatus.COMPLETED or not scene.video_clip_path:
                self.logger.debug(
                    f"Scene {scene.scene_number}: Skipping audio "
                    f"(status={scene.status}, clip={bool(scene.video_clip_path)})"
                )
                continue

            # Skip TTS for backends that generate native audio
            if scene.video_generator and scene.video_generator in native_audio_backends:
                self.logger.info(
                    f"Scene {scene.scene_number}: Native audio from "
                    f"{scene.video_generator} — skipping TTS"
                )
                audio_success += 1
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

    async def _get_scene_image_fal(self, db: AsyncSession, scene: Scene, frame_type: str = "start") -> str:
        """Generate scene image via fal.ai with smart backend routing.

        Routes based on scene type and face visibility:
        - face_visible=False (ACTION_REPLAY, ESTABLISHING without character):
          → flux-lora (LoRA style only, no face reference)
        - face_visible=True + character with face ref available:
          → instant-character (face ref + LoRA for identity preservation)
        - face_visible=True but no face ref file:
          → flux-lora fallback (LoRA + detailed prompt description)
        """
        import re
        import tempfile
        import httpx

        from app.services.personality import load_personality_traits_from_db

        fal_key = settings.FAL_KEY
        if not fal_key:
            raise RuntimeError("FAL_KEY not configured")

        # Load character context
        character_name = "generic_commentator"
        character_traits: dict = {}
        character = None

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

        # Load episode-level character appearance for clothing consistency
        episode_appearance = ""
        if character and self.episode and hasattr(self.episode, "character_appearances"):
            if self.episode.character_appearances:
                episode_appearance = self.episode.character_appearances.get(
                    character.name, ""
                )
                if episode_appearance:
                    self.logger.info(
                        f"Scene {scene.scene_number}: Using episode appearance for {character.name}"
                    )

        # Determine which prompt to use
        if frame_type == "end":
            frame_prompt = scene.end_frame_prompt or scene.action_description or "Character speaking to camera"
        else:
            frame_prompt = scene.start_frame_prompt or scene.action_description or "Character speaking to camera"

        # Determine if face reference is needed
        use_face_reference = getattr(scene, "face_visible", True) and scene.character_id is not None

        # Upload face reference to fal CDN for character scenes
        face_ref_url = None
        if character and use_face_reference:
            face_local = await self.storage.download_face_reference(character.name)
            if face_local:
                import fal_client
                self.logger.info(f"Scene {scene.scene_number}: Uploading face reference for {character.name}")
                face_ref_url = await asyncio.get_event_loop().run_in_executor(
                    None, fal_client.upload_file, face_local
                )
                scene.face_reference_url = face_ref_url

                # Link to CharacterImage record
                from app.models.character import CharacterImage
                ci_stmt = (
                    select(CharacterImage)
                    .where(CharacterImage.character_id == scene.character_id)
                    .order_by(CharacterImage.is_primary.desc(), CharacterImage.id)
                    .limit(1)
                )
                ci_result = await db.execute(ci_stmt)
                ci = ci_result.scalar_one_or_none()
                if ci:
                    scene.character_image_id = ci.id

        # Choose image backend based on scene properties
        if not use_face_reference:
            image_backend = "flux-lora"
            self.logger.info(
                f"Scene {scene.scene_number}: Using flux-lora "
                f"(face_visible={getattr(scene, 'face_visible', True)}, scene_type={scene.scene_type})"
            )
        elif face_ref_url:
            image_backend = "instant-character"
            self.logger.info(
                f"Scene {scene.scene_number}: Using instant-character "
                f"(face_visible=True, face ref available for {character_name})"
            )
        else:
            image_backend = "flux-lora"
            self.logger.info(
                f"Scene {scene.scene_number}: Using flux-lora fallback "
                f"(face_visible=True but no face ref file for {character_name})"
            )

        # Build prompt based on backend
        if image_backend == "flux-lora" and not use_face_reference:
            # --- Landscape/action prompt with racing direction rules ---
            racing_direction_rule = ""
            racing_keywords = [
                "car", "cars", "race", "racing", "overtake", "track", "circuit",
                "straight", "corner", "grid", "cockpit", "onboard", "on-board",
            ]
            if any(kw in (frame_prompt or "").lower() for kw in racing_keywords):
                pov_keywords = ["cockpit pov", "onboard", "on-board", "helmet cam", "driver pov"]
                is_pov = any(kw in (frame_prompt or "").lower() for kw in pov_keywords)
                if is_pov:
                    racing_direction_rule = (
                        "CRITICAL COCKPIT POV: You are the driver looking FORWARD through the halo device. "
                        "ALL cars visible ahead are DRIVING AWAY from you — you are CHASING them. "
                        "You can ONLY see their REAR: rear wings, rear diffusers, exhaust pipes, tail lights, "
                        "rear tyres. You CANNOT see any car's front wing, nose, or headlights. "
                        "Every single car points in the SAME direction — AWAY from the camera. "
                        "This is a chase scene, not a head-on collision. "
                        "TRACK LAYOUT: Tarmac surface in the centre, kerbs (red-white or yellow) on BOTH EDGES of the track only. "
                        "There is NO kerb, barrier, or divider in the middle of the track. The track is one continuous surface. "
                        "GRID SIZE: Maximum 22 cars on track (11 teams x 2 drivers). Never show more than 22 cars. "
                    )
                else:
                    racing_direction_rule = (
                        "ALL cars MUST face the SAME direction, driving AWAY from the camera. "
                        "Show only the REAR of every car — rear wings, rear diffusers, exhaust, rear tyres. "
                        "NO car faces towards the camera. NO car faces the opposite direction. "
                        "TRACK LAYOUT: Tarmac surface in the centre, kerbs (red-white or yellow) on BOTH EDGES only. "
                        "NO kerb, barrier, or divider in the middle of the track. One continuous racing surface. "
                        "Maximum 22 cars on track (11 teams x 2 drivers). "
                        "F1 cars are open-cockpit single-seaters with NO roof. The halo is a thin curved bar above the driver, NOT a canopy or roof. "
                    )
            # For ALL non-face scenes: enforce F1 car count
            # ESTABLISHING shots: focus on environment, minimal cars
            _st = (scene.scene_type or '').upper()
            if _st in ('ESTABLISHING', 'TITLE_CARD'):
                racing_direction_rule += (
                    "IMPORTANT: This is an atmospheric/establishing shot. "
                    "Focus on the ENVIRONMENT — circuit, skyline, sunset, paddock. "
                    "Show at most 3-5 cars in the background, NOT a full grid. "
                    "Cars are secondary to the setting. "
                    "F1 has only 22 cars total (11 teams x 2). NEVER show more than 22 cars. "
                )
            elif not racing_direction_rule:
                racing_direction_rule = (
                    "F1 has exactly 22 cars (11 teams x 2 drivers). "
                    "NEVER show more than 22 cars in any scene. "
                )

            full_prompt = (
                f"ANTKF1STYLE {racing_direction_rule} "
                f"{frame_prompt} "
                "Satirical caricature art style, dramatic lighting, vibrant colors. "
                "No text, no words, no letters, no watermarks."
            )
        else:
            # --- Character scene: rewrite close-ups + add traits ---
            frame_prompt = re.sub(r'(?i)\bMEDIUM\s+CLOSE[- ]?UP\b', 'MEDIUM SHOT', frame_prompt)
            frame_prompt = re.sub(r'(?i)\bEXTREME\s+CLOSE[- ]?UP\b', 'MEDIUM SHOT', frame_prompt)
            frame_prompt = re.sub(r'(?i)\bCLOSE[- ]?UP\b', 'MEDIUM SHOT', frame_prompt)

            physical = character_traits.get("physical_features", "")
            prompt_parts = ["WIDE MEDIUM SHOT showing full character from knees up, camera 5 meters away, plenty of headroom above the head.", frame_prompt]
            # Team overalls from DB are ground truth — always prefer over LLM-generated appearance
            if character and hasattr(character, 'team_id') and character.team_id:
                from app.models.team import Team as _Team
                _team_obj = await db.get(_Team, character.team_id)
                if _team_obj and _team_obj.overalls_description:
                    episode_appearance = _team_obj.overalls_description

            if episode_appearance:
                prompt_parts.append(f"Character appearance for this episode: {episode_appearance}")
            elif physical:
                prompt_parts.append(f"Character physical traits: {physical}")
            prompt_parts.append(
                "Satirical caricature style with oversized head, "
                "photorealistic skin with visible pores. Dramatic lighting with deep shadows. "
                "CRITICAL FRAMING: The character must be shown from the knees or waist up. "
                "Full head, all hair, and both shoulders MUST be visible with clear space above the head. "
                "NEVER crop the top of the head. Camera is far back, NOT close to the face. "
                "Any vehicles visible MUST be Formula 1 open-cockpit cars (NO ROOF) in the character team livery. No road cars. "
                "Maximum 22 F1 cars visible in any scene. "
                "The character MUST wear RACING OVERALLS (fireproof race suit with team colours and sponsor logos). "
                "NOT a business suit, blazer, or formal wear. Racing overalls zip up the front and have sponsor patches. "
                "No text, no words, no letters, no logos, no watermarks on clothing or background."
            )
            full_prompt = " ".join(prompt_parts)

        start_time = datetime.utcnow()

        # ---- Generate via instant-character ----
        if image_backend == "instant-character" and face_ref_url:
            import fal_client as _fal

            ic_args = {
                "prompt": full_prompt,
                "image_url": face_ref_url,
                "negative_prompt": (
                    "cropped head, cut off head, cut off hair, top of head missing, "
                    "forehead cropped, extreme close-up, tight crop, face filling frame, "
                    "zoomed in, macro, portrait crop, chin to forehead only, "
                    "shoulder-up only, passport photo, mugshot, headshot, face only"
                ),
                "image_size": {"width": 1280, "height": 1280},
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
                "scale": 0.3,
                "output_format": "png",
                "loras": [{"path": self.FAL_LORA_URL, "scale": 1.0, "trigger_word": "ANTKF1STYLE"}],
            }

            self.logger.info(f"Scene {scene.scene_number}: Submitting to fal-ai/instant-character")

            # Run synchronous fal_client.subscribe in executor to avoid blocking async event loop
            import functools
            ic_result = await asyncio.get_event_loop().run_in_executor(
                None,
                functools.partial(
                    _fal.subscribe,
                    "fal-ai/instant-character",
                    arguments=ic_args,
                    with_logs=True,
                ),
            )

            ic_images = ic_result.get("images", [])
            if not ic_images:
                raise RuntimeError("fal.ai instant-character returned no images")

            # Download image
            async with httpx.AsyncClient(timeout=120) as dl:
                img_resp = await dl.get(ic_images[0]["url"])
                img_resp.raise_for_status()

            tmp_path = os.path.join(
                tempfile.gettempdir(),
                f"f1_scene_{self.episode_id}_{scene.scene_number:02d}_{frame_type}.png",
            )
            os.makedirs(os.path.dirname(tmp_path), exist_ok=True)

            # Crop from 1280x1280 to 1280x720 — keep top to preserve head/hair — keep top to preserve head/hair
            from PIL import Image as PILImage
            import io
            img_full = PILImage.open(io.BytesIO(img_resp.content))
            if img_full.height > 720:
                img_cropped = img_full.crop((0, 0, img_full.width, 720))
                img_cropped.save(tmp_path, "PNG")
                self.logger.info(
                    f"Scene {scene.scene_number}: Cropped {img_full.width}x{img_full.height} "
                    f"-> {img_cropped.width}x{img_cropped.height}"
                )
            else:
                with open(tmp_path, "wb") as f:
                    f.write(img_resp.content)

            cost = 0.04
            endpoint_name = "fal-ai/instant-character"

            scene.image_backend = "instant-character"
            scene.instant_character_used = True
            scene.lora_used = True

        # ---- Generate via flux-lora ----
        else:
            endpoint_name = "fal-ai/flux-lora"
            self.logger.info(f"Scene {scene.scene_number}: Submitting to {endpoint_name}")

            fal_payload = {
                "prompt": full_prompt,
                "image_size": {"width": 1280, "height": 720},
                "num_images": 1,
                "num_inference_steps": 28,
                "guidance_scale": 3.5,
                "loras": [{"path": self.FAL_LORA_URL, "scale": 1.0}],
                "output_format": "png",
            }

            async with httpx.AsyncClient(timeout=300) as client:
                submit_resp = await client.post(
                    f"https://queue.fal.run/{endpoint_name}",
                    headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
                    json=fal_payload,
                )
                submit_resp.raise_for_status()
                submit_data = submit_resp.json()
                request_id = submit_data.get("request_id")
                status_url = submit_data.get(
                    "status_url",
                    f"https://queue.fal.run/{endpoint_name}/requests/{request_id}/status",
                )
                response_url = submit_data.get(
                    "response_url",
                    f"https://queue.fal.run/{endpoint_name}/requests/{request_id}",
                )

                self.logger.info(f"Scene {scene.scene_number}: fal.ai request {request_id} submitted")

                # Poll for completion (max 5 minutes)
                for i in range(60):
                    await asyncio.sleep(5)
                    status_resp = await client.get(
                        status_url, headers={"Authorization": f"Key {fal_key}"}
                    )
                    status_data = status_resp.json()
                    gen_status = status_data.get("status", "")

                    if gen_status == "COMPLETED":
                        break
                    elif gen_status in ("FAILED", "CANCELLED"):
                        error_msg = status_data.get("error", "fal.ai generation failed")
                        raise RuntimeError(f"fal.ai image: {error_msg}")

                    if (i + 1) % 6 == 0:
                        self.logger.info(
                            f"Scene {scene.scene_number}: Waiting for fal.ai... {(i+1)*5}s"
                        )
                else:
                    raise RuntimeError("fal.ai image generation timed out after 5 minutes")

                # Get result
                result_resp = await client.get(
                    response_url, headers={"Authorization": f"Key {fal_key}"}
                )
                result_resp.raise_for_status()
                result_data = result_resp.json()

                images = result_data.get("images", [])
                if not images:
                    raise RuntimeError("fal.ai returned no images")

                # Download image
                img_resp = await client.get(images[0]["url"])
                img_resp.raise_for_status()

            tmp_path = os.path.join(
                tempfile.gettempdir(),
                f"f1_scene_{self.episode_id}_{scene.scene_number:02d}_{frame_type}.png",
            )
            os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
            with open(tmp_path, "wb") as f:
                f.write(img_resp.content)

            cost = 0.035
            scene.image_backend = "flux-lora"
            scene.lora_used = True

        generation_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        # Upload to MinIO
        image_storage_path = await self.storage.upload_scene_image(
            race_id=self.race.id if self.race else 0,
            episode_id=self.episode_id,
            scene_number=scene.scene_number,
            file_path=tmp_path,
            suffix=frame_type,
        )

        if frame_type == "end":
            scene.end_frame_path = image_storage_path
        else:
            scene.source_image_path = image_storage_path
            scene.start_frame_path = image_storage_path

        from decimal import Decimal as _Dec
        scene.image_cost_usd = (scene.image_cost_usd or _Dec(0)) + _Dec(str(cost))

        await self._log_api_usage(
            db,
            provider=APIProvider.FAL_IMAGE,
            endpoint=endpoint_name,
            cost_usd=cost,
            response_time_ms=generation_time_ms,
        )

        self.logger.info(
            f"Scene {scene.scene_number}: fal.ai image generated in {generation_time_ms}ms "
            f"({image_backend}, ${cost:.3f})"
        )

        return tmp_path


    # ------------------------------------------------------------------
    # Phases 3-5 (unchanged)
    # ------------------------------------------------------------------

    def _adapt_prompt_for_failure(self, scene, validation_result) -> bool:
        """Delegate to shared function in scene_validator."""
        from app.services.scene_validator import adapt_prompt_for_validation_failure
        return adapt_prompt_for_validation_failure(scene, validation_result)

    async def _update_total_costs(self, db: AsyncSession) -> None:
        """Sum all scene image + video costs and update episode total."""
        from decimal import Decimal
        stmt = (
            select(Scene)
            .where(Scene.episode_id == self.episode_id)
        )
        result = await db.execute(stmt)
        scenes = result.scalars().all()

        total_image = sum((s.image_cost_usd or Decimal(0)) for s in scenes)
        total_video = sum((s.video_cost_usd or Decimal(0)) for s in scenes)
        total = total_image + total_video + (self.episode.anthropic_cost_usd or Decimal(0))

        self.episode.total_cost_usd = total
        await db.commit()
        self.logger.info(
            f"Episode costs: images=${float(total_image):.3f}, "
            f"videos=${float(total_video):.3f}, "
            f"script=${float(self.episode.anthropic_cost_usd or 0):.3f}, "
            f"total=${float(total):.3f}"
        )

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

        # Build title/subtitle for intro overlay
        episode_num = self.episode_id
        race_name = self.race.race_name if self.race else "F1 Race"
        title = self.episode.title or race_name
        subtitle = f"Season {self.race.season if self.race else 2026} | Episode {episode_num} | {race_name}"

        # Build next episode teaser for outro
        next_episode_text = ""
        if hasattr(self, '_next_race_info') and self._next_race_info:
            next_episode_text = f"Next: {self._next_race_info}"

        result = await self.stitcher.stitch(
            self.episode_id,
            clip_paths,
            title=title,
            subtitle=subtitle,
            next_episode_text=next_episode_text,
        )

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

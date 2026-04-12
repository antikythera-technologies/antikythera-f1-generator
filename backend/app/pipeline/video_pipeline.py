"""Main video generation pipeline."""

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
from app.models.character import Character
from app.models.episode import Episode, EpisodeStatus
from app.models.gag import GagStatus, GagUsage, RunningGag
from app.models.logs import APIProvider, GenerationLog, LogComponent, LogLevel
from app.models.race import Race
from app.models.scene import Scene, SceneStatus
from app.models.team import Team
# Personality traits loaded from DB via load_personality_traits_from_db()
from app.services.cost_tracker import log_api_cost, update_episode_costs
from app.services.scene_orchestrator import process_scene
from app.services.script_generator import ScriptGenerator, sanitize_dialogue
from app.services.image_generator import ImageGenerator
from app.services.ovi_video_generator import OviVideoGenerator
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

                # GUARD: Refuse to run without a race — scripts need circuit context
                if not self.episode.race_id:
                    raise RuntimeError(
                        f"Episode {self.episode_id} has no race_id. "
                        f"Cannot generate without race/circuit context. "
                        f"The scheduler should never create episodes without a race."
                    )

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
                await self._stitch_video(db)

                # Phase 4: YouTube Upload — DISABLED (manual only via dashboard)
                self.logger.info("PHASE 4: Skipped — YouTube upload is manual only")

                # Phase 5: Cleanup old assets
                self.logger.info("PHASE 5: Cleanup")
                await self._cleanup_old_assets(db)

                # Mark as completed (ready for manual YouTube upload)
                await self._update_status(db, EpisodeStatus.COMPLETED)

                await db.commit()

                self.logger.info("=" * 60)
                self.logger.info(f"PIPELINE COMPLETE: Episode {self.episode_id}")
                self.logger.info("=" * 60)

                return f"Episode {self.episode_id} completed"

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

        # Update episode with deterministic title (DB facts + LLM subtitle)
        self.episode.title = self._build_episode_title(script.subtitle)
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
                duration_seconds=scene_script.target_duration or 5,
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

    def _build_episode_title(self, subtitle: str) -> str:
        """Build episode title from DATABASE facts + LLM subtitle.

        Format: "{Country} {Session}: {Subtitle}"
        Country and session come from the database. NEVER from the LLM.
        The LLM only provides the creative subtitle.
        """
        # Country from database — NEVER from LLM
        if self.race and self.race.country:
            location = self.race.country
        elif self.race and self.race.circuit_name:
            location = self.race.circuit_name
        elif self.race and self.race.race_name:
            location = self.race.race_name
        else:
            location = "F1"

        # Session from episode_type enum — NEVER from LLM
        session = self.episode.episode_type.session_label

        # Defensive: strip location/session from subtitle if LLM included them
        clean = subtitle.strip() if subtitle else ""
        if self.race:
            for noise in [self.race.country, self.race.circuit_name,
                          self.race.race_name, session]:
                if noise and clean.lower().startswith(noise.lower()):
                    clean = clean[len(noise):].lstrip(": -")

        if clean:
            return f"{location} {session}: {clean}"
        return f"{location} {session}"

    def _adapt_end_frame_for_consistency(
        self, start_prompt: str, end_prompt: str
    ) -> str:
        """Adapt end frame prompt to be visually consistent with start frame.

        Keeps the start frame's setting (circuit, lighting, environment) and
        applies only the motion/action difference from the end frame.
        This ensures the two frames are similar enough for FLF interpolation.
        """
        return (
            f"Same scene, same camera angle, same environment as: "
            f"{(start_prompt or '')[:200]}. "
            f"But now showing: {end_prompt or ''}"
        )

    def _extract_episode_storyline(self) -> str:
        """Build a one-sentence storyline description for the intro image.

        Uses database facts (circuit, session, country) + the episode subtitle
        to create a prompt fragment that makes the intro image episode-specific.
        """
        parts = []

        # Session type from DB
        session = self.episode.episode_type.session_label if self.episode else "Race"

        # Circuit/location from DB
        circuit = ""
        country = ""
        if self.race:
            circuit = self.race.circuit_name or ""
            country = self.race.country or ""

        # Episode subtitle — the LLM-generated storyline hook
        title = self.episode.title if self.episode else ""
        # Extract subtitle part after the colon (e.g. "Japan Qualifying: X" -> "X")
        subtitle = title.split(": ", 1)[1] if ": " in title else title

        if subtitle:
            parts.append(subtitle)

        # Add session + location context
        if circuit and country:
            parts.append(f"at {circuit} in {country}")
        elif country:
            parts.append(f"in {country}")

        parts.append(f"during {session.lower()}")

        return ", ".join(parts) if parts else ""

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
        """Generate images + video clips for all scenes via shared service layer.

        Delegates each scene to scene_orchestrator.process_scene() which handles:
        - Image generation (flux-lora / instant-character routing)
        - Image validation with self-correcting retries
        - End frame generation for FLF-capable backends
        - Video generation via configured fal.ai backend
        - Video validation (motion check + Claude Vision)
        - Audio validation (non-blocking)

        No business logic lives here — it's all in the shared services.
        """
        # Commit scenes from Phase 1 so process_scene can find them
        await db.commit()

        # Collect episode-level character appearances for clothing consistency
        episode_appearances = None
        if self.episode and hasattr(self.episode, "character_appearances"):
            episode_appearances = self.episode.character_appearances

        total = len(scenes)
        completed = 0
        failed = 0

        for idx, scene in enumerate(scenes):
            result = await process_scene(
                db=db,
                scene=scene,
                episode_id=self.episode_id,
                race_id=self.race.id if self.race else 0,
                storage=self.storage,
                scene_index=idx,
                total_scenes=total,
                episode_character_appearances=episode_appearances,
            )

            if result.status == "completed":
                completed += 1
            else:
                failed += 1
                self.logger.error(
                    f"Scene {scene.scene_number} FAILED: {result.error}"
                )

        self.logger.info(
            f"Phase 2 complete: {completed} completed, {failed} failed out of {total}"
        )

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
        from app.services.fal_video_generator import FAL_AUDIO_BACKENDS
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


    async def _update_total_costs(self, db: AsyncSession) -> None:
        """Sum all scene costs and update episode total. Delegates to shared cost_tracker."""
        await update_episode_costs(db, self.episode_id)

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
            circuit_name=self.race.circuit_name if self.race else "",
            episode_storyline=self._extract_episode_storyline(),
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
        """Log API usage. Delegates to shared cost_tracker."""
        await log_api_cost(
            db,
            episode_id=self.episode_id,
            provider=provider,
            endpoint=endpoint,
            cost_usd=cost_usd,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            response_time_ms=response_time_ms,
        )

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

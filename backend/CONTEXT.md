# Backend Context (Layer 2)

> Read this when working on API endpoints, data models, schemas, database migrations, testing, or the job queue.
> Do NOT read this when working on pipeline internals or the dashboard.

## What This Workspace Does

FastAPI backend for the F1 video generation system. REST API, PostgreSQL database, Redis job queue, background worker.

## API Routes (all at /api/v1/)

- **Episodes** (`api/episodes.py`): CRUD + generate trigger (with duplicate prevention: 409 if exists) + retry
- **Scenes** (`api/scenes.py`): List/get scenes, update prompts, regenerate frames/video/all
- **Characters** (`api/characters.py`): CRUD + image upload + face reference + personality + caricature generation
- **Races** (`api/races.py`): CRUD + calendar sync
- **Scheduler** (`api/scheduler.py`): Sync calendar, list/create/cancel/trigger jobs, queue status
- **Pipeline Settings** (`api/pipeline_settings.py`): GET/PUT runtime pipeline config (video generator, image generator, TTS, quality)
- **News** (`api/news.py`): Sources CRUD, article scraping, context for episodes
- **Gags** (`api/gags.py`): Running gags CRUD + usage tracking + cooldowns
- **Storylines** (`api/storylines.py`): Multi-episode narrative arcs + beat progression
- **Teams** (`api/teams.py`): F1 team management
- **Analytics** (`api/analytics.py`): Cost breakdown, generation performance metrics

## Data Models (app/models/)

Core entities and their status fields:

- **Episode**: PENDING -> GENERATING -> STITCHING -> UPLOADING -> PUBLISHED | FAILED
- **Scene**: PENDING -> GENERATING -> COMPLETED | FAILED (~26 per episode)
  - Has: start_frame_prompt, end_frame_prompt, video_prompt, camera_direction
  - Has: source_image_path, start_frame_path, end_frame_path, video_clip_path, audio_clip_path
  - Has: video_generator, image_backend ("flux-lora" or "instant-character"), face_visible, instant_character_used, end_frame_delta
  - Has: scene_type (TALKING_HEAD, ACTION_REPLAY, ESTABLISHING, TWO_SHOT, OVER_THE_SHOULDER, PODIUM)
  - Has: validation_status, validation_issues (JSON)
- **Character**: name, team, role, active flag -> CharacterImage (reference/style images)
- **Race**: season, round_number, name, circuit, dates, is_sprint_weekend
- **RaceResult**: race_id -> position, driver, team, laps, time (for accurate scripts)
- **ScheduledJob**: SCHEDULED -> RUNNING -> COMPLETED | FAILED
- **RunningGag**: times_used, cooldown_races, status transitions
- **Storyline**: type (rivalry/character_arc/season_plot), beats, character links
- **NewsSource/NewsArticle**: RSS/HTML scraping with relevance scoring
- **GenerationLog/APIUsage**: Cost tracking per provider

## Job Queue (app/jobs.py)

Redis + RQ on queue "f1-pipeline". Thin RQ wrappers that delegate to shared services. Job types:
- `enqueue_pipeline(episode_id)` -- full episode pipeline (2h timeout)
- `enqueue_scene_image(episode_id, scene_number)` -- calls `scene_image_service.generate_scene_image()`
- `enqueue_scene_all(episode_id, scene_number)` -- calls `scene_orchestrator.process_scene()`
- `enqueue_scene_video(episode_id, scene_number)` -- calls `scene_video_service.generate_scene_video()`
- `enqueue_stitch(episode_id)` -- stitch all clips into final video
- `enqueue_youtube_upload(episode_id)` -- upload to YouTube
- `enqueue_validate(episode_id)` -- validate all scenes (Claude Vision)

**No business logic in jobs.py.** All image routing, video generation, validation, and cost tracking live in the shared service layer. Pipeline and jobs call the same functions.

## Worker (app/worker.py)

RQ worker + scheduler poll loop (configurable interval). Polls for ScheduledJob records whose time has passed, creates Episode, enqueues pipeline. **Has duplicate episode prevention** -- checks existing episode before creating.

## Services Layer (app/services/)

**Shared scene services** (called by both pipeline and jobs — single source of truth):
- `scene_image_service.py` -- Image gen with routing (flux-lora vs instant-character), prompt building, fal.ai API
- `scene_video_service.py` -- Video gen via fal.ai, prompt building via `build_f1_video_prompt()`, FLF end frames
- `scene_orchestrator.py` -- Full scene lifecycle: image → validate → end frame → video → validate. Self-correcting retries.
- `cost_tracker.py` -- Shared cost logging + episode cost aggregation
- `image_utils.py` -- Portrait-to-landscape blur-pad conversion

**External integrations** (one class per service):
- `script_generator.py` -- Anthropic Haiku for scene scripts + dialogue sanitisation + session context injection
- `fal_video_generator.py` -- fal.ai video gen (8 backends) + `build_f1_video_prompt()` + `calculate_scene_duration()`
- `scene_validator.py` -- Image validation (8 checks) + video validation + FLF frame compatibility + `adapt_prompt_for_validation_failure()`
- `tts_generator.py` -- Edge TTS speech generation + 42 character voice mappings
- `audio_mixer.py` -- Mux TTS audio onto video clips via ffmpeg
- `stitcher.py` -- ffmpeg video concatenation
- `storage.py` -- MinIO object storage (4 buckets) + face ref priority (caricature first, real photo fallback)
- `youtube_uploader.py` -- YouTube Data API v3 upload
- `personality.py` -- Character personality trait loader
- `image_generator.py` -- ComfyUI image gen (legacy, for character caricatures only)
- `runtime_settings.py` -- Runtime pipeline settings (image_generator, video_generator)
- `scheduler.py` -- F1 calendar sync + job scheduling
- `news_scraper.py` -- RSS/HTML news scraping
- `race_results_scraper.py` -- Scrape actual race results for script accuracy
- `api_logger.py` -- Structured API request/response logging

## Config

Pydantic Settings in `app/config.py`. All settings from env vars. Access: `settings.FIELD_NAME`

## Commands

```bash
cd backend
uv run uvicorn app.main:app --reload          # Dev server on :8000
uv run alembic upgrade head                    # Run migrations
uv run alembic revision --autogenerate -m "x"  # New migration
uv run pytest --cov=app                        # Tests
uv run ruff check app/                         # Lint
uv run black app/ tests/                       # Format
```


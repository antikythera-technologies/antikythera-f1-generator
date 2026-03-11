# Backend Context (Layer 2)

> Read this when working on API endpoints, data models, schemas, database migrations, testing, or the job queue.
> Do NOT read this when working on pipeline internals or the dashboard.

## What This Workspace Does

FastAPI backend for the F1 video generation system. REST API, PostgreSQL database, Redis job queue, background worker.

## API Routes (all at /api/v1/)

- **Episodes** (`api/episodes.py`): CRUD + generate trigger + retry
- **Scenes** (`api/scenes.py`): List/get scenes, update prompts, regenerate frames/video (NEW -- just built)
- **Characters** (`api/characters.py`): CRUD + image upload + face reference + personality + caricature generation
- **Races** (`api/races.py`): CRUD + calendar sync (sync not yet implemented)
- **Scheduler** (`api/scheduler.py`): Sync calendar, list/create/cancel/trigger jobs, queue status
- **News** (`api/news.py`): Sources CRUD, article scraping, context for episodes
- **Gags** (`api/gags.py`): Running gags CRUD + usage tracking + cooldowns
- **Storylines** (`api/storylines.py`): Multi-episode narrative arcs + beat progression
- **Analytics** (`api/analytics.py`): Cost breakdown, generation performance metrics

## Data Models (app/models/)

Core entities and their status fields:

- **Episode**: PENDING -> GENERATING -> STITCHING -> UPLOADING -> PUBLISHED | FAILED
- **Scene**: PENDING -> GENERATING -> COMPLETED | FAILED (24 per episode)
  - Has: start_frame_prompt, end_frame_prompt, camera_direction, video_prompt (for LTX dual-frame)
  - Has: source_image_path, start_frame_path, end_frame_path, video_clip_path
  - Has: video_generator field ("ltx" or "ovi")
- **Character**: name, team, role, active flag -> CharacterImage (reference/style images)
- **Race**: season, round_number, name, circuit, dates (fp1/fp2/fp3/sprint/qualifying/race)
- **ScheduledJob**: SCHEDULED -> RUNNING -> COMPLETED | FAILED
- **RunningGag**: times_used, cooldown_races, status transitions
- **Storyline**: type (rivalry/character_arc/season_plot), beats, character links
- **NewsSource/NewsArticle**: RSS/HTML scraping with relevance scoring
- **GenerationLog/APIUsage**: Cost tracking per provider

## Job Queue

- Redis + RQ on queue "f1-pipeline"
- `jobs.py`: enqueue_pipeline(episode_id) -> worker picks up
- `worker.py`: RQ worker + scheduler poll loop (every 15 min)
- Job timeout: 2 hours

## Database

- PostgreSQL (async via asyncpg + SQLAlchemy 2.0)
- Migrations: Alembic in `migrations/versions/`
- Test DB: in-memory SQLite (aiosqlite) via conftest.py fixtures

## Testing

- Framework: pytest + pytest-asyncio
- Fixtures: `db_session` (function-scoped, auto-rollback), `client`, `async_client`
- Pattern: FastAPI dependency override for test DB injection
- Run: `uv run pytest --cov=app` or `uv run pytest tests/test_api.py -k "test_name"`

## Services Layer (app/services/)

One class per external integration:

- `script_generator.py` -- Anthropic Haiku for 24-scene scripts
- `image_generator.py` -- ComfyUI (Flux + LoRA + PuLID) for scene images
- `ltx_video_generator.py` -- LTX 2.3 via ComfyUI for video clips (current)
- `ovi_video_generator.py` -- Ovi via Gradio for video clips (legacy)
- `comfyui_client.py` -- shared HTTP client for ComfyUI API
- `ovi_space_manager.py` -- RunPod pod lifecycle (start/stop/health)
- `storage.py` -- MinIO object storage (4 buckets)
- `stitcher.py` -- ffmpeg video concatenation
- `youtube_uploader.py` -- YouTube Data API v3 upload
- `personality.py` -- loads character personality JSONs
- `scheduler.py` -- F1 calendar sync + job scheduling
- `news_scraper.py` -- RSS/HTML news scraping

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

## Current Development State

We are stepping through the pipeline scene by scene, testing each piece. The Scenes API was just built to allow viewing and editing scene prompts/images. Not everything has been tested end-to-end yet -- image generation works, video generation is being tested, stitching/YouTube upload haven't been tested yet.

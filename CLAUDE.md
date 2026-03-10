# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Automated video generation system for satirical F1 commentary videos. FastAPI backend with PostgreSQL, Next.js 15 dashboard (React 19), Anthropic Haiku for scripts, Google Gemini for scene images, Ovi (Gradio) for image-to-video, YouTube Data API for uploads.

## Commands
```bash
# Install
./scripts/install.sh

# Start services
./scripts/startup.sh              # All services (docker-compose)
./scripts/startup.sh backend      # Backend only (uvicorn --reload on :8000)
./scripts/startup.sh dashboard    # Dashboard only (next dev on :3000)

# Database
./scripts/prime.sh                # Migrations + seed data
./scripts/prime.sh --reset        # Drop and recreate everything

# Backend dev
cd backend && uv run uvicorn app.main:app --reload
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
uv run pytest --cov=app
uv run pytest tests/test_api.py -k "test_name"     # Single test
uv run ruff check app/                              # Lint
uv run black app/ tests/                            # Format
uv run isort app/ tests/                            # Sort imports
uv run mypy app/                                    # Type check

# Dashboard dev
cd dashboard && npm run dev       # Dev server on :3000
npm run build                     # Production build
npm run lint                      # ESLint

# Deploy (rsync to antikythera-n8n VPS, docker-compose.production.yml)
./scripts/deploy.sh
```

## Architecture

### Video Pipeline (5 sequential phases)
The core system is `backend/app/pipeline/video_pipeline.py`. Each episode generates 24 × 5-second scenes = 2 minutes of video.

1. **Script Generation** — Anthropic Haiku writes 24 scene scripts (dialogue, action, audio descriptions) given race context and character personalities
2. **Video Clip Generation** — For each scene: Gemini generates a scene image from character reference/style images + traits → Ovi converts image to 5s video clip. OviSpaceManager auto-starts/pauses the HuggingFace space to save GPU costs
3. **Stitching** — ffmpeg concatenates 24 clips into final video (libx264, CRF 23, aac audio)
4. **YouTube Upload** — OAuth2 resumable upload with metadata (title, description, tags)
5. **Cleanup** — Deletes MinIO assets older than 3 races

### Backend Structure
- **Services layer** (`app/services/`): One class per external integration — `ScriptGenerator`, `ImageGenerator`, `VideoGenerator`, `OviSpaceManager`, `VideoStitcher`, `YouTubeUploader`, `StorageService`, `NewsScraper`, `SchedulerService`
- **Async DB sessions** via `get_db()` dependency with auto-commit/rollback
- **Custom exceptions** in `app/exceptions.py` with `RetryableError` base for rate limits; scene-level retry (max 3 attempts)
- **Config**: Pydantic Settings in `app/config.py`, accessed as `settings.FIELD_NAME`
- **API versioned** at `/api/v1` with routers: episodes, characters, races, scheduler, analytics, news, gags
- **Background worker** (`app/worker.py`) uses Redis + RQ for job processing

### Dashboard Structure
- **Next.js 15 App Router**, all pages are `"use client"` with React hooks (no global state manager)
- **Tailwind CSS v4** with cyberpunk theme (custom properties in `globals.css`: `--deep-space`, `--neon-cyan`, `--racing-red`, etc.)
- **Centralized API client** in `src/lib/api.ts` — 7 modules (episodes, characters, races, analytics, scheduler, news, gags) with TypeScript interfaces
- **Env vars**: `NEXT_PUBLIC_API_URL` (default `http://localhost:8001/api/v1`), `NEXT_PUBLIC_MINIO_URL`

### Key Data Model Relationships
```
Race → Episode → Scene (24 per episode)
                 ↳ GenerationLog, APIUsage (cost tracking)
Character → CharacterImage (reference/style images)
RunningGag → GagUsage → Episode
NewsSource → NewsArticle
ScheduledJob → Race, Episode
```

### Episode Types & Scheduling
- Standard weekend: POST_FP2 (Friday), POST_RACE (Sunday)
- Sprint weekend: adds POST_SPRINT (Saturday)
- Off-week: WEEKLY_RECAP (Friday 07:00 SAST)

### Docker Setup
- Development: `docker-compose.yml` — backend(:8001), dashboard(:3001), redis, worker
- Production: `docker-compose.production.yml` — same minus worker, uses `.env` file
- External network: `n8n-docker-caddy_antikythera_internal_network` for Caddy routing
- MinIO custom DNS: `minio.antikythera.co.za:172.18.0.5` via extra_hosts

### Testing
- Tests in `backend/tests/` using pytest-asyncio with in-memory SQLite (`aiosqlite`)
- `conftest.py` provides `db_session` (function-scoped with rollback) and `client`/`async_client` fixtures
- FastAPI dependency override pattern for test DB injection

## Brain Vault References
- Architecture: `brain_search("f1 generator architecture")`

## Credentials
All secrets in `.env.example`. Production values in encrypted vault. Use `credential_get("service name")`.

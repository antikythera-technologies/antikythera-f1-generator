# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Automated satirical F1 commentary video system. Scheduler fires after each race session, generates a funny 2-minute video with caricature characters, and publishes to YouTube. FastAPI + PostgreSQL backend, Next.js 15 dashboard, fal.ai for images/video, ElevenLabs/Edge TTS for audio.

## MANDATORY: Read OPERATIONS.md First

**Before doing ANY work, read `OPERATIONS.md` in this repo root.** It contains the operational flow, rules, costs, and key decisions. Not reading it leads to broken pipelines and wasted money.

## Task Routing

Read the CONTEXT.md in the workspace BEFORE starting work. Skip everything else.

| Task | Read This Context | Skip |
|------|------------------|------|
| Pipeline / scene quality | `backend/app/pipeline/CONTEXT.md` | `dashboard/*`, `docs/*` |
| Full episode pipeline | `backend/app/pipeline/CONTEXT.md`, `backend/CONTEXT.md` | `dashboard/*`, `scripts/experiments/*` |
| Script / characters / gags | `backend/CONTEXT.md` | `dashboard/*`, pipeline internals |
| Dashboard UI | `dashboard/CONTEXT.md` | `backend/app/pipeline/*`, `backend/app/services/*` |
| Backend API / models | `backend/CONTEXT.md` | `dashboard/*`, `scripts/experiments/*` |
| Experiments (image/video R&D) | `scripts/experiments/CONTEXT.md` | `dashboard/*`, `backend/app/api/*` |
| Deploy | `scripts/CONTEXT.md` | `backend/app/*`, `dashboard/src/*` |

## Quick Commands

```bash
# Start services
./scripts/startup.sh              # All (docker-compose)
./scripts/startup.sh backend      # Backend on :8000
./scripts/startup.sh dashboard    # Dashboard on :3000

# Database
./scripts/prime.sh                # Migrations + seed (2026 calendar, drivers, teams)
./scripts/prime.sh --reset        # Drop + recreate

# Backend (from backend/)
uv run uvicorn app.main:app --reload          # Dev server
uv run python -m app.worker                   # Background worker + scheduler
uv run pytest --cov=app                       # Tests
uv run pytest tests/test_api.py::TestCharacters -k "test_create"  # Single test
uv run ruff check app/ && uv run black app/ tests/                # Lint + format
uv run alembic upgrade head                   # Run migrations
uv run alembic revision --autogenerate -m "description"           # New migration

# Dashboard (from dashboard/)
npm run dev                       # Dev server on :3000
npm run build && npm run lint     # Build + lint

# Deploy
./scripts/deploy.sh
```

## Architecture

### Pipeline (the core — 5 phases)

The pipeline runs fully automated via the scheduler. All fixes go into pipeline code, never individual scenes — the scheduler will overwrite manual edits.

```
Scheduler polls (every 15 min) → race session ended?
  → Duplicate check (race_id + episode_type) → skip if exists
  → Create Episode → enqueue to RQ (Redis)
  → Phase 1: Script gen (Anthropic Haiku) — 26 scenes with dialogue, scene_type, face_visible
  → Phase 2a: Image gen (fal.ai) — routes by face_visible flag
  → Phase 2a-bis: End frames (for FLF-capable backends only)
  → Phase 2b: Video gen (fal.ai, configurable backend)
  → Phase 2c: TTS audio (Edge TTS, only if backend has no native audio)
  → Phase 3: Stitch (ffmpeg concat → final video)
  → Phase 4: YouTube upload (currently disabled for manual review)
```

**Image routing** (face_visible flag from script):
- `false` → flux-lora (LoRA style only, no character face)
- `true` + face ref exists → instant-character (face ref + LoRA, scale=0.3)
- `true` + no face ref → flux-lora fallback with detailed prompt

**CRITICAL: Feature parity rule** — `video_pipeline.py` and `jobs.py` must implement identical image routing, video prompt wrapping, and TTS logic. Scene regeneration via API must behave identically to bulk pipeline runs.

### Backend

- **API** (`app/api/`) — 11 route modules under `/api/v1/`. Episode creation returns 409 on duplicates (override with `force=true`).
- **Models** (`app/models/`) — Episode, Scene, Character, CharacterImage, Race, RaceResult, ScheduledJob, RunningGag, Storyline, NewsSource, NewsArticle, GenerationLog, CharacterAppearance.
- **Services** (`app/services/`) — One class per external integration. Key: `script_generator` (Anthropic), `fal_video_generator` (8 backends), `tts_generator` (42 voice mappings), `storage` (MinIO, 4 buckets), `stitcher` (ffmpeg).
- **Jobs** (`app/jobs.py`) — RQ job wrappers for pipeline, scene regen, stitch, upload, validation. Default timeout 2h for full pipeline.
- **Worker** (`app/worker.py`) — RQ worker + scheduler poll loop (60s interval). Handles duplicate prevention before creating episodes.

### Dashboard

Next.js 15 + React 19 + Tailwind v4. Cyberpunk theme. All pages are `"use client"` with React hooks. API client in `src/lib/api.ts` (10 typed modules: episodes, scenes, characters, races, scheduler, news, gags, storylines, analytics, settings). SSE polling for long-running job progress.

### Infrastructure

- **PostgreSQL** — All data in database, never JSON files on disk
- **Redis** — RQ job queue (`f1-pipeline` queue)
- **MinIO** — Object storage (4 buckets: characters, scene_images, video_clips, final_videos)
- **Docker** — backend (:8001 prod), worker, redis, dashboard (:3001). Networks: `f1-network` (internal) + `antikythera-network` (Caddy proxy)

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Scene images | `scene_{num:02d}_{suffix}.png` | `scene_01_start.png` |
| Video clips | `scene_{num:02d}.{webm\|mp4}` | `scene_01.webm` |
| Experiments | `test_{what}.py` | `test_ltx_scene1.py` |
| Migrations | `{seq}_{description}.py` | `002_add_scene_dual_frame_columns.py` |
| Face references | `{character_name}.{ext}` | `max_verstappen.jpg` |

## Development State

Pipeline runs end-to-end automated. fal-ltx is the active video backend via fal.ai API. Self-hosted LTX via ComfyUI/RunPod is blocked. Image routing (flux-lora / instant-character) is production-ready. TTS audio mux works. Stitching works. YouTube upload code exists but is disabled for manual review.

## Credentials

All secrets in `.env`. Production values in encrypted vault: `credential_get("service name")`.

## Brain Vault

- Architecture: `brain_search("f1 generator architecture")`
- Image gen: `brain_search("f1 image generation")`

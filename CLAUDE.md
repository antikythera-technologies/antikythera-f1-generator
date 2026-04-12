# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Automated satirical F1 commentary video system. Scheduler fires after each race session, generates a funny 2-minute video with caricature characters, and publishes to YouTube. FastAPI + PostgreSQL backend, Next.js 15 dashboard, fal.ai for images/video, Edge TTS for audio.

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

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Scene images | `scene_{num:02d}_{suffix}.png` | `scene_01_start.png` |
| Video clips | `scene_{num:02d}.{webm\|mp4}` | `scene_01.webm` |
| Experiments | `test_{what}.py` | `test_ltx_scene1.py` |
| Migrations | `{seq}_{description}.py` | `002_add_scene_dual_frame_columns.py` |
| Face references | `{character_name}.{ext}` | `max_verstappen.jpg` |

## Credentials

All secrets in `.env`. Production values in encrypted vault: `credential_get("service name")`.

## Brain Vault

- Architecture: `brain_search("f1 generator architecture")`
- Image gen: `brain_search("f1 image generation")`

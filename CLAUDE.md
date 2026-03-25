# CLAUDE.md — F1 Video Generator

Automated satirical F1 commentary video system. FastAPI + PostgreSQL backend, Next.js 15 dashboard, fal.ai for images + video, YouTube for publishing.

## MANDATORY: Read OPERATIONS.md First

**Before doing ANY work, read `OPERATIONS.md` in this repo root.** It contains the operational flow, rules, costs, and key decisions. Not reading it leads to broken pipelines and wasted money.

## Folder Map

```
backend/                 → FastAPI backend (API, models, services, pipeline)
  app/api/               → REST endpoints at /api/v1/
  app/models/            → SQLAlchemy data models
  app/schemas/           → Pydantic request/response schemas
  app/services/          → One class per external integration
  app/pipeline/          → Video generation orchestrator (5 phases)
  migrations/            → Alembic DB migrations
  tests/                 → pytest + pytest-asyncio tests
dashboard/               → Next.js 15 dashboard (React 19, Tailwind v4)
  src/app/               → App Router pages
  src/components/        → UI components
  src/lib/api.ts         → Centralized API client (10 modules)
scripts/                 → Utility scripts (deploy, setup, batch ops)
  experiments/           → R&D test scripts (active)
  experiments/archive/   → Superseded experiments
docs/                    → Plans, research, archived design docs
```

## Task Routing

Read the CONTEXT.md in the workspace BEFORE starting work. Skip everything else.

| Task | Read This Context | Skip |
|------|------------------|------|
| Generate/test a scene | `backend/app/pipeline/CONTEXT.md` | `dashboard/*`, `docs/*` |
| Iterate on scene quality | `backend/app/pipeline/CONTEXT.md` | `dashboard/*`, `backend/app/api/*` |
| Run full episode pipeline | `backend/app/pipeline/CONTEXT.md`, `backend/CONTEXT.md` | `dashboard/*`, `scripts/experiments/*` |
| Script generation (prompts, gags, storylines) | `backend/CONTEXT.md` | `dashboard/*`, pipeline internals |
| Character work (personalities, faces, caricatures) | `backend/CONTEXT.md` | `dashboard/*`, pipeline video gen |
| Dashboard UI | `dashboard/CONTEXT.md` | `backend/app/pipeline/*`, `backend/app/services/*` |
| Backend API (endpoints, models, schemas) | `backend/CONTEXT.md` | `dashboard/*`, `scripts/experiments/*` |
| Run experiments (image/video R&D) | `scripts/experiments/CONTEXT.md` | `dashboard/*`, `backend/app/api/*` |
| Deploy | `scripts/CONTEXT.md` | `backend/app/*`, `dashboard/src/*` |
| Scheduling & automation | `backend/CONTEXT.md` | `dashboard/*` (beyond scheduler page) |

## Quick Commands

```bash
# Start
./scripts/startup.sh              # All (docker-compose)
./scripts/startup.sh backend      # Backend on :8000
./scripts/startup.sh dashboard    # Dashboard on :3000

# Database
./scripts/prime.sh                # Migrations + seed
./scripts/prime.sh --reset        # Drop + recreate

# Backend
cd backend && uv run uvicorn app.main:app --reload
uv run pytest --cov=app
uv run ruff check app/ && uv run black app/ tests/

# Dashboard
cd dashboard && npm run dev
npm run build && npm run lint

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

## Development State

Testing the pipeline scene by scene. Image generation works. Ovi is the **active video engine** (scene_01 tested successfully). LTX 2.3 is BLOCKED (ComfyUI integration failed after 20h; under audit — see `docs/runpod-setup/ltx-audit.md`). TTS audio mux working. Stitching/YouTube upload not yet tested.

## Credentials

All secrets in `.env`. Production values in encrypted vault: `credential_get("service name")`.

## Brain Vault

- Architecture: `brain_search("f1 generator architecture")`
- Image gen: `brain_search("f1 image generation")`


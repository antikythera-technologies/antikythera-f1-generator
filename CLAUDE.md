# CLAUDE.md - Antikythera F1 Video Generator

## Project Overview
Automated video generation system for satirical F1 commentary videos. FastAPI backend with PostgreSQL, Next.js 16 dashboard, Anthropic Haiku for scripts, Ovi (Gradio) for image-to-video, YouTube Data API for uploads.

## Commands
```bash
# Install
./scripts/install.sh

# Start services
./scripts/startup.sh              # All services (docker-compose)
./scripts/startup.sh backend      # Backend only
./scripts/startup.sh dashboard    # Dashboard only

# Database
./scripts/prime.sh                # Migrations + seed data
./scripts/prime.sh --reset        # Drop and recreate everything

# Backend dev
cd backend && uv run uvicorn app.main:app --reload
uv run alembic upgrade head
uv run pytest --cov=app

# Deploy
./scripts/deploy.sh
```

## Key Patterns
- Structured logging: `logging.getLogger(__name__)` per module
- Async DB sessions with FastAPI dependency injection
- Custom exceptions in `app/exceptions.py`, retry with exponential backoff
- Main pipeline: `backend/app/pipeline/video_pipeline.py`

## Brain Vault References
- Architecture: `brain_search("f1 generator architecture")`

## Credentials
All secrets in `.env.example`. Production values in encrypted vault. Use `credential_get("service name")`.

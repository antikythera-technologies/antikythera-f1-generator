# CLAUDE.md - Antikythera F1 Video Generator

## Project Overview

Automated video generation system for satirical F1 commentary videos.

**PRD Location:** `/home/wkoch/clawd/projects/antikythera-f1/PRD.md`

## Tech Stack

### Backend
- **Framework:** FastAPI
- **Database:** PostgreSQL (postgres.antikythera.co.za / AntikytheraF1Series)
- **ORM:** SQLAlchemy 2.0 with async support
- **Storage:** MinIO (minio.antikythera.co.za:9000)
- **Task Queue:** Redis (optional, for job queueing)

### Frontend (Dashboard)
- **Framework:** Next.js 16
- **React:** 19
- **Styling:** Tailwind CSS 4

### External APIs
- **Anthropic Haiku:** Script generation
- **Ovi (Gradio):** Image-to-video generation
- **YouTube Data API v3:** Video upload

## Key Commands

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Run tests
pytest

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"

# Docker
docker-compose up -d
docker-compose logs -f backend
```

## Code Patterns

### Logging
All modules use structured logging. Import logger per module:
```python
import logging
logger = logging.getLogger(__name__)
```

### Database Sessions
Use async sessions with dependency injection:
```python
from app.database import get_db

@app.get("/endpoint")
async def endpoint(db: AsyncSession = Depends(get_db)):
    ...
```

### Error Handling
Use custom exceptions in `app/exceptions.py`. All retry logic uses exponential backoff.

## Key Files

- `backend/app/config.py` - All configuration and env vars
- `backend/app/pipeline/video_pipeline.py` - Main generation pipeline
- `backend/app/services/script_generator.py` - Anthropic integration
- `backend/app/services/video_generator.py` - Ovi integration

## Environment Variables

See `.env.example` for full list. Key ones:
- `ANTHROPIC_API_KEY`
- `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`
- `DATABASE_URL`
- `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test
pytest tests/test_pipeline.py -v
```

## Deployment

Uses Docker Compose. See `docker-compose.yml` for service definitions.

Production deployment on Antikythera infrastructure.

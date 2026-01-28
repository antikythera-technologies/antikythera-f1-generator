# Antikythera F1 Video Generator

Automated video generation system that produces **2-minute satirical F1 commentary videos** twice per week during race season.

## Features

- **Zero manual intervention** after initial setup
- **Consistent branding** with pre-defined 3D characters
- **Engaging content** with speech synthesis and sound effects
- **Cost tracking** for internal expense allocation

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌───────────┐
│   TRIGGER   │───▶│   SCRIPT    │───▶│   VIDEO     │───▶│  UPLOAD   │
│   SERVICE   │    │  GENERATOR  │    │  PIPELINE   │    │  SERVICE  │
└─────────────┘    └─────────────┘    └─────────────┘    └───────────┘
       │                  │                  │                 │
       ▼                  ▼                  ▼                 ▼
  Cron/Webhook       Anthropic           Ovi/ffmpeg        YouTube
```

## Output Specification

| Attribute | Value |
|-----------|-------|
| Video Duration | 2 minutes (120 seconds) |
| Scene Count | 24 scenes |
| Scene Duration | 5 seconds each |
| Frame Rate | 24 FPS |
| Resolution | 1080p |
| Episodes/Week | 2 (during race season) |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- ffmpeg
- Node.js 22+ (for dashboard)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/antikythera/antikythera-f1-generator.git
cd antikythera-f1-generator
```

2. Copy environment template:
```bash
cp .env.example .env
# Edit .env with your credentials
```

3. Start services:
```bash
docker-compose up -d
```

4. Run migrations:
```bash
docker-compose exec backend alembic upgrade head
```

5. Access the dashboard:
```
http://localhost:3000
```

## Project Structure

```
antikythera-f1-generator/
├── backend/           # FastAPI backend
│   ├── app/
│   │   ├── api/       # API endpoints
│   │   ├── models/    # SQLAlchemy models
│   │   ├── schemas/   # Pydantic schemas
│   │   ├── services/  # Business logic
│   │   └── pipeline/  # Video generation pipeline
│   ├── migrations/    # Alembic migrations
│   └── tests/
├── dashboard/         # Next.js frontend
└── docker-compose.yml
```

## API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## External Services

| Service | Purpose |
|---------|---------|
| Anthropic Haiku | Script generation |
| Ovi (HuggingFace) | Image-to-video |
| YouTube API | Video upload |
| MinIO | Object storage |
| PostgreSQL | Metadata storage |

## License

Proprietary - Antikythera Technologies

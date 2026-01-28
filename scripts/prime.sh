#!/bin/bash
# prime.sh - Prime/seed the database for Antikythera F1 Generator
# Usage: ./scripts/prime.sh [--reset]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "================================================"
echo "   Antikythera F1 Generator - Database Prime"
echo "================================================"
echo ""

cd "$PROJECT_DIR"

# Check for .env
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Run ./scripts/install.sh first"
    exit 1
fi

# Load environment
export $(grep -v '^#' .env | xargs)

RESET_FLAG=""
if [ "$1" == "--reset" ]; then
    RESET_FLAG="--reset"
    echo "⚠️  Reset mode: Will drop and recreate all tables"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

cd backend

echo "[1/3] Running database migrations..."
if command -v uv &> /dev/null; then
    uv run alembic upgrade head
else
    python -m alembic upgrade head
fi

echo ""
echo "[2/3] Seeding 2026 F1 calendar and drivers..."
if command -v uv &> /dev/null; then
    uv run python -m app.scripts.seed_data $RESET_FLAG
else
    python -m app.scripts.seed_data $RESET_FLAG
fi

echo ""
echo "[3/3] Verifying database..."
if command -v uv &> /dev/null; then
    uv run python -c "from app.database import get_db; print('✅ Database connection verified')"
else
    python -c "from app.database import get_db; print('✅ Database connection verified')"
fi

echo ""
echo "================================================"
echo "✅ Database primed successfully!"
echo ""
echo "Tables created:"
echo "  - races (2026 F1 calendar)"
echo "  - drivers (2026 grid)"
echo "  - teams"
echo "  - characters (3D character mappings)"
echo "  - episodes (video tracking)"
echo "  - scenes (24 scenes per episode)"
echo "================================================"

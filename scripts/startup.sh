#!/bin/bash
# startup.sh - Start Antikythera F1 Generator for development
# Usage: ./scripts/startup.sh [backend|dashboard|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "================================================"
echo "   Antikythera F1 Generator - Development"
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

MODE="${1:-all}"

start_backend() {
    echo "[Backend] Starting FastAPI server..."
    cd "$PROJECT_DIR/backend"
    if command -v uv &> /dev/null; then
        uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    else
        python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    fi
}

start_dashboard() {
    echo "[Dashboard] Starting Next.js dev server..."
    cd "$PROJECT_DIR/dashboard"
    npm run dev
}

case "$MODE" in
    backend)
        start_backend
        ;;
    dashboard)
        start_dashboard
        ;;
    all)
        echo "Starting all services..."
        echo ""
        # Use docker-compose for local development
        docker-compose up --build
        ;;
    *)
        echo "Usage: $0 [backend|dashboard|all]"
        echo ""
        echo "  backend   - Start FastAPI backend only"
        echo "  dashboard - Start Next.js dashboard only"
        echo "  all       - Start all services with docker-compose (default)"
        exit 1
        ;;
esac

#!/bin/bash
# install.sh - Install dependencies for Antikythera F1 Generator
# Usage: ./scripts/install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "================================================"
echo "   Antikythera F1 Generator - Install"
echo "================================================"
echo ""

cd "$PROJECT_DIR"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Check for uv (preferred) or pip
if command -v uv &> /dev/null; then
    echo "[1/3] Installing Python dependencies with uv..."
    cd backend
    uv sync
    cd ..
else
    echo "[1/3] Installing Python dependencies with pip..."
    cd backend
    pip install -r requirements.txt
    cd ..
fi

# Check for Node.js (for dashboard)
if command -v node &> /dev/null; then
    echo ""
    echo "[2/3] Installing dashboard dependencies..."
    cd dashboard
    npm install
    cd ..
else
    echo ""
    echo "[2/3] ⚠️  Node.js not found - skipping dashboard install"
fi

# Copy .env if not exists
echo ""
echo "[3/3] Setting up environment..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ Created .env from .env.example"
        echo "⚠️  Please update .env with your credentials"
    else
        echo "⚠️  No .env.example found"
    fi
else
    echo "✅ .env already exists"
fi

echo ""
echo "================================================"
echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Update .env with your credentials"
echo "  2. Run: ./scripts/prime.sh (to seed the database)"
echo "  3. Run: ./scripts/startup.sh (to start development)"
echo "================================================"

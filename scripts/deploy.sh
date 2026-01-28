#!/bin/bash
# deploy.sh - Deploy Antikythera F1 Generator to production
# Usage: ./scripts/deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
REMOTE_HOST="antikythera-n8n"
REMOTE_PATH="/opt/antikythera-f1-generator/"
SERVICE_NAME="f1-generator"
DOMAIN="f1.antikythera.co.za"

echo "================================================"
echo "   Antikythera F1 Generator - Production Deploy"
echo "================================================"
echo ""

cd "$PROJECT_DIR"

# Step 1: Sync files
echo "[1/5] Syncing files to server..."
rsync -avz --delete \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='*.pyc' \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.env' \
    ./ "$REMOTE_HOST:$REMOTE_PATH"

# Step 2: Copy .env if exists
echo ""
echo "[2/5] Syncing environment..."
if [ -f ".env.production" ]; then
    rsync -avz .env.production "$REMOTE_HOST:$REMOTE_PATH.env"
elif [ -f ".env" ]; then
    echo "⚠️  Using local .env (consider creating .env.production)"
    rsync -avz .env "$REMOTE_HOST:$REMOTE_PATH.env"
else
    echo "⚠️  No .env found - make sure server has environment configured"
fi

# Step 3: Build and start containers
echo ""
echo "[3/5] Building Docker images..."
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker-compose -f docker-compose.production.yml build"

echo ""
echo "[4/5] Starting services..."
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker-compose -f docker-compose.production.yml down && docker-compose -f docker-compose.production.yml up -d"

# Step 5: Configure Caddy (if not already done)
echo ""
echo "[5/5] Verifying Caddy configuration..."
ssh "$REMOTE_HOST" "grep -q '$DOMAIN' /opt/caddy/Caddyfile 2>/dev/null && echo '✅ Caddy already configured for $DOMAIN' || echo '⚠️  Add $DOMAIN to Caddy configuration'"

# Wait and verify
echo ""
echo "Waiting for services to start..."
sleep 5

# Health check
HEALTH=$(ssh "$REMOTE_HOST" "curl -s http://localhost:8001/health 2>/dev/null" || echo "FAILED")

if [[ "$HEALTH" == *"ok"* ]] || [[ "$HEALTH" == *"healthy"* ]]; then
    echo ""
    echo "================================================"
    echo "✅ Deployment successful!"
    echo ""
    echo "Services:"
    echo "  - Backend:   https://$DOMAIN/api"
    echo "  - Dashboard: https://$DOMAIN"
    echo ""
    echo "Check logs:"
    echo "  ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker-compose logs -f'"
    echo "================================================"
else
    echo ""
    echo "================================================"
    echo "⚠️  Health check response: $HEALTH"
    echo ""
    echo "Debug commands:"
    echo "  ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker-compose ps'"
    echo "  ssh $REMOTE_HOST 'cd $REMOTE_PATH && docker-compose logs'"
    echo "================================================"
fi

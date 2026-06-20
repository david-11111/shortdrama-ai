#!/usr/bin/env bash
set -euo pipefail

# Usage: ssh server ./deploy.sh
# Expects to be run from the project root on the server.

echo "=== Pulling latest code ==="
git pull origin main

echo "=== Building and restarting ==="
docker compose build --pull
docker compose up -d

echo "=== Cleaning up old images ==="
docker image prune -f

echo "=== Checking health ==="
sleep 5
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
  echo "✅ API is healthy"
else
  echo "⚠️  API health check failed — check logs with: docker compose logs api"
fi

echo "=== Deploy complete ==="

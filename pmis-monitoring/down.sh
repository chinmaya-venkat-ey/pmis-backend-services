#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "🛑 Stopping PMIS monitoring stack..."

# Stop all monitoring containers
docker compose --env-file .env down

echo "🧼 Removing unused containers..."
docker container prune -f

echo "🧠 Removing unused images (safe)..."
docker image prune -f

echo "📊 Removing unused volumes (ONLY dangling)..."
docker volume prune -f

echo "✅ Monitoring stack stopped successfully"

#!/bin/bash
set -euo pipefail

# ── Variables — change per client ───────────────────────────────
DOCKERHUB_USER="ritamhudait"
GITHUB_ORG="EY-DIGIT"
NOTIF_REPO="PMIS-notification-service"
BRANCH="dev"
IMAGE="${DOCKERHUB_USER}/pmis-notification"
REPO_DIR="$HOME/pmis-notification"        # code is here directly
VERSION_FILE="$HOME/pmis-env/notification_image_version.txt"
ENV_FILE="$HOME/pmis-notification/.env"
# ────────────────────────────────────────────────────────────────

echo "Pulling latest code from GitHub..."
cd "$REPO_DIR"
git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "Reading version..."
LAST_VERSION=$(cat "$VERSION_FILE" 2>/dev/null || echo "0")
[[ "$LAST_VERSION" =~ ^[0-9]+$ ]] || LAST_VERSION=0
NEXT_VERSION=$((LAST_VERSION + 1))
IMAGE_TAG="v${NEXT_VERSION}"
echo "$NEXT_VERSION" > "$VERSION_FILE"

echo "Building image: $IMAGE:$IMAGE_TAG"
docker build -t "$IMAGE:$IMAGE_TAG" "$REPO_DIR"
docker tag "$IMAGE:$IMAGE_TAG" "$IMAGE:latest"

echo "Logging in to Docker Hub..."
docker login -u "$DOCKERHUB_USER"

echo "Pushing images..."
docker push "$IMAGE:$IMAGE_TAG"
docker push "$IMAGE:latest"

echo "Deploying container..."
docker stop pmis-notification 2>/dev/null || true
docker rm pmis-notification 2>/dev/null || true

# Internal port 8000 → External port 8002
docker run -d \
  --name pmis-notification \
  --restart unless-stopped \
  -p 8002:8000 \
  --env-file "$ENV_FILE" \
  "$IMAGE:$IMAGE_TAG"

docker image prune -f

echo "Waiting for service to start..."
sleep 8

if curl -sf http://localhost:8002/api/v1/health >/dev/null 2>&1; then
    echo ""
    echo "======================================="
    echo "  Notification service is LIVE!"
    echo "  Version : $IMAGE_TAG"
    echo "  Health  : http://localhost:8002/api/v1/health"
    echo "  Docs    : http://localhost:8002/docs"
    echo "======================================="
else
    echo "[WARN] Health check failed. Check logs:"
    docker logs --tail 30 pmis-notification
fi

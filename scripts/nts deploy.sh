#!/bin/bash
set -euo pipefail

DOCKERHUB_USER="ritamhudait"
BRANCH="dev_micro"

# Docker image names MUST be lowercase
IMAGE="${DOCKERHUB_USER}/pmis-notification-service"

REPO_DIR="$HOME/PMIS-notification-service/src"
VERSION_FILE="$HOME/pmis-env/PMIS-notification-service.txt"
ENV_FILE="$HOME/PMIS-notification-service/.env"

echo "Pulling latest code..."

if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"

    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"

else
    mkdir -p "$REPO_DIR"

    git clone --branch "$BRANCH" \
    "https://TOKEN@github.com/EY-DIGIT/PMIS-notification-service.git" \
    "$REPO_DIR"

    cd "$REPO_DIR"
fi

LAST_VERSION=$(cat "$VERSION_FILE" 2>/dev/null || echo "0")

[[ "$LAST_VERSION" =~ ^[0-9]+$ ]] || LAST_VERSION=0

NEXT_VERSION=$((LAST_VERSION + 1))
IMAGE_TAG="v${NEXT_VERSION}"

echo "$NEXT_VERSION" > "$VERSION_FILE"

echo "Building: $IMAGE:$IMAGE_TAG"

docker build -t "$IMAGE:$IMAGE_TAG" "$REPO_DIR"

docker tag "$IMAGE:$IMAGE_TAG" "$IMAGE:latest"

docker login -u "$DOCKERHUB_USER"

docker push "$IMAGE:$IMAGE_TAG"
docker push "$IMAGE:latest"

docker stop PMIS-notification-service 2>/dev/null || true
docker rm PMIS-notification-service 2>/dev/null || true

docker run -d \
  --name PMIS-notification-service \
  --restart unless-stopped \
  -p 8012:8002 \
  --env-file "$ENV_FILE" \
  "$IMAGE:$IMAGE_TAG"

docker image prune -f

sleep 10

curl -sf http://localhost:8012/health \
  && echo "PMIS-notification-service healthy" \
  || echo "Check logs: docker logs PMIS-notification-service"

echo "Done: $IMAGE_TAG"

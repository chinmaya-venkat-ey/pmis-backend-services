#!/bin/bash
set -euo pipefail

BRANCH="dev"
IMAGE="ritamhudait/pmis-usermanagement"
REPO_DIR="$HOME/pmis-usermanagement/src"
VERSION_FILE="$HOME/pmis-env/usermanagement_image_version.txt"

# ── Step 1: Pull latest code ────────────────────────────────────
echo "Pulling latest code from GitHub..."

if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    mkdir -p "$REPO_DIR"
    git clone --branch "$BRANCH" https://github.com/EY-DIGIT/PMIS-user-management.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

# ── Step 2: Read & bump version ─────────────────────────────────
echo "Reading version..."
if [ -f "$VERSION_FILE" ]; then
    LAST_VERSION=$(cat "$VERSION_FILE")
else
    LAST_VERSION=0
fi

if ! [[ "$LAST_VERSION" =~ ^[0-9]+$ ]]; then
    LAST_VERSION=0
fi

NEXT_VERSION=$((LAST_VERSION + 1))
IMAGE_TAG="v${NEXT_VERSION}"
echo "$NEXT_VERSION" > "$VERSION_FILE"

# ── Step 3: Build ────────────────────────────────────────────────
echo "Building image: $IMAGE:$IMAGE_TAG"
docker build -t "$IMAGE:$IMAGE_TAG" "$REPO_DIR"

# ── Step 4: Tag latest ───────────────────────────────────────────
echo "Tagging latest..."
docker tag "$IMAGE:$IMAGE_TAG" "$IMAGE:latest"

# ── Step 5: Push ─────────────────────────────────────────────────
echo "Logging in to Docker Hub..."
docker login -u ritamhudait

echo "Pushing images..."
docker push "$IMAGE:$IMAGE_TAG"
docker push "$IMAGE:latest"

# ── Step 6: Deploy ───────────────────────────────────────────────
echo "Deploying container..."
docker stop pmis-usermanagement 2>/dev/null || true
docker rm pmis-usermanagement 2>/dev/null || true

docker run -d \
  --name pmis-usermanagement \
  --network host \
  --restart unless-stopped \
  --env-file "$HOME/pmis-usermanagement/.env" \
  "$IMAGE:$IMAGE_TAG"

# ── Step 7: Cleanup ──────────────────────────────────────────────
echo "Cleaning unused images..."
docker image prune -f

echo "Done. Deployed version: $IMAGE_TAG"


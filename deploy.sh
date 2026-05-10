#!/usr/bin/env bash
set -euo pipefail

# ── Config ─────────────────────────────────────────────
GITHUB_ORG="EY-DIGIT"
REPO="PMIS-project-management"
BRANCH="dev"

IMAGE_NAME="pmis-projectmanagement"
REPO_DIR="$HOME/pmis-projectmanagement"
VERSION_FILE="$HOME/pmis-env/projectmanagement_image_version.txt"
ENV_FILE="$REPO_DIR/.env"

echo "---------------------------------------"
echo " PMIS PROJECT MANAGEMENT DEPLOYMENT"
echo "---------------------------------------"

# ── Step 1: Pull latest code ───────────────────────────
echo "Pulling latest code..."

if [ -d "$REPO_DIR/.git" ]; then
    cd "$REPO_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    mkdir -p "$REPO_DIR"
    git clone --branch "$BRANCH" \
        https://github.com/${GITHUB_ORG}/${REPO}.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

COMMIT=$(git rev-parse --short HEAD)

# ── Step 2: Versioning ─────────────────────────────────
echo "Reading version..."

if [[ -f "$VERSION_FILE" ]]; then
    LAST_VERSION=$(cat "$VERSION_FILE")
else
    LAST_VERSION=0
fi

[[ "$LAST_VERSION" =~ ^[0-9]+$ ]] || LAST_VERSION=0

NEXT_VERSION=$((LAST_VERSION + 1))
IMAGE_TAG="v${NEXT_VERSION}"

echo "$NEXT_VERSION" > "$VERSION_FILE"

# ── Step 3: Docker Hub optional ────────────────────────
echo ""
read -rp "Push to Docker Hub? (y/n): " USE_DOCKER_HUB
USE_DOCKER_HUB=$(echo "$USE_DOCKER_HUB" | tr '[:upper:]' '[:lower:]')

if [[ "$USE_DOCKER_HUB" == "y" ]]; then
    read -rp "Docker Username: " DOCKER_USERNAME
    read -rsp "Docker Token/Password: " DOCKER_PASSWORD
    echo ""

    echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin

    FULL_IMAGE="${DOCKER_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"
    LATEST_IMAGE="${DOCKER_USERNAME}/${IMAGE_NAME}:latest"
else
    echo "Skipping Docker Hub..."
    DOCKER_USERNAME=""
    FULL_IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
    LATEST_IMAGE="${IMAGE_NAME}:latest"
fi

# ── Step 4: Build ─────────────────────────────────────
echo "Building image: $FULL_IMAGE"
docker build -t "$FULL_IMAGE" "$REPO_DIR"

echo "Tagging latest..."
docker tag "$FULL_IMAGE" "$LATEST_IMAGE"

# ── Step 5: Push (optional) ───────────────────────────
if [[ "$USE_DOCKER_HUB" == "y" ]]; then
    echo "Pushing to Docker Hub..."
    docker push "$FULL_IMAGE"
    docker push "$LATEST_IMAGE"
else
    echo "Skipping push..."
fi

# ── Step 6: Deploy ────────────────────────────────────
echo "Deploying container..."

docker stop pmis-projectmanagement 2>/dev/null || true
docker rm   pmis-projectmanagement 2>/dev/null || true

docker run -d \
  --name pmis-projectmanagement \
  --network host \
  --restart unless-stopped \
  -v /mnt/pmis_files:/mnt/pmis_files:rw \
  --env-file "$ENV_FILE" \
  "$FULL_IMAGE"

# ── Step 7: Cleanup ───────────────────────────────────
echo "Cleaning unused images..."
docker image prune -f

# ── Done ──────────────────────────────────────────────
echo ""
echo "---------------------------------------"
echo " DEPLOYMENT SUCCESS"
echo "---------------------------------------"
echo " Image   : $FULL_IMAGE"
echo " Commit  : $COMMIT"
echo " Branch  : $BRANCH"
echo " Version : $IMAGE_TAG"
echo "---------------------------------------"

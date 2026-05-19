#!/bin/bash
set -euo pipefail

# ================================
# CONFIG (EDIT THIS)
# ================================
IMAGE_NAME="ritamhudait/pmis-redis"
CONTAINER_NAME="pmis-redis"
PORT="6379"

# ================================
# AUTO VERSIONING
# ================================
VERSION_FILE="./redis_image_version.txt"

if [ ! -f "$VERSION_FILE" ]; then
  echo "v1" > "$VERSION_FILE"
fi

CURRENT_VERSION=$(cat "$VERSION_FILE")

# Extract number
VERSION_NUMBER=${CURRENT_VERSION#v}
NEW_VERSION="v$((VERSION_NUMBER + 1))"

echo "Current version: $CURRENT_VERSION"
echo "New version: $NEW_VERSION"

# ================================
# DOCKER LOGIN (SECURE)
# ================================
echo "Docker Hub Login Required"

read -p "Enter Docker Hub Username: " DOCKER_USERNAME
read -s -p "Enter Docker Hub Password: " DOCKER_PASSWORD
echo ""

echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin

# ================================
# BUILD IMAGE
# ================================
echo "Building Docker image..."

docker build -t $IMAGE_NAME:$NEW_VERSION .

# ================================
# PUSH IMAGE
# ================================
echo "Pushing to Docker Hub..."

docker push $IMAGE_NAME:$NEW_VERSION

# ================================
# SAVE VERSION
# ================================
echo "$NEW_VERSION" > "$VERSION_FILE"

# ================================
# DEPLOY CONTAINER
# ================================
echo "Stopping old container (if exists)..."

docker stop $CONTAINER_NAME 2>/dev/null || true
docker rm $CONTAINER_NAME 2>/dev/null || true

echo "Starting new container..."

docker run -d \
  --name $CONTAINER_NAME \
  -p $PORT:6379 \
  --restart always \
  $IMAGE_NAME:$NEW_VERSION

# ================================
# VERIFY
# ================================
echo "Checking Redis..."

sleep 3

if docker exec $CONTAINER_NAME redis-cli ping | grep -q PONG; then
  echo " Redis is running successfully!"
else
  echo "Redis failed to start!"
  exit 1
fi

echo "Deployment completed with version $NEW_VERSION"

#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

DOCKERHUB_USER="ritamhudait"
IMAGE_NAME="pmis-monitoring"
VERSION_FILE="version.txt"

# Read current version
VERSION=$(cat "$VERSION_FILE")
NEW_VERSION=$((VERSION + 1))
TAG="v${NEW_VERSION}"

echo "====================================="
echo " PMIS MONITORING DEPLOYMENT"
echo "====================================="
echo "Building version: $TAG"

# Build lightweight wrapper image

docker build \
  -t ${DOCKERHUB_USER}/${IMAGE_NAME}:${TAG} \
  -t ${DOCKERHUB_USER}/${IMAGE_NAME}:latest \
  .

# DockerHub login

echo "DockerHub login"
docker login -u ${DOCKERHUB_USER}

# Push images

docker push ${DOCKERHUB_USER}/${IMAGE_NAME}:${TAG}
docker push ${DOCKERHUB_USER}/${IMAGE_NAME}:latest

# Update version file

echo ${NEW_VERSION} > ${VERSION_FILE}

# Pull latest monitoring images first

echo "Pulling latest monitoring images..."
docker compose --env-file .env pull

# Deploy monitoring stack safely

echo "Starting monitoring stack safely..."
docker compose --env-file .env up -d --remove-orphans

# Remove ONLY dangling images
# safer than docker image prune -f

echo "Cleaning unused dangling images..."
docker image prune -f --filter "dangling=true"

echo "====================================="
echo " Monitoring deployed successfully"
echo "====================================="

#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="pmis-frontend"
VERSION_FILE=".image_version"
ENV_FILE=".env"
HOST_PORT="3000"

echo "---------------------------------------"
echo " PMIS FRONTEND DOCKER DEPLOYMENT"
echo "---------------------------------------"

# ── Pre-flight ─────────────────────────────────────────
command -v docker >/dev/null || { echo "Docker not installed"; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose not installed"; exit 1; }

[ -f package.json ] || { echo "Run from project root"; exit 1; }

# ── Git Pull ───────────────────────────────────────────
echo "Pulling latest code..."
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Stashing local changes..."
  git stash push -m "auto-deploy $(date)"
  STASHED=true
else
  STASHED=false
fi

git pull origin "$CURRENT_BRANCH"

[[ "$STASHED" == true ]] && git stash pop || true

COMMIT=$(git rev-parse --short HEAD)

# ── Load env ───────────────────────────────────────────
[ -f ".env.development" ] || { echo ".env.development missing"; exit 1; }

echo "Loading env..."

while IFS='=' read -r key value; do
  [[ -z "$key" || "$key" =~ ^# ]] && continue
  value="${value%%#*}"
  value="$(echo -e "${value}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  export "$key=$value"
done < ".env.development"

[ -n "${VITE_API_BASE_URL:-}" ] || {
  echo "VITE_API_BASE_URL not set"
  exit 1
}

# ── Docker Hub Optional ────────────────────────────────
echo ""
read -rp "Push to Docker Hub? (y/n): " USE_DOCKER_HUB
USE_DOCKER_HUB=$(echo "$USE_DOCKER_HUB" | tr '[:upper:]' '[:lower:]')

if [[ "$USE_DOCKER_HUB" == "y" ]]; then
  read -rp "Docker Username: " DOCKER_USERNAME
  read -rsp "Docker Token/Password: " DOCKER_PASSWORD
  echo ""

  echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
  PUSH_ENABLED=true
else
  DOCKER_USERNAME=""
  PUSH_ENABLED=false
fi

# ── Versioning ─────────────────────────────────────────
if [[ -f "$VERSION_FILE" ]]; then
  CURRENT_VERSION=$(cat "$VERSION_FILE")
else
  CURRENT_VERSION=0
fi

NEW_VERSION=$((CURRENT_VERSION + 1))
TAG="v${NEW_VERSION}"

if [[ "$PUSH_ENABLED" == true ]]; then
  FULL_IMAGE="${DOCKER_USERNAME}/${IMAGE_NAME}:${TAG}"
  LATEST_IMAGE="${DOCKER_USERNAME}/${IMAGE_NAME}:latest"
else
  FULL_IMAGE="${IMAGE_NAME}:${TAG}"
  LATEST_IMAGE="${IMAGE_NAME}:latest"
fi

echo "Building: $FULL_IMAGE"

# ── Build Args ─────────────────────────────────────────
BUILD_ARGS=""
while IFS='=' read -r key value; do
  [[ "$key" == VITE_* ]] && BUILD_ARGS+=" --build-arg $key=$value"
done < ".env.development"

docker build $BUILD_ARGS -t "$FULL_IMAGE" .
docker tag "$FULL_IMAGE" "$LATEST_IMAGE"

# ── Push (optional) ────────────────────────────────────
if [[ "$PUSH_ENABLED" == true ]]; then
  echo "Pushing to Docker Hub..."
  docker push "$FULL_IMAGE"
  docker push "$LATEST_IMAGE"
else
  echo "Skipping Docker push"
fi

# ── Save Version ───────────────────────────────────────
echo "$NEW_VERSION" > "$VERSION_FILE"

cat > "$ENV_FILE" <<EOF
DOCKER_USERNAME=$DOCKER_USERNAME
VERSION=$TAG
EOF

# ── Deploy ─────────────────────────────────────────────
echo "Restarting container..."
docker compose down || true
docker compose up -d

# ── Done ───────────────────────────────────────────────
echo ""
echo "---------------------------------------"
echo " DEPLOYMENT SUCCESS"
echo "---------------------------------------"
echo " Image   : $FULL_IMAGE"
echo " Commit  : $COMMIT"
echo " Branch  : $CURRENT_BRANCH"
echo " URL     : http://$(hostname -I | awk '{print $1}'):${HOST_PORT}"
echo "---------------------------------------"

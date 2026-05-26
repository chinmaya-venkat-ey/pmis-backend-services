#!/usr/bin/env bash
##############################################################
# deploy.sh
# Pull code from git → build FastAPI image → start the stack
#
# Usage:
#   ./deploy.sh              – full deploy (default branch from .env)
#   ./deploy.sh --branch dev – deploy a specific branch
#   ./deploy.sh --no-build   – skip image build, just restart containers
##############################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Parse flags ───────────────────────────────────────────
BUILD=true
BRANCH=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build) BUILD=false; shift ;;
    --branch)   BRANCH="$2"; shift 2 ;;
    *) error "Unknown flag: $1" ;;
  esac
done

# ── Load .env ─────────────────────────────────────────────
[[ -f .env ]] || error ".env not found. Run: cp .env.example .env  then fill it in."
set -a; source .env; set +a
BRANCH="${BRANCH:-${REPO_BRANCH:-main}}"

# ── Resolve which LLM service URL to advertise to FastAPI ─
if [[ "${LLM_BACKEND:-ollama}" == "vllm" ]]; then
  LLM_BASE_URL="http://vllm:8000"
  LLM_SVC="vllm"
  LLM_INFO="${LLM_MODEL:-Qwen/Qwen3-8B} via vLLM"
else
  LLM_BASE_URL="http://ollama:11434"
  LLM_SVC="ollama"
  LLM_INFO="${OLLAMA_MODEL:-qwen3:8b} via Ollama"
fi
export LLM_BASE_URL

echo ""
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo    "  AI Stack Deploy"
echo    "  LLM    : $LLM_INFO"
echo    "  Branch : $BRANCH"
echo    "  Build  : $BUILD"
echo -e "${CYAN}══════════════════════════════════════════════${NC}"
echo ""

# ── Pre-flight ────────────────────────────────────────────
command -v docker >/dev/null 2>&1  || error "Docker not installed. Run: curl -fsSL https://get.docker.com | sudo sh"
docker compose version >/dev/null 2>&1 || error "Docker Compose v2 not found. Run: sudo apt-get install docker-compose-plugin"

[[ -n "${DATABASE_URL:-}" && "$DATABASE_URL" != *"HOST_IP"* ]] \
  || error "DATABASE_URL in .env is still the placeholder. Please set your real DB connection string."

# ── Clone / update your FastAPI repo ─────────────────────
REPO_DIR="$SCRIPT_DIR/app_repo"

if $BUILD; then
  if [[ -d "$REPO_DIR/.git" ]]; then
    info "Updating repo to branch '$BRANCH'..."
    git -C "$REPO_DIR" fetch origin
    git -C "$REPO_DIR" checkout "$BRANCH"
    git -C "$REPO_DIR" pull origin "$BRANCH"
  else
    info "Cloning $REPO_URL (branch: $BRANCH)..."
    git clone --branch "$BRANCH" "${REPO_URL}" "$REPO_DIR"
  fi
  success "Repo ready."

  # ── Build FastAPI Docker image ───────────────────────
  DOCKERFILE="$REPO_DIR/Dockerfile"
  [[ -f "$DOCKERFILE" ]] || DOCKERFILE="$REPO_DIR/docker/Dockerfile"
  [[ -f "$DOCKERFILE" ]] || {
    warn "No Dockerfile found in repo."
    warn "Copy docs/Dockerfile.example into your repo root as 'Dockerfile' and push it."
    error "Cannot build image without a Dockerfile."
  }

  info "Building image: ${FASTAPI_IMAGE:-fastapi-app:latest} ..."
  docker build \
    -t "${FASTAPI_IMAGE:-fastapi-app:latest}" \
    -f "$DOCKERFILE" \
    --build-arg APP_ENV=production \
    "$REPO_DIR"
  success "Image built."
fi

# ── Start services ────────────────────────────────────────
# Start the chosen LLM backend, plus all shared services.
# The other LLM service is intentionally NOT started.
info "Starting shared services (embedding, qdrant, paddleocr)..."
docker compose up -d embedding qdrant paddleocr

info "Starting LLM backend: $LLM_SVC ..."
docker compose up -d "$LLM_SVC"

info "Starting FastAPI app..."
docker compose up -d --remove-orphans fastapi

# ── Health check loop ─────────────────────────────────────
echo ""
info "Waiting for all services to become healthy..."
info "(First run downloads models — this can take 5-20 minutes)"
echo ""

SERVICES=("qdrant" "embedding" "paddleocr" "$LLM_SVC" "fastapi")
ALL_OK=true

for svc in "${SERVICES[@]}"; do
  printf "  %-15s" "$svc"
  TIMEOUT=600   # 10 minutes – generous for model downloads
  ELAPSED=0
  while true; do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "missing")
    case "$STATUS" in
      healthy)   echo -e " ${GREEN}✓ healthy${NC}"; break ;;
      unhealthy) echo -e " ${RED}✗ unhealthy${NC}"; ALL_OK=false; break ;;
      missing)   echo -e " ${RED}✗ not found${NC}"; ALL_OK=false; break ;;
      *)
        if [[ $ELAPSED -ge $TIMEOUT ]]; then
          echo -e " ${YELLOW}⚠ timed out${NC}"; ALL_OK=false; break
        fi
        printf "."; sleep 10; ELAPSED=$((ELAPSED + 10)) ;;
    esac
  done
done

echo ""
if $ALL_OK; then
  success "All services healthy! Your stack is running."
  echo ""
  echo "  FastAPI  → http://localhost:${FASTAPI_PORT:-8080}"
  if [[ "$LLM_SVC" == "ollama" ]]; then
    echo "  Ollama   → http://localhost:11434"
  else
    echo "  vLLM     → http://localhost:8000"
  fi
  echo "  Qdrant   → http://localhost:6333"
  echo "  Embedder → http://localhost:8001"
  echo "  OCR      → http://localhost:8002"
  echo ""
  echo "  Tip: ./stack.sh status   – check health at any time"
  echo "  Tip: ./stack.sh logs fastapi – tail your app logs"
else
  echo ""
  warn "One or more services are not healthy yet."
  warn "Check logs:  ./stack.sh logs <service_name>"
  warn "Services: ollama  vllm  embedding  qdrant  paddleocr  fastapi"
fi

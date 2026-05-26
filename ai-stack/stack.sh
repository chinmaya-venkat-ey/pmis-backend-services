#!/usr/bin/env bash
##############################################################
# stack.sh  –  Day-to-day control of your AI stack
#
# Usage:
#   ./stack.sh up              – start everything
#   ./stack.sh down            – stop everything (data kept safe)
#   ./stack.sh restart         – restart everything
#   ./stack.sh restart fastapi – restart one service
#   ./stack.sh status          – health overview
#   ./stack.sh logs fastapi    – tail logs (Ctrl+C to stop)
#   ./stack.sh logs vllm
#   ./stack.sh reset-volumes   – DANGER: wipe all stored data
##############################################################
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

[[ -f .env ]] && { set -a; source .env; set +a; }

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }

# Which LLM backend is active?
LLM_SVC="${LLM_BACKEND:-ollama}"

CMD="${1:-help}"; shift || true

case "$CMD" in

  up)
    if [[ $# -eq 0 ]]; then
      info "Starting all services (LLM backend: $LLM_SVC)..."
      docker compose up -d embedding qdrant paddleocr "$LLM_SVC"
      docker compose up -d fastapi
    else
      info "Starting: $*"
      docker compose up -d "$@"
    fi
    success "Done. Run './stack.sh status' to check health."
    ;;

  down)
    info "Stopping all services (data volumes are preserved)..."
    docker compose down
    success "Stack stopped. Your Qdrant data and model cache are safe."
    ;;

  restart)
    if [[ $# -eq 0 ]]; then
      info "Restarting all services..."
      docker compose restart
    else
      info "Restarting: $*"
      docker compose restart "$@"
    fi
    ;;

  logs)
    SVC="${1:-fastapi}"
    info "Tailing logs for '$SVC'  (Ctrl+C to stop)"
    docker compose logs -f --tail=100 "$SVC"
    ;;

  status)
    echo ""
    echo -e "${CYAN}══ AI Stack Status ══════════════════════════════${NC}"
    echo -e "   LLM backend configured: ${YELLOW}${LLM_SVC}${NC}"
    echo ""
    printf "  %-15s %-12s %-12s\n" "SERVICE" "STATE" "HEALTH"
    echo "  ──────────────────────────────────────────"
    for svc in ollama vllm embedding qdrant paddleocr fastapi; do
      STATE=$(docker inspect --format='{{.State.Status}}'        "$svc" 2>/dev/null || echo "not running")
      HEALTH=$(docker inspect --format='{{.State.Health.Status}}' "$svc" 2>/dev/null || echo "—")
      # colour the health column
      case "$HEALTH" in
        healthy)   HC="${GREEN}" ;;
        unhealthy) HC="${RED}" ;;
        starting)  HC="${YELLOW}" ;;
        *)         HC="${NC}" ;;
      esac
      # dim services that are not the active LLM backend
      if [[ "$svc" == "ollama" && "$LLM_SVC" != "ollama" ]]; then
        printf "  %-15s ${NC}%-12s ${NC}%-12s  (inactive backend)\n" "$svc" "$STATE" "$HEALTH"
      elif [[ "$svc" == "vllm" && "$LLM_SVC" != "vllm" ]]; then
        printf "  %-15s ${NC}%-12s ${NC}%-12s  (inactive backend)\n" "$svc" "$STATE" "$HEALTH"
      else
        printf "  %-15s %-12s ${HC}%-12s${NC}\n" "$svc" "$STATE" "$HEALTH"
      fi
    done
    echo ""
    ;;

  reset-volumes)
    echo -e "${RED}WARNING: This permanently deletes Qdrant vector data and cached models!${NC}"
    echo    "Your PostgreSQL database and NFS/S3 files are NOT affected."
    read -rp "Type YES to confirm: " CONFIRM
    if [[ "$CONFIRM" == "YES" ]]; then
      docker compose down -v
      success "All Docker volumes deleted. Run './deploy.sh' to start fresh."
    else
      info "Cancelled — nothing was deleted."
    fi
    ;;

  *)
    echo ""
    echo "Usage: $0 <command> [service]"
    echo ""
    echo "  up [svc...]        Start everything, or specific services"
    echo "  down               Stop everything (keeps all data)"
    echo "  restart [svc...]   Restart everything, or specific services"
    echo "  logs <svc>         Stream logs  (default: fastapi)"
    echo "  status             Health overview of all services"
    echo "  reset-volumes      DANGER: delete all stored data"
    echo ""
    echo "Services you can name:"
    echo "  ollama    embedding    qdrant    paddleocr    fastapi"
    echo "  vllm      (only if LLM_BACKEND=vllm in .env)"
    echo ""
    ;;
esac

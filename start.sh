#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  start.sh — RazorShield AI one-command launcher
#  Starts both the FastAPI backend (port 8000) and Next.js frontend (port 3000)
#  concurrently, with graceful SIGINT/SIGTERM handling.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[0;33m"
RESET="\033[0m"

banner() { echo -e "\n${BOLD}${BLUE}══════════════════════════════════════════${RESET}"; }
info()   { echo -e "  ${GREEN}→${RESET} $*"; }
warn()   { echo -e "  ${YELLOW}⚠${RESET}  $*"; }

banner
echo -e "  ${BOLD}RazorShield AI — Full-Stack Launcher${RESET}"
banner

# ── Validate prerequisites ───────────────────────────────────────────────────
PYTHON=$(command -v python3.11 || command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
  echo "ERROR: python3.11 not found. Install via Homebrew: brew install python@3.11" >&2
  exit 1
fi
info "Python: $($PYTHON --version)"

NODE=$(command -v node || true)
if [[ -z "$NODE" ]]; then
  echo "ERROR: node not found. Install from https://nodejs.org" >&2
  exit 1
fi
info "Node:   $(node --version)"

# ── Free ports if occupied ───────────────────────────────────────────────────
for PORT in 8000 3000; do
  PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)
  if [[ -n "$PIDS" ]]; then
    warn "Port $PORT in use — killing PIDs: $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    sleep 0.5
  fi
done

# ── Backend ──────────────────────────────────────────────────────────────────
info "Starting FastAPI backend on http://localhost:8000 …"
"$PYTHON" -m uvicorn razorshield_backend.main:app \
  --host 0.0.0.0 --port 8000 \
  --log-level info \
  2>&1 | sed "s/^/  [BACKEND] /" &
BACKEND_PID=$!

# Wait for backend to be ready (max 20s)
echo -n "  Waiting for backend"
for i in $(seq 1 20); do
  sleep 1
  if curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1; then
    echo " ✓"
    break
  fi
  echo -n "."
  if [[ $i -eq 20 ]]; then
    echo ""
    warn "Backend slow to start — continuing anyway"
  fi
done

# ── Frontend ─────────────────────────────────────────────────────────────────
info "Starting Next.js frontend on http://localhost:3000 …"
npm run dev -- --port 3000 2>&1 | sed "s/^/  [FRONTEND] /" &
FRONTEND_PID=$!

# ── Summary ──────────────────────────────────────────────────────────────────
banner
echo -e "  ${BOLD}Both servers running${RESET}"
echo -e "  Frontend:  ${BLUE}http://localhost:3000${RESET}"
echo -e "  Backend:   ${BLUE}http://localhost:8000${RESET}"
echo -e "  API Docs:  ${BLUE}http://localhost:8000/api/docs${RESET}"
banner
echo ""
echo "  Press Ctrl-C to stop both servers."

# ── Graceful shutdown ────────────────────────────────────────────────────────
cleanup() {
  echo -e "\n${YELLOW}  Shutting down…${RESET}"
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "  Done."
}
trap cleanup EXIT INT TERM

wait

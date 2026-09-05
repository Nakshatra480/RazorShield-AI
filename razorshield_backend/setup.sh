#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# RazorShield AI — Backend Setup Script (macOS / Homebrew Python 3.11)
# ─────────────────────────────────────────────────────────────────────────────
# Usage (run from project root):
#   bash razorshield_backend/setup.sh
#
# On macOS, `pip` is not in PATH when Python was installed via Homebrew.
# This script always invokes `python3.11 -m pip` to target the correct env.
# ─────────────────────────────────────────────────────────────────────────────
set -e

# Resolve to project root (one level above this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

PYTHON="python3.11"
PIP="$PYTHON -m pip"

echo "──────────────────────────────────────────────"
echo "  RazorShield AI Backend — Dependency Setup"
echo "──────────────────────────────────────────────"
echo "Python:  $($PYTHON --version)"
echo "Pip:     $($PIP --version | head -1)"
echo "Project: $PROJECT_ROOT"
echo ""

# 1. Install CPU-only PyTorch first (prevents pulling CUDA wheels, saves ~2 GB)
echo "→ Installing PyTorch (CPU only, ~200 MB)..."
$PIP install torch --index-url https://download.pytorch.org/whl/cpu --quiet

# 2. Install all backend requirements
echo "→ Installing backend dependencies (this may take 3–5 minutes)..."
$PIP install -r "$SCRIPT_DIR/requirements.txt" --quiet

# 3. Install Playwright browsers (Chromium only)
echo "→ Installing Playwright Chromium browser (~130 MB)..."
$PYTHON -m playwright install chromium

echo ""
echo "✅ Setup complete! All packages installed into python3.11"
echo ""
echo "To start the backend API server:"
echo "  cd $PROJECT_ROOT"
echo "  python3.11 -m uvicorn razorshield_backend.main:app --reload --port 8000"
echo ""
echo "To run the benchmark evaluation:"
echo "  python3.11 -m razorshield_backend.benchmark"


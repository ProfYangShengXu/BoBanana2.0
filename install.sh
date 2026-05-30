#!/usr/bin/env bash
# BoBanana 2.0 installer for macOS / Linux — run: chmod +x install.sh && ./install.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[install] Python not found. Install Python 3.10+ first." >&2
  exit 1
fi

exec "$PY" "$ROOT/install.py" "$@"

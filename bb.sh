#!/usr/bin/env bash
# BoBanana 2.0 launcher for macOS / Linux (mirrors bb.ps1)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV_PY="$ROOT/.venv/bin/python"
if [[ ! -f "$VENV_PY" ]]; then
  echo "[bb] .venv not found — run ./install.sh first" >&2
  exit 1
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

info()  { echo -e "\033[36m[bb] $*\033[0m"; }
ok()    { echo -e "\033[32m[bb] $*\033[0m"; }
warn()  { echo -e "\033[33m[bb] $*\033[0m"; }
fail()  { echo -e "\033[31m[bb] $*\033[0m" >&2; exit 1; }

run_tests() {
  info "running selfcheck + offline tests ..."
  "$VENV_PY" -m bobanana --selfcheck
  "$VENV_PY" "$ROOT/tests/test_graph_offline.py"
  "$VENV_PY" "$ROOT/tests/test_skills_offline.py"
  ok "all tests passed"
}

start_agent() {
  info "launching agent ... (type /quit to exit)"
  exec "$VENV_PY" -m bobanana "$@"
}

stop_bobanana() {
  local pids
  pids=$(pgrep -f "[p]ython.*bobanana" 2>/dev/null || true)
  if [[ -z "$pids" ]]; then
    warn "no running bobanana instance found"
    return 0
  fi
  echo "$pids" | xargs kill -TERM 2>/dev/null || true
  ok "stopped bobanana"
}

show_help() {
  cat <<'EOF'
BoBanana 2.0 — launcher (macOS / Linux)

  ./bb.sh start [args]   run tests, then launch the agent
  ./bb.sh use   [args]   launch quickly (skips tests)
  ./bb.sh close          stop any running bobanana instance
  ./bb.sh restart [args] close, then start (with tests)
  ./bb.sh test             selfcheck + offline tests only
  ./bb.sh setup            refresh dependencies in .venv
  ./bb.sh install [args]   full install (see INSTALL.md)
  ./bb.sh config           configure API key / model (interactive)
  ./bb.sh help             show this help
EOF
}

CMD="${1:-help}"
shift || true
CMD_LOWER=$(echo "$CMD" | tr '[:upper:]' '[:lower:]')

case "$CMD_LOWER" in
  start)
    run_tests
    start_agent "$@"
    ;;
  use)
    start_agent "$@"
    ;;
  close|stop)
    stop_bobanana
    ;;
  restart)
    stop_bobanana || true
    run_tests
    start_agent "$@"
    ;;
  test)
    run_tests
    ;;
  setup)
    "$VENV_PY" -m pip install -r "$ROOT/requirements.txt"
    ok "setup done"
    ;;
  install)
    exec "$ROOT/install.sh" "$@"
    ;;
  config)
    "$VENV_PY" -m bobanana --configure
    ;;
  help|-h|--help)
    show_help
    ;;
  *)
    fail "unknown command: $CMD"
    show_help
    ;;
esac

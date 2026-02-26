#!/usr/bin/env bash
# Swarm orchestrator management script.
# Usage: ./run.sh {start|stop|restart|status|logs|install|uninstall}

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/swarm.pid"
LOGFILE="$DIR/swarm.log"
VENV="$DIR/.venv/bin/python"
SERVICE_NAME="claude-swarm"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Helpers ──────────────────────────────────────────────

_is_systemd() {
  [ -f "$SERVICE_FILE" ] && command -v systemctl &>/dev/null
}

_require_sudo() {
  if [ "$EUID" -ne 0 ]; then
    echo "This command requires sudo. Re-running with sudo..."
    exec sudo "$0" "$@"
  fi
}

_ensure_venv() {
  if [ -f "$DIR/.venv/bin/python" ]; then
    return 0
  fi

  echo "Setting up Python virtual environment..."

  # Find python3
  if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first:"
    echo "  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
  fi

  # Check version >= 3.10
  PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.minor}")')
  if [ "$PY_VERSION" -lt 10 ]; then
    echo "ERROR: Python 3.10+ required (found 3.${PY_VERSION})"
    exit 1
  fi

  # Create venv and install deps
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install --upgrade pip -q
  "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt" -q
  echo "Virtual environment ready"
}

_ensure_env() {
  if [ -f "$DIR/.env" ]; then
    return 0
  fi

  echo ""
  echo "No .env file found — let's set it up."
  echo ""

  # Copy template
  cp "$DIR/.env.example" "$DIR/.env"

  read -rp "CLAUDE_CODE_OAUTH_TOKEN (from 'claude setup-token'): " TOKEN
  read -rp "GH_TOKEN (GitHub PAT): " GH
  read -rp "GITHUB_REPO (e.g. owner/repo): " REPO
  read -rp "TARGET_REPO_PATH (absolute path to local clone): " TARGET

  sed -i "s|^CLAUDE_CODE_OAUTH_TOKEN=.*|CLAUDE_CODE_OAUTH_TOKEN=${TOKEN}|" "$DIR/.env"
  sed -i "s|^GH_TOKEN=.*|GH_TOKEN=${GH}|" "$DIR/.env"
  sed -i "s|^GITHUB_REPO=.*|GITHUB_REPO=${REPO}|" "$DIR/.env"
  sed -i "s|^TARGET_REPO_PATH=.*|TARGET_REPO_PATH=${TARGET}|" "$DIR/.env"

  echo ""
  echo ".env configured. You can edit $DIR/.env to change settings later."
}

# ── Commands ─────────────────────────────────────────────

cmd_start() {
  if _is_systemd; then
    echo "systemd service installed — using systemctl"
    sudo systemctl start "$SERVICE_NAME"
    sudo systemctl status "$SERVICE_NAME" --no-pager
  else
    _ensure_venv
    _ensure_env
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Swarm already running (PID $(cat "$PIDFILE"))"
      exit 1
    fi
    echo "Starting swarm orchestrator..."
    nohup "$VENV" -m orchestrator.main >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Started (PID $!, log: $LOGFILE)"
  fi
}

cmd_stop() {
  if _is_systemd; then
    echo "Stopping via systemctl..."
    sudo systemctl stop "$SERVICE_NAME"
    echo "Stopped"
  else
    if [ ! -f "$PIDFILE" ]; then
      echo "No PID file found"
      exit 1
    fi
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
      echo "Stopping swarm (PID $PID)..."
      kill "$PID"
      for i in $(seq 1 30); do
        kill -0 "$PID" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$PID" 2>/dev/null; then
        echo "Force killing..."
        kill -9 "$PID"
      fi
      echo "Stopped"
    else
      echo "Process $PID not running"
    fi
    rm -f "$PIDFILE"
  fi
}

cmd_restart() {
  if _is_systemd; then
    sudo systemctl restart "$SERVICE_NAME"
    sudo systemctl status "$SERVICE_NAME" --no-pager
  else
    cmd_stop || true
    sleep 1
    cmd_start
  fi
}

cmd_status() {
  if _is_systemd; then
    sudo systemctl status "$SERVICE_NAME" --no-pager
  else
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Running (PID $(cat "$PIDFILE"))"
    else
      echo "Not running"
      rm -f "$PIDFILE" 2>/dev/null
    fi
  fi
}

cmd_logs() {
  if _is_systemd; then
    sudo journalctl -u "$SERVICE_NAME" -f
  else
    tail -f "$LOGFILE"
  fi
}

cmd_install() {
  echo "Installing Claude Code Swarm as a systemd service..."
  echo ""

  # Detect current user (the real user, not root)
  REAL_USER="${SUDO_USER:-$(whoami)}"
  REAL_GROUP="$(id -gn "$REAL_USER")"

  # Auto-setup venv and .env if missing
  _ensure_venv
  _ensure_env

  # Generate the service file with correct paths
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Claude Code Agent Swarm Orchestrator
After=network.target

[Service]
Type=simple
User=${REAL_USER}
Group=${REAL_GROUP}
WorkingDirectory=${DIR}
ExecStart=${DIR}/.venv/bin/python -m orchestrator.main
EnvironmentFile=${DIR}/.env
KillSignal=SIGTERM
TimeoutStopSec=60
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=claude-swarm

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME"
  systemctl start "$SERVICE_NAME"

  echo ""
  echo "Installed and started successfully!"
  echo ""
  echo "  Status:   ./run.sh status"
  echo "  Logs:     ./run.sh logs"
  echo "  Restart:  ./run.sh restart"
  echo "  Stop:     ./run.sh stop"
  echo "  Remove:   ./run.sh uninstall"
  echo ""
  systemctl status "$SERVICE_NAME" --no-pager
}

cmd_uninstall() {
  echo "Removing Claude Code Swarm systemd service..."
  if [ -f "$SERVICE_FILE" ]; then
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload
    echo "Service removed"
  else
    echo "Service not installed"
  fi
}

# ── Main ─────────────────────────────────────────────────

case "${1:-help}" in
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  restart)  cmd_restart ;;
  status)   cmd_status ;;
  logs)     cmd_logs ;;
  install)  _require_sudo "$@"; cmd_install ;;
  uninstall) _require_sudo "$@"; cmd_uninstall ;;
  *)
    echo "Claude Code Swarm Orchestrator"
    echo ""
    echo "Usage: $0 {command}"
    echo ""
    echo "Commands:"
    echo "  start      Start the orchestrator"
    echo "  stop       Stop the orchestrator"
    echo "  restart    Restart the orchestrator"
    echo "  status     Show current status"
    echo "  logs       Tail live logs"
    echo "  install    Install as systemd service (auto-start on boot, auto-restart on crash)"
    echo "  uninstall  Remove the systemd service"
    ;;
esac

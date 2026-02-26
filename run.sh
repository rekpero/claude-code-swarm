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

_apt_updated=false
_apt_update() {
  if [ "$_apt_updated" = false ]; then
    apt-get update -qq
    _apt_updated=true
  fi
}

_ensure_deps() {
  echo "Checking system dependencies..."

  # ── Python 3 ──
  if ! command -v python3 &>/dev/null; then
    echo "  Installing python3..."
    _apt_update
    apt-get install -y -qq python3 python3-pip
  fi

  PY_VERSION=$(python3 -c 'import sys; print(sys.version_info.minor)')
  if [ "$PY_VERSION" -lt 10 ]; then
    echo "ERROR: Python 3.10+ required (found 3.${PY_VERSION})"
    exit 1
  fi

  # ── python3-venv ──
  if ! python3 -m ensurepip --version &>/dev/null 2>&1; then
    echo "  Installing python3.${PY_VERSION}-venv..."
    _apt_update
    apt-get install -y -qq "python3.${PY_VERSION}-venv"
  fi

  # ── Node.js (needed for claude CLI) ──
  if ! command -v node &>/dev/null; then
    echo "  Installing Node.js..."
    if ! command -v curl &>/dev/null; then
      _apt_update
      apt-get install -y -qq curl
    fi
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
  fi

  # ── GitHub CLI (gh) ──
  if ! command -v gh &>/dev/null; then
    echo "  Installing GitHub CLI..."
    if ! command -v curl &>/dev/null; then
      _apt_update
      apt-get install -y -qq curl
    fi
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg 2>/dev/null
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list
    apt-get update -qq
    apt-get install -y -qq gh
  fi

  # ── Claude CLI ──
  if ! command -v claude &>/dev/null; then
    echo "  Installing Claude CLI..."
    npm install -g @anthropic-ai/claude-code
  fi

  echo "System dependencies ready"
}

_ensure_venv() {
  if [ ! -f "$DIR/.venv/bin/python" ]; then
    echo "Setting up Python virtual environment..."
    python3 -m venv "$DIR/.venv"
  fi

  # Always ensure deps are installed
  "$DIR/.venv/bin/pip" install --upgrade pip -q 2>/dev/null
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

  # Install all system-level deps, then venv & .env
  _ensure_deps
  _ensure_venv
  _ensure_env

  # Build PATH that includes claude, gh, node, etc.
  SVC_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  # Add node/npm path if installed via nvm
  REAL_HOME=$(eval echo "~${REAL_USER}")
  for p in "$REAL_HOME/.nvm/versions/node"/*/bin /usr/local/lib/nodejs/*/bin; do
    [ -d "$p" ] && SVC_PATH="${p}:${SVC_PATH}"
  done

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
Environment=PATH=${SVC_PATH}
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

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

# ── Commands ─────────────────────────────────────────────

cmd_start() {
  if _is_systemd; then
    echo "systemd service installed — using systemctl"
    sudo systemctl start "$SERVICE_NAME"
    sudo systemctl status "$SERVICE_NAME" --no-pager
  else
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

  # Check prerequisites
  if [ ! -f "$DIR/.env" ]; then
    echo "ERROR: .env file not found at $DIR/.env"
    echo "Copy .env.example to .env and fill in your tokens first."
    exit 1
  fi
  if [ ! -f "$DIR/.venv/bin/python" ]; then
    echo "ERROR: Virtual environment not found at $DIR/.venv"
    echo "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
  fi

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

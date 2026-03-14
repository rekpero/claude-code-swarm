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

  sed -i "s|^CLAUDE_CODE_OAUTH_TOKEN=.*|CLAUDE_CODE_OAUTH_TOKEN=${TOKEN}|" "$DIR/.env"
  sed -i "s|^GH_TOKEN=.*|GH_TOKEN=${GH}|" "$DIR/.env"

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
  cmd_build_ui
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
  cmd_build_ui

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

# ── UI Build ─────────────────────────────────────────────

cmd_build_ui() {
  FRONTEND_DIR="$DIR/frontend"
  if [ ! -d "$FRONTEND_DIR" ]; then
    echo "ERROR: frontend/ directory not found at $FRONTEND_DIR"
    exit 1
  fi
  echo "Building dashboard UI..."
  cd "$FRONTEND_DIR"
  npm install --silent
  npm run build
  echo "Dashboard UI built successfully — output in orchestrator/static/"
}

# ── Skills (powered by skills.sh) ─────────────────────────

# Default skill repos to install. Each entry is "owner/repo".
# Override with SKILL_REPOS in .env (comma-separated).
DEFAULT_SKILL_REPOS=(
  "anthropics/skills"
  "vercel-labs/agent-skills"
)

cmd_install_skills() {
  local global_flag=""
  local repos=()
  local skill_filter=""
  local extra_args=()

  # Parse arguments
  shift  # remove "install-skills" from args
  while [ $# -gt 0 ]; do
    case "$1" in
      --global|-g)
        global_flag="--global"
        shift
        ;;
      --repo|-r)
        repos+=("$2")
        shift 2
        ;;
      --skill|-s)
        skill_filter="$2"
        shift 2
        ;;
      --list|-l)
        # List available skills from default repos
        echo "Listing available skills from default repos..."
        echo ""
        for repo in "${DEFAULT_SKILL_REPOS[@]}"; do
          echo "=== $repo ==="
          npx skills add "$repo" --list 2>&1 | grep -E "^\│\s+(✓\s+)?\S" || true
          echo ""
        done
        echo "Usage:"
        echo "  $0 install-skills                              Install all default skills into target repo"
        echo "  $0 install-skills --global                     Install globally (~/.claude/skills/)"
        echo "  $0 install-skills --repo owner/repo            Install from a specific repo"
        echo "  $0 install-skills --skill frontend-design      Install a specific skill"
        echo "  $0 install-skills --repo owner/repo --list     List skills in a repo"
        echo "  $0 install-skills custom owner/repo [...]      Install from custom repo(s)"
        return 0
        ;;
      --copy)
        extra_args+=("--copy")
        shift
        ;;
      -*)
        echo "Unknown option: $1"
        return 1
        ;;
      *)
        # Positional args treated as repo names
        repos+=("$1")
        shift
        ;;
    esac
  done

  # Default to DEFAULT_SKILL_REPOS if no repos specified
  if [ ${#repos[@]} -eq 0 ]; then
    repos=("${DEFAULT_SKILL_REPOS[@]}")
  fi

  # Always install globally (workspaces are managed via dashboard)
  if [ -z "$global_flag" ]; then
    global_flag="--global"
  fi
  local target_dir=""

  echo "Installing skills from ${#repos[@]} repo(s)..."
  if [ -n "$global_flag" ]; then
    echo "Scope: global (~/.claude/skills/)"
  else
    echo "Scope: target repo ($target_dir)"
  fi
  echo ""

  local failed=0
  for repo in "${repos[@]}"; do
    echo "--- Installing from: $repo ---"

    # Build npx skills add command
    # --copy is default for target repo installs (symlinks break in worktrees)
    local cmd=(npx skills add "$repo" --agent claude-code -y)

    if [ -n "$global_flag" ]; then
      cmd+=("--global")
    else
      cmd+=("--copy")
    fi

    if [ -n "$skill_filter" ]; then
      cmd+=("--skill" "$skill_filter")
    else
      cmd+=("--skill" "*")
    fi

    for arg in "${extra_args[@]}"; do
      cmd+=("$arg")
    done

    # Run in the target directory (or cwd for global)
    if [ -n "$target_dir" ] && [ -z "$global_flag" ]; then
      (cd "$target_dir" && "${cmd[@]}") || {
        echo "WARNING: Failed to install from $repo"
        failed=$((failed + 1))
      }
    else
      "${cmd[@]}" || {
        echo "WARNING: Failed to install from $repo"
        failed=$((failed + 1))
      }
    fi

    echo ""
  done

  if [ $failed -eq 0 ]; then
    echo "All skills installed successfully."
  else
    echo "$failed repo(s) had errors. Check output above."
  fi

  echo ""
  echo "Make sure SKILLS_ENABLED=true is set in .env (default: true)."

  # Show what's installed
  echo ""
  echo "Installed skills:"
  if [ -n "$target_dir" ] && [ -z "$global_flag" ]; then
    (cd "$target_dir" && npx skills list 2>&1) || true
  else
    npx skills list 2>&1 || true
  fi
}

cmd_uninstall_skills() {
  local global_flag=""
  local skill_filter=""

  shift  # remove "uninstall-skills" from args
  while [ $# -gt 0 ]; do
    case "$1" in
      --global|-g)
        global_flag="--global"
        shift
        ;;
      --skill|-s)
        skill_filter="$2"
        shift 2
        ;;
      *)
        skill_filter="$1"
        shift
        ;;
    esac
  done

  local cmd=(npx skills remove --agent claude-code -y --global)
  if [ -n "$skill_filter" ]; then
    cmd+=("--skill" "$skill_filter")
  else
    cmd+=("--skill" "*")
  fi

  "${cmd[@]}" || true

  echo "Done."
}

cmd_list_skills() {
  echo "Installed skills (global: ~/.claude/skills/):"
  echo ""
  npx skills list --global 2>&1 || echo "  (none)"
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
  build-ui) cmd_build_ui ;;
  install-skills)   cmd_install_skills "$@" ;;
  uninstall-skills) cmd_uninstall_skills "$@" ;;
  list-skills)      cmd_list_skills ;;
  *)
    echo "Claude Code Swarm Orchestrator"
    echo ""
    echo "Usage: $0 {command}"
    echo ""
    echo "Commands:"
    echo "  start              Start the orchestrator"
    echo "  stop               Stop the orchestrator"
    echo "  restart            Restart the orchestrator"
    echo "  status             Show current status"
    echo "  logs               Tail live logs"
    echo "  install            Install as systemd service (auto-start on boot, auto-restart on crash)"
    echo "  uninstall          Remove the systemd service"
    echo "  build-ui           Build the React dashboard UI (frontend/ → orchestrator/static/)"
    echo ""
    echo "Skills (powered by skills.sh):"
    echo "  install-skills                           Install default skills into target repo"
    echo "  install-skills --global                  Install globally (~/.claude/skills/)"
    echo "  install-skills --repo owner/repo         Install from a specific GitHub repo"
    echo "  install-skills --skill name              Install a specific skill only"
    echo "  install-skills --list                    List available skills in default repos"
    echo "  list-skills                              Show currently installed skills"
    echo "  uninstall-skills                         Remove all installed skills"
    echo ""
    echo "Default skill repos: ${DEFAULT_SKILL_REPOS[*]}"
    echo "Override with SKILL_REPOS in .env (comma-separated)"
    ;;
esac

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# === Authentication ===
CLAUDE_CODE_OAUTH_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
GH_TOKEN = os.environ.get("GH_TOKEN", "")

# === Repository ===
GITHUB_REPO = os.environ.get("GITHUB_REPO", "owner/repo")
BASE_BRANCH = os.environ.get("BASE_BRANCH", "main")

# === Target Repo Path ===
TARGET_REPO_PATH = Path(os.environ.get("TARGET_REPO_PATH", ".")).resolve()

# === Issue Polling ===
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
ISSUE_LABEL = os.environ.get("ISSUE_LABEL", "agent")
MAX_ISSUE_RETRIES = int(os.environ.get("MAX_ISSUE_RETRIES", "3"))

# Trigger: agents only start when a comment containing this mention is posted on the issue.
# e.g. "@claude-swarm start", "@claude-swarm work on this", etc.
# Set to empty string to disable (pick up issues immediately on label).
TRIGGER_MENTION = os.environ.get("TRIGGER_MENTION", "@claude-swarm")

# === Agent Pool ===
MAX_CONCURRENT_AGENTS = int(os.environ.get("MAX_CONCURRENT_AGENTS", "3"))
AGENT_MAX_TURNS_IMPLEMENT = int(os.environ.get("AGENT_MAX_TURNS_IMPLEMENT", "30"))
AGENT_MAX_TURNS_FIX = int(os.environ.get("AGENT_MAX_TURNS_FIX", "20"))
AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))

# === PR Review Loop ===
PR_POLL_INTERVAL_SECONDS = int(os.environ.get("PR_POLL_INTERVAL_SECONDS", "120"))
MAX_PR_FIX_RETRIES = int(os.environ.get("MAX_PR_FIX_RETRIES", "5"))
CI_WAIT_TIMEOUT_SECONDS = int(os.environ.get("CI_WAIT_TIMEOUT_SECONDS", "600"))

# === Rate Limit Handling ===
# How often (seconds) to check if rate-limited agents can be resumed.
RATE_LIMIT_RETRY_INTERVAL = int(os.environ.get("RATE_LIMIT_RETRY_INTERVAL", "300"))
# Max times we'll resume a single agent after rate limits before giving up.
MAX_RATE_LIMIT_RESUMES = int(os.environ.get("MAX_RATE_LIMIT_RESUMES", "5"))

# === Dashboard ===
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8420"))

# === Paths ===
WORKTREE_DIR = Path(
    os.environ.get(
        "WORKTREE_DIR",
        str(TARGET_REPO_PATH.parent / f"{TARGET_REPO_PATH.name}-worktrees"),
    )
)
DB_PATH = Path(
    os.environ.get(
        "DB_PATH",
        str(Path(__file__).parent / "swarm.db"),
    )
)


def validate_environment() -> list[str]:
    """Validate that all required tools and config are present.
    Returns a list of error messages. Empty list means all good.
    """
    errors: list[str] = []

    # Check required env vars
    if not CLAUDE_CODE_OAUTH_TOKEN:
        errors.append("CLAUDE_CODE_OAUTH_TOKEN is not set")
    if not GH_TOKEN:
        errors.append("GH_TOKEN is not set")
    if GITHUB_REPO == "owner/repo":
        errors.append("GITHUB_REPO is not configured (still default 'owner/repo')")

    # Check TARGET_REPO_PATH
    if not TARGET_REPO_PATH.exists():
        errors.append(f"TARGET_REPO_PATH does not exist: {TARGET_REPO_PATH}")
    elif not (TARGET_REPO_PATH / ".git").exists():
        errors.append(f"TARGET_REPO_PATH is not a git repo: {TARGET_REPO_PATH}")

    # Check claude CLI
    if not shutil.which("claude"):
        errors.append("'claude' CLI not found in PATH")

    # Check gh CLI
    if not shutil.which("gh"):
        errors.append("'gh' CLI not found in PATH")
    else:
        # Verify gh auth works with GH_TOKEN
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "GH_TOKEN": GH_TOKEN},
            )
            if result.returncode != 0:
                errors.append(f"gh auth check failed: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            errors.append("gh auth status timed out")

    # Check git
    if not shutil.which("git"):
        errors.append("'git' not found in PATH")

    return errors


def print_config():
    """Print current configuration (redacting secrets)."""
    print("=== Swarm Configuration ===")
    print(f"  GITHUB_REPO:           {GITHUB_REPO}")
    print(f"  BASE_BRANCH:           {BASE_BRANCH}")
    print(f"  TARGET_REPO_PATH:      {TARGET_REPO_PATH}")
    print(f"  WORKTREE_DIR:          {WORKTREE_DIR}")
    print(f"  DB_PATH:               {DB_PATH}")
    print(f"  POLL_INTERVAL:         {POLL_INTERVAL_SECONDS}s")
    print(f"  ISSUE_LABEL:           {ISSUE_LABEL}")
    print(f"  TRIGGER_MENTION:       {TRIGGER_MENTION or '(disabled — immediate pickup)'}")
    print(f"  MAX_CONCURRENT_AGENTS: {MAX_CONCURRENT_AGENTS}")
    print(f"  MAX_TURNS (implement): {AGENT_MAX_TURNS_IMPLEMENT}")
    print(f"  MAX_TURNS (fix):       {AGENT_MAX_TURNS_FIX}")
    print(f"  AGENT_TIMEOUT:         {AGENT_TIMEOUT_SECONDS}s")
    print(f"  PR_POLL_INTERVAL:      {PR_POLL_INTERVAL_SECONDS}s")
    print(f"  MAX_PR_FIX_RETRIES:    {MAX_PR_FIX_RETRIES}")
    print(f"  RATE_LIMIT_RETRY:      {RATE_LIMIT_RETRY_INTERVAL}s")
    print(f"  MAX_RATE_RESUMES:      {MAX_RATE_LIMIT_RESUMES}")
    print(f"  DASHBOARD_PORT:        {DASHBOARD_PORT}")
    token_preview = CLAUDE_CODE_OAUTH_TOKEN[:12] + "..." if CLAUDE_CODE_OAUTH_TOKEN else "(not set)"
    gh_preview = GH_TOKEN[:8] + "..." if GH_TOKEN else "(not set)"
    print(f"  CLAUDE_TOKEN:          {token_preview}")
    print(f"  GH_TOKEN:              {gh_preview}")
    print("===========================")

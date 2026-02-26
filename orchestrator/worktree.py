import logging
import subprocess
from pathlib import Path

from orchestrator.config import BASE_BRANCH, TARGET_REPO_PATH, WORKTREE_DIR

logger = logging.getLogger(__name__)


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command against the target repo."""
    cmd = ["git", "-C", str(TARGET_REPO_PATH)] + list(args)
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
        )
    return result


def ensure_repo_updated():
    """Fetch and pull latest changes from origin."""
    logger.info("Updating target repo at %s", TARGET_REPO_PATH)
    _run_git("fetch", "origin")
    _run_git("pull", "origin", BASE_BRANCH, check=False)


def create_worktree(issue_number: int, base_branch: str | None = None) -> str:
    """Create a git worktree for an issue. Returns the worktree path."""
    base = base_branch or BASE_BRANCH
    worktree_path = WORKTREE_DIR / f"issue-{issue_number}"
    branch_name = f"fix/issue-{issue_number}"

    WORKTREE_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up stale worktree if it exists
    if worktree_path.exists():
        logger.warning("Worktree already exists at %s, removing first", worktree_path)
        cleanup_worktree(str(worktree_path))

    logger.info("Creating worktree: %s (branch: %s)", worktree_path, branch_name)
    _run_git(
        "worktree", "add", str(worktree_path), "-b", branch_name, base
    )
    return str(worktree_path)


def create_worktree_for_pr(pr_number: int, branch_name: str) -> str:
    """Create a git worktree for fixing PR review comments. Returns the path."""
    worktree_path = WORKTREE_DIR / f"pr-fix-{pr_number}"

    WORKTREE_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up stale worktree if it exists
    if worktree_path.exists():
        logger.warning("Worktree already exists at %s, removing first", worktree_path)
        cleanup_worktree(str(worktree_path))

    # Fetch the branch first
    _run_git("fetch", "origin", branch_name, check=False)

    logger.info("Creating worktree for PR fix: %s (branch: %s)", worktree_path, branch_name)
    _run_git("worktree", "add", str(worktree_path), branch_name)
    return str(worktree_path)


def cleanup_worktree(path: str):
    """Remove a git worktree."""
    logger.info("Cleaning up worktree: %s", path)
    _run_git("worktree", "remove", path, "--force", check=False)


def list_worktrees() -> list[dict]:
    """List all active worktrees."""
    result = _run_git("worktree", "list", "--porcelain")
    worktrees = []
    current: dict = {}
    for line in result.stdout.strip().split("\n"):
        if not line:
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]
        elif line == "bare":
            current["bare"] = True
    if current:
        worktrees.append(current)
    return worktrees


def cleanup_all_worktrees():
    """Remove all worktrees in WORKTREE_DIR. Used during shutdown."""
    if not WORKTREE_DIR.exists():
        return
    for child in WORKTREE_DIR.iterdir():
        if child.is_dir():
            cleanup_worktree(str(child))
    logger.info("All worktrees cleaned up")

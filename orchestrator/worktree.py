import logging
import subprocess
from pathlib import Path

from orchestrator.config import BASE_BRANCH, TARGET_REPO_PATH, WORKTREE_DIR

logger = logging.getLogger(__name__)


def _run_git(*args: str, repo_path: Path | str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command against a repo."""
    target = str(repo_path) if repo_path else str(TARGET_REPO_PATH)
    cmd = ["git", "-C", target] + list(args)
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
        )
    return result


def ensure_repo_updated(repo_path: Path | str | None = None, base_branch: str | None = None):
    """Fetch and pull latest changes from origin."""
    target = repo_path or TARGET_REPO_PATH
    branch = base_branch or BASE_BRANCH
    logger.info("Updating target repo at %s", target)
    _run_git("fetch", "origin", repo_path=target)
    _run_git("pull", "origin", branch, repo_path=target, check=False)


def create_worktree(
    issue_number: int,
    repo_path: Path | str | None = None,
    worktree_dir: Path | str | None = None,
    base_branch: str | None = None,
) -> str:
    """Create a git worktree for an issue. Returns the worktree path."""
    target = repo_path or TARGET_REPO_PATH
    wt_dir = Path(worktree_dir) if worktree_dir else WORKTREE_DIR
    base = base_branch or BASE_BRANCH
    worktree_path = wt_dir / f"issue-{issue_number}"
    branch_name = f"fix/issue-{issue_number}"

    wt_dir.mkdir(parents=True, exist_ok=True)

    # Clean up stale worktree if it exists
    if worktree_path.exists():
        logger.warning("Worktree already exists at %s, removing first", worktree_path)
        cleanup_worktree(str(worktree_path), repo_path=target)

    # Delete stale branch if it exists (leftover from a previous failed run)
    branch_check = _run_git("branch", "--list", branch_name, repo_path=target, check=False)
    if branch_name in branch_check.stdout:
        logger.warning("Deleting stale branch %s", branch_name)
        _run_git("branch", "-D", branch_name, repo_path=target, check=False)

    logger.info("Creating worktree: %s (branch: %s)", worktree_path, branch_name)
    _run_git(
        "worktree", "add", str(worktree_path), "-b", branch_name, base,
        repo_path=target,
    )
    return str(worktree_path)


def create_worktree_for_pr(
    pr_number: int,
    branch_name: str,
    repo_path: Path | str | None = None,
    worktree_dir: Path | str | None = None,
) -> str:
    """Create a git worktree for fixing PR review comments. Returns the path."""
    target = repo_path or TARGET_REPO_PATH
    wt_dir = Path(worktree_dir) if worktree_dir else WORKTREE_DIR
    worktree_path = wt_dir / f"pr-fix-{pr_number}"

    wt_dir.mkdir(parents=True, exist_ok=True)

    # Clean up stale worktree if it exists
    if worktree_path.exists():
        logger.warning("Worktree already exists at %s, removing first", worktree_path)
        cleanup_worktree(str(worktree_path), repo_path=target)

    # Fetch the branch first
    _run_git("fetch", "origin", branch_name, repo_path=target, check=False)

    logger.info("Creating worktree for PR fix: %s (branch: %s)", worktree_path, branch_name)
    _run_git("worktree", "add", str(worktree_path), branch_name, repo_path=target)

    # Reset to latest remote commit — an external push may have landed since the
    # local branch was last checked out.
    subprocess.run(
        ["git", "-C", str(worktree_path), "reset", "--hard", f"origin/{branch_name}"],
        capture_output=True, text=True, timeout=30,
    )
    logger.info("Worktree reset to origin/%s", branch_name)

    return str(worktree_path)


def cleanup_worktree(path: str, repo_path: Path | str | None = None):
    """Remove a git worktree."""
    logger.info("Cleaning up worktree: %s", path)
    _run_git("worktree", "remove", path, "--force", repo_path=repo_path, check=False)


def list_worktrees(repo_path: Path | str | None = None) -> list[dict]:
    """List all active worktrees."""
    result = _run_git("worktree", "list", "--porcelain", repo_path=repo_path)
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


def cleanup_all_worktrees(worktree_dir: Path | str | None = None, repo_path: Path | str | None = None):
    """Remove all worktrees in a directory. Used during shutdown."""
    wt_dir = Path(worktree_dir) if worktree_dir else WORKTREE_DIR
    if not wt_dir.exists():
        return
    for child in wt_dir.iterdir():
        if child.is_dir():
            cleanup_worktree(str(child), repo_path=repo_path)
    logger.info("All worktrees cleaned up in %s", wt_dir)

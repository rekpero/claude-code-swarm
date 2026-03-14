import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_git(*args: str, repo_path: Path | str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command against a repo."""
    target = str(repo_path)
    cmd = ["git", "-C", target] + list(args)
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if check and result.returncode != 0:
        raise RuntimeError(
            f"git command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
        )
    return result


def ensure_repo_updated(repo_path: Path | str, base_branch: str = "main"):
    """Fetch and pull latest changes from origin."""
    target = repo_path
    branch = base_branch
    logger.info("Updating target repo at %s", target)
    _run_git("fetch", "origin", repo_path=target)
    # Ensure we're on the base branch (not a stale feature branch)
    _run_git("checkout", branch, repo_path=target, check=False)
    _run_git("pull", "origin", branch, repo_path=target, check=False)


def get_sync_status(repo_path: Path | str, base_branch: str = "main") -> dict:
    """Check if the local base branch is in sync with origin.

    Returns a dict with:
      - synced (bool): True if local HEAD matches remote HEAD
      - local_sha (str): short local commit hash
      - remote_sha (str): short remote commit hash
      - behind (int): commits behind remote
      - ahead (int): commits ahead of remote
    """
    target = repo_path
    # Fetch latest refs from remote (silent, no merge)
    _run_git("fetch", "origin", repo_path=target, check=False)

    local = _run_git("rev-parse", "--short", base_branch, repo_path=target, check=False)
    remote = _run_git("rev-parse", "--short", f"origin/{base_branch}", repo_path=target, check=False)

    local_sha = local.stdout.strip() if local.returncode == 0 else ""
    remote_sha = remote.stdout.strip() if remote.returncode == 0 else ""

    behind = 0
    ahead = 0
    if local_sha and remote_sha:
        rev_list = _run_git(
            "rev-list", "--left-right", "--count",
            f"{base_branch}...origin/{base_branch}",
            repo_path=target, check=False,
        )
        if rev_list.returncode == 0:
            parts = rev_list.stdout.strip().split()
            if len(parts) == 2:
                ahead = int(parts[0])
                behind = int(parts[1])

    return {
        "synced": local_sha == remote_sha and local_sha != "",
        "local_sha": local_sha,
        "remote_sha": remote_sha,
        "behind": behind,
        "ahead": ahead,
    }


def create_worktree(
    issue_number: int,
    repo_path: Path | str,
    worktree_dir: Path | str,
    base_branch: str = "main",
) -> str:
    """Create a git worktree for an issue. Returns the worktree path."""
    target = repo_path
    wt_dir = Path(worktree_dir)
    base = base_branch
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
        "worktree", "add", "--force", str(worktree_path), "-b", branch_name, base,
        repo_path=target,
    )
    return str(worktree_path)


def create_worktree_for_pr(
    pr_number: int,
    branch_name: str,
    repo_path: Path | str,
    worktree_dir: Path | str,
) -> str:
    """Create a git worktree for fixing PR review comments. Returns the path."""
    target = repo_path
    wt_dir = Path(worktree_dir)
    worktree_path = wt_dir / f"pr-fix-{pr_number}"

    wt_dir.mkdir(parents=True, exist_ok=True)

    # Clean up stale worktree if it exists
    if worktree_path.exists():
        logger.warning("Worktree already exists at %s, removing first", worktree_path)
        cleanup_worktree(str(worktree_path), repo_path=target)

    # Fetch the branch first
    _run_git("fetch", "origin", branch_name, repo_path=target, check=False)

    logger.info("Creating worktree for PR fix: %s (branch: %s)", worktree_path, branch_name)
    _run_git("worktree", "add", "--force", str(worktree_path), branch_name, repo_path=target)

    # Reset to latest remote commit — an external push may have landed since the
    # local branch was last checked out.
    subprocess.run(
        ["git", "-C", str(worktree_path), "reset", "--hard", f"origin/{branch_name}"],
        capture_output=True, text=True, timeout=30,
    )
    logger.info("Worktree reset to origin/%s", branch_name)

    return str(worktree_path)


def copy_env_files_to_worktree(
    worktree_path: str,
    repo_path: str,
    workspace_id: str | None = None,
) -> None:
    """Copy .env files from the source repo into the worktree.

    Uses two strategies:
    1. Copy any .env* files found on disk in the source repo.
    2. If a workspace_id is provided, also write any DB-managed env files
       that don't already exist on disk (e.g. user added them via the dashboard
       but they were cleaned up from the source repo).
    """
    src = Path(repo_path)
    dst = Path(worktree_path)
    copied: list[str] = []

    # Strategy 1: copy .env* files from the source repo root and subdirs
    for env_file in src.rglob(".env*"):
        # Skip directories, .envrc, and files inside node_modules / .git
        rel = env_file.relative_to(src)
        parts = rel.parts
        if env_file.is_dir():
            continue
        if any(p.startswith(".git") or p == "node_modules" for p in parts):
            continue

        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(env_file), str(target))
        copied.append(str(rel))

    # Strategy 2: write DB-managed env files that weren't already on disk
    if workspace_id:
        from orchestrator import db

        for env_file_path in db.get_workspace_env_files(workspace_id):
            if env_file_path in copied:
                continue
            env_dict = db.get_workspace_env(workspace_id, env_file_path)
            if not env_dict:
                continue
            target = dst / env_file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            for key, value in sorted(env_dict.items()):
                if " " in value or '"' in value or "'" in value or "\n" in value:
                    value = f'"{value}"'
                lines.append(f"{key}={value}")
            target.write_text("\n".join(lines) + "\n")
            copied.append(env_file_path)

    if copied:
        logger.info("Copied %d env file(s) to worktree %s: %s", len(copied), worktree_path, ", ".join(copied))


def cleanup_worktree(path: str, repo_path: Path | str | None = None):
    """Remove a git worktree, force-deleting the directory if git can't."""
    logger.info("Cleaning up worktree: %s", path)
    _run_git("worktree", "remove", path, "--force", repo_path=repo_path, check=False)
    # If the directory still exists (locked files, etc.), nuke it
    wt = Path(path)
    if wt.exists():
        logger.warning("Worktree directory still exists after git remove, force-deleting: %s", path)
        shutil.rmtree(str(wt), ignore_errors=True)
    # Prune stale worktree references so git doesn't complain
    if repo_path:
        _run_git("worktree", "prune", repo_path=repo_path, check=False)


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


def cleanup_all_worktrees(worktree_dir: Path | str, repo_path: Path | str | None = None):
    """Remove all worktrees in a directory. Used during shutdown."""
    wt_dir = Path(worktree_dir)
    if not wt_dir.exists():
        return
    for child in wt_dir.iterdir():
        if child.is_dir():
            cleanup_worktree(str(child), repo_path=repo_path)
    logger.info("All worktrees cleaned up in %s", wt_dir)

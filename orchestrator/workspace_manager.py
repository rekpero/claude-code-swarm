"""Manages workspace lifecycle — clone, detect structure, env vars."""

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

from orchestrator import db
from orchestrator.config import GH_TOKEN, WORKSPACES_DIR

logger = logging.getLogger(__name__)


def _parse_github_repo(repo_url: str) -> str:
    """Extract 'owner/repo' from a GitHub URL or shorthand."""
    # Handle: https://github.com/owner/repo.git, git@github.com:owner/repo.git, owner/repo
    url = repo_url.strip().rstrip("/")
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", url)
    if match:
        return match.group(1)
    # Already in owner/repo format
    if re.match(r"^[^/]+/[^/]+$", url):
        return url
    raise ValueError(f"Cannot parse GitHub repo from: {repo_url}")


def _normalize_repo_url(repo_url: str) -> str:
    """Ensure we have a cloneable HTTPS URL."""
    url = repo_url.strip().rstrip("/")
    if url.startswith("git@"):
        # Convert git@github.com:owner/repo.git -> https://github.com/owner/repo.git
        url = url.replace(":", "/").replace("git@", "https://")
    if not url.startswith("http"):
        url = f"https://github.com/{url}"
    if not url.endswith(".git"):
        url += ".git"
    return url


def create_workspace(
    repo_url: str,
    name: str | None = None,
    base_branch: str = "main",
) -> dict:
    """Create a new workspace — parse URL, insert DB record, start cloning."""
    github_repo = _parse_github_repo(repo_url)
    normalized_url = _normalize_repo_url(repo_url)

    if not name:
        name = github_repo.split("/")[-1]

    workspace_id = str(uuid.uuid4())[:8]
    local_path = str(WORKSPACES_DIR / name)

    WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)

    db.create_workspace(
        workspace_id=workspace_id,
        name=name,
        github_repo=github_repo,
        repo_url=normalized_url,
        local_path=local_path,
        base_branch=base_branch,
        status="cloning",
    )

    # Clone in background thread
    threading.Thread(
        target=_clone_repo_thread,
        args=(workspace_id, normalized_url, local_path),
        daemon=True,
        name=f"clone-{workspace_id}",
    ).start()

    return db.get_workspace(workspace_id)


def _clone_repo_thread(workspace_id: str, repo_url: str, local_path: str):
    """Clone a repo in background and update workspace status."""
    try:
        logger.info("Cloning %s to %s", repo_url, local_path)

        if Path(local_path).exists():
            logger.warning("Path %s already exists, removing first", local_path)
            shutil.rmtree(local_path)

        # Embed GH_TOKEN in the clone URL for authenticated HTTPS access
        clone_url = repo_url
        if GH_TOKEN and clone_url.startswith("https://"):
            clone_url = clone_url.replace("https://", f"https://x-access-token:{GH_TOKEN}@")

        env = {**os.environ, "GH_TOKEN": GH_TOKEN}
        result = subprocess.run(
            ["git", "clone", clone_url, local_path],
            capture_output=True, text=True, timeout=600, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr}")

        # Reset the remote URL to the original (non-token) URL so we don't
        # persist credentials in .git/config
        if clone_url != repo_url:
            subprocess.run(
                ["git", "-C", local_path, "remote", "set-url", "origin", repo_url],
                capture_output=True, text=True, timeout=30,
            )
            # Configure git to use GH_TOKEN via credential helper for future operations
            subprocess.run(
                ["git", "-C", local_path, "config", "credential.helper",
                 f"!f() {{ echo \"username=x-access-token\"; echo \"password={GH_TOKEN}\"; }}; f"],
                capture_output=True, text=True, timeout=10,
            )

        logger.info("Clone complete for workspace %s", workspace_id)

        # Detect repo structure
        structure = detect_repo_structure(local_path)
        db.update_workspace(
            workspace_id,
            status="active",
            is_monorepo=1 if structure["is_monorepo"] else 0,
            structure_json=json.dumps(structure),
        )
        logger.info("Workspace %s is active (monorepo=%s)", workspace_id, structure["is_monorepo"])

    except Exception as e:
        logger.error("Failed to clone for workspace %s: %s", workspace_id, e)
        db.update_workspace(workspace_id, status="error")


def update_workspace(workspace_id: str, **kwargs) -> dict | None:
    """Update workspace details. If repo_url changes, re-clone."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return None

    repo_url_changed = False
    if "repo_url" in kwargs and kwargs["repo_url"] != workspace["repo_url"]:
        repo_url_changed = True
        kwargs["repo_url"] = _normalize_repo_url(kwargs["repo_url"])
        kwargs["github_repo"] = _parse_github_repo(kwargs["repo_url"])

    if "name" in kwargs and kwargs["name"] != workspace["name"]:
        new_path = str(WORKSPACES_DIR / kwargs["name"])
        kwargs["local_path"] = new_path

    db.update_workspace(workspace_id, **kwargs)

    if repo_url_changed:
        updated = db.get_workspace(workspace_id)
        db.update_workspace(workspace_id, status="cloning")
        threading.Thread(
            target=_clone_repo_thread,
            args=(workspace_id, updated["repo_url"], updated["local_path"]),
            daemon=True,
        ).start()

    return db.get_workspace(workspace_id)


def delete_workspace(workspace_id: str) -> bool:
    """Delete a workspace — remove clone, worktrees, and all DB records."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return False

    local_path = workspace["local_path"]

    # Clean up worktrees directory
    worktree_dir = local_path + "-worktrees"
    if Path(worktree_dir).exists():
        shutil.rmtree(worktree_dir, ignore_errors=True)

    # Clean up the clone
    if Path(local_path).exists():
        shutil.rmtree(local_path, ignore_errors=True)

    # Delete all DB records
    db.delete_workspace(workspace_id)
    logger.info("Deleted workspace %s (%s)", workspace_id, workspace["name"])
    return True


def detect_repo_structure(local_path: str) -> dict:
    """Scan a cloned repo to detect monorepo structure and env files."""
    root = Path(local_path)
    result = {
        "is_monorepo": False,
        "packages": [],
        "env_files": [],
    }

    # Monorepo detection signals
    monorepo_configs = [
        "pnpm-workspace.yaml",
        "lerna.json",
        "turbo.json",
        "nx.json",
    ]

    for config_file in monorepo_configs:
        if (root / config_file).exists():
            result["is_monorepo"] = True
            break

    # Check package.json for workspaces field
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            with open(pkg_json) as f:
                pkg = json.load(f)
            if "workspaces" in pkg:
                result["is_monorepo"] = True
        except (json.JSONDecodeError, IOError):
            pass

    # Detect packages/apps directories (standard monorepo layout)
    package_dirs = ["packages", "apps", "services", "libs", "modules"]
    for pkg_dir_name in package_dirs:
        pkg_dir = root / pkg_dir_name
        if pkg_dir.is_dir():
            for child in sorted(pkg_dir.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    rel_path = str(child.relative_to(root))
                    result["packages"].append({"name": child.name, "path": rel_path})
            if result["packages"]:
                result["is_monorepo"] = True

    # Detect top-level sub-projects (non-standard monorepo layout)
    # If there are multiple top-level dirs with their own package.json, Dockerfile,
    # Cargo.toml, go.mod, etc., treat the repo as a monorepo.
    if not result["is_monorepo"]:
        project_markers = ["package.json", "Dockerfile", "Cargo.toml", "go.mod", "pyproject.toml", "pom.xml", "build.gradle"]
        skip_dirs = {"node_modules", ".git", ".github", ".vscode", "__pycache__", "dist", "build", "target", ".next", "coverage"}
        sub_projects = []
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name in skip_dirs:
                continue
            for marker in project_markers:
                if (child / marker).exists():
                    sub_projects.append({"name": child.name, "path": child.name})
                    break
        if len(sub_projects) >= 2:
            result["is_monorepo"] = True
            result["packages"].extend(sub_projects)

    # Find all .env* files in the repo
    env_patterns = [".env", ".env.example", ".env.local", ".env.development", ".env.production", ".env.test"]

    def scan_env_files(directory: Path, depth: int = 0):
        if depth > 3:  # Don't recurse too deep
            return
        for pattern in env_patterns:
            env_path = directory / pattern
            if env_path.is_file():
                rel_path = str(env_path.relative_to(root))
                keys = _read_env_keys(env_path)
                result["env_files"].append({
                    "path": rel_path,
                    "exists": True,
                    "keys": keys,
                })

    # Scan root
    scan_env_files(root)

    # Scan package directories
    for pkg in result["packages"]:
        scan_env_files(root / pkg["path"], depth=1)

    return result


def _read_env_keys(env_path: Path) -> list[str]:
    """Read keys from an .env file (not values for security)."""
    keys = []
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key = line.split("=", 1)[0].strip()
                    if key:
                        keys.append(key)
    except IOError:
        pass
    return keys


def discover_existing_env_files(workspace_id: str) -> list[dict]:
    """Scan workspace repo for existing .env* files with masked values."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return []

    root = Path(workspace["local_path"])
    if not root.exists():
        return []

    structure = detect_repo_structure(str(root))
    return structure["env_files"]


def save_env_vars(workspace_id: str, env_dict: dict[str, str], env_file: str = ".env"):
    """Save env vars to DB and write to disk."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        raise ValueError(f"Workspace {workspace_id} not found")

    # Save to DB
    db.save_workspace_env_bulk(workspace_id, env_dict, env_file)

    # Write to disk
    _write_env_file_to_disk(workspace_id, workspace["local_path"], env_file, env_dict)


def get_env_vars(workspace_id: str, env_file: str = ".env") -> dict[str, str]:
    """Get env vars for a workspace with disk sync.

    If the disk file has been modified since the last sync, re-imports from disk.
    If DB has nothing for this file, falls back to reading from disk.
    """
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return db.get_workspace_env(workspace_id, env_file)

    file_path = Path(workspace["local_path"]) / env_file

    # Check if disk file is newer than our last sync
    if file_path.exists():
        disk_mtime = file_path.stat().st_mtime
        last_synced_mtime = db.get_env_sync_mtime(workspace_id, env_file)

        if last_synced_mtime is None or disk_mtime > last_synced_mtime:
            # Disk is newer (or never synced) — re-import from disk
            logger.info("Env file %s changed on disk, re-syncing for workspace %s", env_file, workspace_id)
            return load_env_from_disk(workspace_id, env_file)

    # DB is up to date
    env_dict = db.get_workspace_env(workspace_id, env_file)
    if env_dict:
        return env_dict

    # DB empty, file doesn't exist — nothing to return
    return {}


def get_all_env_files(workspace_id: str) -> list[str]:
    """Get all managed env file paths for a workspace."""
    return db.get_workspace_env_files(workspace_id)


def _write_env_file_to_disk(workspace_id: str, local_path: str, env_file: str, env_dict: dict[str, str]):
    """Write env vars to a .env file on disk and record the mtime."""
    file_path = Path(local_path) / env_file
    file_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for key, value in sorted(env_dict.items()):
        # Quote values containing spaces or special chars
        if " " in value or '"' in value or "'" in value or "\n" in value:
            value = f'"{value}"'
        lines.append(f"{key}={value}")

    file_path.write_text("\n".join(lines) + "\n")
    logger.info("Wrote %d env vars to %s", len(env_dict), file_path)

    # Record mtime so get_env_vars doesn't think disk changed
    db.set_env_sync_mtime(workspace_id, env_file, file_path.stat().st_mtime)


def _parse_env_file(file_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict."""
    env_dict = {}
    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    env_dict[key] = value
    return env_dict


def load_env_from_disk(workspace_id: str, env_file: str = ".env") -> dict[str, str]:
    """Load env vars from an existing .env file on disk into DB and record sync mtime."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return {}

    file_path = Path(workspace["local_path"]) / env_file
    if not file_path.exists():
        return {}

    env_dict = _parse_env_file(file_path)

    # Save to DB and record sync mtime
    db.save_workspace_env_bulk(workspace_id, env_dict, env_file)
    db.set_env_sync_mtime(workspace_id, env_file, file_path.stat().st_mtime)

    return env_dict



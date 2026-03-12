"""Polls GitHub for open issues labeled for automation."""

import json
import logging
import os
import subprocess

from orchestrator import db
from orchestrator.config import GH_TOKEN, ISSUE_LABEL, MAX_ISSUE_RETRIES, TRIGGER_MENTION

logger = logging.getLogger(__name__)


def _run_gh(*args: str) -> subprocess.CompletedProcess:
    """Run a gh CLI command with GH_TOKEN in the environment."""
    cmd = ["gh"] + list(args)
    logger.debug("Running: %s", " ".join(cmd))
    env = {**os.environ, "GH_TOKEN": GH_TOKEN}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"gh command failed: {' '.join(cmd)}\nstderr: {result.stderr}")
    return result


def _find_open_pr_for_issue(issue_number: int, github_repo: str | None = None) -> int | None:
    """Check GitHub for an existing open PR that references this issue."""
    repo = github_repo
    branch_name = f"fix/issue-{issue_number}"
    try:
        result = _run_gh(
            "pr", "list",
            "--repo", repo,
            "--head", branch_name,
            "--state", "open",
            "--json", "number",
            "--limit", "1",
        )
        prs = json.loads(result.stdout) if result.stdout.strip() else []
        if prs:
            pr_num = prs[0]["number"]
            logger.info("Found existing open PR #%d for issue #%d (branch %s)", pr_num, issue_number, branch_name)
            return pr_num
    except Exception as e:
        logger.warning("Failed to check for existing PR for issue #%d: %s", issue_number, e)

    return None


def _issue_has_trigger(issue_number: int, github_repo: str | None = None) -> bool:
    """Check if an issue has a comment containing the trigger mention."""
    if not TRIGGER_MENTION:
        return True  # Trigger disabled — all labeled issues are eligible

    repo = github_repo
    try:
        result = _run_gh(
            "issue", "view", str(issue_number),
            "--repo", repo,
            "--json", "comments",
        )
        data = json.loads(result.stdout) if result.stdout.strip() else {}
        comments = data.get("comments", [])

        trigger_lower = TRIGGER_MENTION.lower()
        for comment in comments:
            body = (comment.get("body") or "").lower()
            if trigger_lower in body:
                logger.info("Issue #%d has trigger comment containing '%s'", issue_number, TRIGGER_MENTION)
                return True

        logger.debug("Issue #%d has no trigger comment (checked %d comments)", issue_number, len(comments))
        return False

    except Exception as e:
        logger.warning("Failed to check comments for issue #%d: %s", issue_number, e)
        return False


def poll_issues(github_repo: str | None = None, workspace_id: str | None = None) -> list[dict]:
    """Poll GitHub for new issues that need agent dispatch.

    Returns a list of issue dicts ready for dispatch. Each dict includes a
    'workspace_id' key for tracking.
    """
    repo = github_repo
    logger.info("Polling issues for repo %s with label '%s'", repo, ISSUE_LABEL)

    result = _run_gh(
        "issue", "list",
        "--repo", repo,
        "--label", ISSUE_LABEL,
        "--state", "open",
        "--json", "number,title,labels,body",
        "--limit", "50",
    )

    issues = json.loads(result.stdout) if result.stdout.strip() else []
    logger.info("Found %d open issues with label '%s' in %s", len(issues), ISSUE_LABEL, repo)

    ready = []
    for issue in issues:
        issue_number = issue["number"]
        title = issue["title"]

        # Check if we're already tracking this issue
        existing = db.get_issue(issue_number, workspace_id=workspace_id)

        if existing is None:
            # New issue — check if there's already an open PR for it
            existing_pr = _find_open_pr_for_issue(issue_number, github_repo=repo)

            if existing_pr:
                # PR already exists — seed as pr_created so PR monitor picks it up
                db.upsert_issue(issue_number, title, status="pr_created", workspace_id=workspace_id)
                db.update_issue(issue_number, workspace_id=workspace_id, pr_number=existing_pr)
                logger.info(
                    "Issue #%d already has open PR #%d — seeded as pr_created for monitoring",
                    issue_number, existing_pr,
                )
                continue

            # No existing PR — add to DB and dispatch if triggered
            db.upsert_issue(issue_number, title, status="pending", workspace_id=workspace_id)

            if _issue_has_trigger(issue_number, github_repo=repo):
                issue["workspace_id"] = workspace_id
                ready.append(issue)
                logger.info("New issue triggered: #%d — %s", issue_number, title)
            else:
                logger.info("New issue discovered but not triggered yet: #%d — %s", issue_number, title)

        elif existing["status"] == "pending":
            if existing["attempts"] >= MAX_ISSUE_RETRIES:
                logger.warning(
                    "Issue #%d exceeded max retries (%d), skipping",
                    issue_number, MAX_ISSUE_RETRIES,
                )
                continue

            # Check trigger on each poll (someone may have commented since last check)
            if _issue_has_trigger(issue_number, github_repo=repo):
                issue["workspace_id"] = workspace_id
                ready.append(issue)
            else:
                logger.debug("Issue #%d still waiting for trigger comment", issue_number)

        elif existing["status"] in ("in_progress", "pr_created"):
            logger.debug("Issue #%d already %s, skipping", issue_number, existing["status"])

        elif existing["status"] == "needs_human":
            logger.debug("Issue #%d needs human intervention, skipping", issue_number)

        elif existing["status"] == "resolved":
            logger.debug("Issue #%d already resolved (PR merged), skipping", issue_number)

    logger.info("%d issues ready for dispatch", len(ready))
    return ready

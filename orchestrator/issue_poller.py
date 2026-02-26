"""Polls GitHub for open issues labeled for automation."""

import json
import logging
import os
import subprocess

from orchestrator import db
from orchestrator.config import GH_TOKEN, GITHUB_REPO, ISSUE_LABEL, MAX_ISSUE_RETRIES, TRIGGER_MENTION

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


def _find_open_pr_for_issue(issue_number: int) -> int | None:
    """Check GitHub for an existing open PR that references this issue.

    Looks for PRs with a branch named 'fix/issue-{N}' or whose body contains
    'Closes #{N}' / 'Fixes #{N}'.  Returns the PR number if found, else None.
    """
    branch_name = f"fix/issue-{issue_number}"
    try:
        result = _run_gh(
            "pr", "list",
            "--repo", GITHUB_REPO,
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


def _issue_has_trigger(issue_number: int) -> bool:
    """Check if an issue has a comment containing the trigger mention.

    Looks for any comment whose body contains TRIGGER_MENTION (case-insensitive).
    Examples that match (with default @claude-swarm):
      - "@claude-swarm start"
      - "@claude-swarm work on this"
      - "Hey @claude-swarm please start this"
    """
    if not TRIGGER_MENTION:
        return True  # Trigger disabled — all labeled issues are eligible

    try:
        result = _run_gh(
            "issue", "view", str(issue_number),
            "--repo", GITHUB_REPO,
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


def poll_issues() -> list[dict]:
    """Poll GitHub for new issues that need agent dispatch.

    Returns a list of issue dicts ready for dispatch. An issue is ready when:
    1. It has the configured label (e.g. "agent")
    2. It has a comment containing the trigger mention (e.g. "@claude-swarm start")
    3. It hasn't exceeded the retry limit
    4. It's not already being worked on
    """
    logger.info("Polling issues for repo %s with label '%s'", GITHUB_REPO, ISSUE_LABEL)

    result = _run_gh(
        "issue", "list",
        "--repo", GITHUB_REPO,
        "--label", ISSUE_LABEL,
        "--state", "open",
        "--json", "number,title,labels,body",
        "--limit", "50",
    )

    issues = json.loads(result.stdout) if result.stdout.strip() else []
    logger.info("Found %d open issues with label '%s'", len(issues), ISSUE_LABEL)

    ready = []
    for issue in issues:
        issue_number = issue["number"]
        title = issue["title"]

        # Check if we're already tracking this issue
        existing = db.get_issue(issue_number)

        if existing is None:
            # New issue — check if there's already an open PR for it
            existing_pr = _find_open_pr_for_issue(issue_number)

            if existing_pr:
                # PR already exists — seed as pr_created so PR monitor picks it up
                db.upsert_issue(issue_number, title, status="pr_created")
                db.update_issue(issue_number, pr_number=existing_pr)
                logger.info(
                    "Issue #%d already has open PR #%d — seeded as pr_created for monitoring",
                    issue_number, existing_pr,
                )
                continue

            # No existing PR — add to DB and dispatch if triggered
            db.upsert_issue(issue_number, title, status="pending")

            if _issue_has_trigger(issue_number):
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
            if _issue_has_trigger(issue_number):
                ready.append(issue)
            else:
                logger.debug("Issue #%d still waiting for trigger comment", issue_number)

        elif existing["status"] in ("in_progress", "pr_created"):
            logger.debug("Issue #%d already %s, skipping", issue_number, existing["status"])

        elif existing["status"] == "needs_human":
            logger.debug("Issue #%d needs human intervention, skipping", issue_number)

        elif existing["status"] == "resolved":
            # Check if the PR is still open — it may have been prematurely resolved
            # before CI/BugBot had a chance to run.
            existing_pr = existing.get("pr_number")
            if existing_pr:
                open_pr = _find_open_pr_for_issue(issue_number)
                if open_pr:
                    logger.warning(
                        "Issue #%d is marked resolved but PR #%d is still open — "
                        "resetting to pr_created for monitoring",
                        issue_number, open_pr,
                    )
                    db.update_issue(issue_number, status="pr_created", pr_number=open_pr)
                    continue
            logger.debug("Issue #%d already resolved, skipping", issue_number)

    logger.info("%d issues ready for dispatch", len(ready))
    return ready

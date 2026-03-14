"""Monitors PRs created by agents for review comments and CI status."""

import json
import logging
import os
import subprocess
import time

from orchestrator import db
from orchestrator.config import (
    CI_WAIT_TIMEOUT_SECONDS,
    GH_TOKEN,
    MAX_PR_FIX_RETRIES,
    PR_POLL_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


def _run_gh(*args: str) -> subprocess.CompletedProcess:
    cmd = ["gh"] + list(args)
    env = {**os.environ, "GH_TOKEN": GH_TOKEN}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    return result


def get_pr_comments(pr_number: int, github_repo: str | None = None) -> list[dict]:
    """Fetch all review comments on a PR (REST API — no resolution status)."""
    repo = github_repo
    owner, repo_name = repo.split("/", 1)
    result = _run_gh(
        "api", f"repos/{owner}/{repo_name}/pulls/{pr_number}/comments",
        "--paginate",
    )
    if result.returncode != 0:
        logger.error("Failed to fetch PR #%d comments: %s", pr_number, result.stderr)
        return []
    try:
        return json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        logger.error("Failed to parse PR #%d comments JSON", pr_number)
        return []


def get_unresolved_threads(pr_number: int, github_repo: str | None = None) -> list[dict] | None:
    """Fetch unresolved review threads with full details using the GraphQL API.

    Paginates through all review threads to ensure none are missed when a PR
    has more than 100 threads.  Comments per thread are fetched up to 100
    (plenty for review context).
    """
    repo = github_repo
    owner, repo_name = repo.split("/", 1)
    query = """
    query($owner: String!, $repo: String!, $pr: Int!, $cursor: String) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes {
              isResolved
              path
              line
              comments(first: 100) {
                nodes {
                  body
                  author { login }
                }
              }
            }
          }
        }
      }
    }
    """

    unresolved = []
    cursor = None

    while True:
        args = [
            "api", "graphql",
            "-f", f"query={query}",
            "-f", f"owner={owner}",
            "-f", f"repo={repo_name}",
            "-F", f"pr={pr_number}",
        ]
        if cursor:
            args += ["-f", f"cursor={cursor}"]

        result = _run_gh(*args)
        if result.returncode != 0:
            logger.warning("GraphQL query failed for PR #%d: %s", pr_number, result.stderr)
            return None
        try:
            data = json.loads(result.stdout)
            if data.get("errors"):
                logger.warning("GraphQL response contained errors for PR #%d: %s", pr_number, data["errors"])
                return None
            review_threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]
            threads = review_threads["nodes"]
            page_info = review_threads["pageInfo"]

            for t in threads:
                if not t["isResolved"]:
                    unresolved.append({
                        "path": t.get("path", "unknown"),
                        "line": t.get("line"),
                        "comments": [
                            {"body": c["body"], "author": c.get("author", {}).get("login", "unknown")}
                            for c in t.get("comments", {}).get("nodes", [])
                        ],
                    })

            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
            if not cursor:
                break

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("Failed to parse GraphQL response for PR #%d: %s", pr_number, e)
            return None

    return unresolved


def get_pr_checks(pr_number: int, github_repo: str | None = None) -> list[dict]:
    """Fetch CI check status for a PR."""
    repo = github_repo
    result = _run_gh(
        "pr", "checks", str(pr_number),
        "--repo", repo,
        "--json", "name,state,bucket",
    )
    if result.returncode != 0:
        logger.warning("Failed to fetch PR #%d checks: %s", pr_number, result.stderr)
        return []
    try:
        return json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return []


def get_pr_branch(pr_number: int, github_repo: str | None = None) -> str | None:
    """Get the head branch name for a PR."""
    repo = github_repo
    result = _run_gh(
        "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "headRefName",
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        return data.get("headRefName")
    except json.JSONDecodeError:
        return None


def is_pr_merged(pr_number: int, github_repo: str | None = None) -> bool:
    """Check if a PR has been merged."""
    repo = github_repo
    result = _run_gh(
        "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "state,mergedAt",
    )
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
        return data.get("state") == "MERGED" or bool(data.get("mergedAt"))
    except json.JSONDecodeError:
        return False


class PRMonitor:
    """Monitors PRs created by agents and dispatches fix agents when needed."""

    def __init__(self, dispatch_fix_callback):
        """
        Args:
            dispatch_fix_callback: function(pr_number, branch_name, issue_number, workspace, unresolved_threads) -> agent_id
                Called when a PR needs review fixes.
        """
        self._dispatch_fix = dispatch_fix_callback
        self._last_comment_counts: dict[int, int] = {}
        self._running = False

    def start(self):
        """Start the PR monitoring loop (blocking)."""
        self._running = True
        logger.info("PR Monitor started (poll interval: %ds)", PR_POLL_INTERVAL_SECONDS)

        while self._running:
            try:
                self._poll_prs()
            except Exception as e:
                logger.error("PR Monitor poll error: %s", e)
            time.sleep(PR_POLL_INTERVAL_SECONDS)

    def stop(self):
        self._running = False

    def _poll_prs(self):
        """Check all PRs in 'pr_created' status for review comments and merge status."""
        issues_with_prs = db.get_issues_by_status("pr_created")

        for issue in issues_with_prs:
            pr_number = issue.get("pr_number")
            if not pr_number:
                continue

            issue_number = issue["issue_number"]
            workspace_id = issue.get("workspace_id")

            # Resolve workspace config for this issue
            workspace = None
            github_repo = None
            if workspace_id:
                workspace = db.get_workspace(workspace_id)
                if workspace:
                    github_repo = workspace["github_repo"]

            logger.debug("Checking PR #%d for issue #%d", pr_number, issue_number)

            # Check if the PR has been merged
            if is_pr_merged(pr_number, github_repo=github_repo):
                logger.info(
                    "PR #%d has been merged. Resolving issue #%d",
                    pr_number, issue_number,
                )
                db.update_issue(issue_number, workspace_id=workspace_id, status="resolved")
                continue

            # Check how many fix iterations we've done
            reviews = db.get_pr_reviews(pr_number)
            iteration_count = len(reviews)

            if iteration_count >= MAX_PR_FIX_RETRIES:
                logger.warning(
                    "PR #%d exceeded max fix retries (%d), escalating to needs_human",
                    pr_number, MAX_PR_FIX_RETRIES,
                )
                db.update_issue(issue_number, workspace_id=workspace_id, status="needs_human")
                self._label_needs_human(issue_number, github_repo=github_repo)
                continue

            # Check if there's already a running fix agent for this PR
            running_agents = db.get_running_agents()
            has_running_fix = any(
                a["pr_number"] == pr_number and a["agent_type"] == "fix_review"
                for a in running_agents
            )
            if has_running_fix:
                logger.debug("Fix agent already running for PR #%d, skipping", pr_number)
                continue

            # Fetch CI status
            checks = get_pr_checks(pr_number, github_repo=github_repo)

            if not checks:
                logger.debug("PR #%d has no CI checks yet, waiting for CI to start", pr_number)
                continue
            ci_pending = any(c.get("state") == "PENDING" or c.get("bucket") == "pending" for c in checks)
            if ci_pending:
                logger.debug("PR #%d CI still running, waiting", pr_number)
                continue

            ci_failed = any(
                c.get("bucket") == "fail" or c.get("state") in ("FAILURE", "ERROR")
                for c in checks
            )

            unresolved_threads = get_unresolved_threads(pr_number, github_repo=github_repo)

            if unresolved_threads is not None:
                unresolved_count = len(unresolved_threads)
                logger.debug("PR #%d: %d unresolved review thread(s)", pr_number, unresolved_count)

                if unresolved_count == 0 and not ci_failed:
                    logger.info(
                        "PR #%d is clean (0 unresolved threads, CI passed). Awaiting merge for issue #%d",
                        pr_number, issue_number,
                    )
                    continue

                if unresolved_count > 0 or ci_failed:
                    # If CI failed but there are no review comments, check if a
                    # fix_review agent already completed for this PR.  If the agent
                    # ran and CI still fails with nothing to fix, the failure is
                    # external (e.g. deploy/Vercel config) — escalate instead of looping.
                    if ci_failed and unresolved_count == 0:
                        completed_fix_agents = [
                            a for a in db.get_all_agents(workspace_id=workspace_id)
                            if a.get("pr_number") == pr_number
                            and a.get("agent_type") == "fix_review"
                            and a.get("status") == "completed"
                        ]
                        if completed_fix_agents:
                            logger.warning(
                                "PR #%d: CI still failing after %d completed fix agent(s) with 0 unresolved "
                                "threads. Escalating to needs_human — the CI failure is likely external.",
                                pr_number, len(completed_fix_agents),
                            )
                            db.update_issue(issue_number, workspace_id=workspace_id, status="needs_human")
                            self._label_needs_human(issue_number, github_repo=github_repo)
                            continue

                    reason_parts = []
                    if unresolved_count > 0:
                        reason_parts.append(f"{unresolved_count} unresolved thread(s)")
                    if ci_failed:
                        reason_parts.append("CI failed")
                    reason = ", ".join(reason_parts)
                    logger.info(
                        "PR #%d needs fixes (%s). Dispatching fix agent (iteration %d)",
                        pr_number, reason, iteration_count + 1,
                    )
                    db.create_pr_review(pr_number, iteration_count + 1, unresolved_count, json.dumps(unresolved_threads), workspace_id=workspace_id)

                    branch_name = get_pr_branch(pr_number, github_repo=github_repo)
                    if not branch_name:
                        logger.error("Could not determine branch for PR #%d", pr_number)
                        continue

                    self._dispatch_fix(pr_number, branch_name, issue_number, workspace, unresolved_threads)
                    continue
            else:
                comments = get_pr_comments(pr_number, github_repo=github_repo)
                new_comment_count = len(comments)
                prev_count = self._last_comment_counts.get(pr_number, 0)

                if new_comment_count == 0 and not ci_failed:
                    logger.info(
                        "PR #%d is clean (0 comments, CI passed). Awaiting merge for issue #%d",
                        pr_number, issue_number,
                    )
                    continue

                if new_comment_count > prev_count or ci_failed:
                    reason = f"{new_comment_count} comments" if new_comment_count > prev_count else "CI failed"
                    logger.info("PR #%d needs fixes (%s). Dispatching fix agent (iteration %d)", pr_number, reason, iteration_count + 1)

                    self._last_comment_counts[pr_number] = new_comment_count
                    rest_threads = [
                        {"path": c.get("path", "unknown"), "line": c.get("line"), "comments": [{"body": c.get("body", ""), "author": (c.get("user") or {}).get("login", "unknown")}]}
                        for c in comments
                    ] if comments else None
                    db.create_pr_review(pr_number, iteration_count + 1, new_comment_count, json.dumps(rest_threads) if rest_threads else None, workspace_id=workspace_id)

                    branch_name = get_pr_branch(pr_number, github_repo=github_repo)
                    if not branch_name:
                        logger.error("Could not determine branch for PR #%d", pr_number)
                        continue

                    self._dispatch_fix(pr_number, branch_name, issue_number, workspace, None)
                    continue

                if prev_count > 0 and new_comment_count <= prev_count and not ci_failed:
                    logger.info(
                        "PR #%d: CI passed and no new comments since last fix (%d comments). "
                        "Awaiting merge for issue #%d",
                        pr_number, new_comment_count, issue_number,
                    )
                    continue

    def _label_needs_human(self, issue_number: int, github_repo: str | None = None):
        """Add 'needs-human' label to the GitHub issue."""
        repo = github_repo
        try:
            _run_gh(
                "issue", "edit", str(issue_number),
                "--repo", repo,
                "--add-label", "needs-human",
            )
        except Exception as e:
            logger.error("Failed to label issue #%d: %s", issue_number, e)

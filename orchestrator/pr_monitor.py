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
    GITHUB_REPO,
    MAX_PR_FIX_RETRIES,
    PR_POLL_INTERVAL_SECONDS,
)

logger = logging.getLogger(__name__)


def _run_gh(*args: str) -> subprocess.CompletedProcess:
    cmd = ["gh"] + list(args)
    env = {**os.environ, "GH_TOKEN": GH_TOKEN}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    return result


def get_pr_comments(pr_number: int) -> list[dict]:
    """Fetch all review comments on a PR (REST API — no resolution status)."""
    owner, repo = GITHUB_REPO.split("/", 1)
    result = _run_gh(
        "api", f"repos/{owner}/{repo}/pulls/{pr_number}/comments",
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


def get_unresolved_threads(pr_number: int) -> list[dict] | None:
    """Fetch unresolved review threads with full details using the GraphQL API.

    Returns a list of unresolved thread dicts with 'path' and 'comments' keys,
    or None if the query fails (caller should fall back to REST heuristic).
    """
    owner, repo = GITHUB_REPO.split("/", 1)
    query = """
    query($owner: String!, $repo: String!, $pr: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $pr) {
          reviewThreads(first: 100) {
            nodes {
              isResolved
              path
              line
              comments(first: 10) {
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
    result = _run_gh(
        "api", "graphql",
        "-f", f"query={query}",
        "-f", f"owner={owner}",
        "-f", f"repo={repo}",
        "-F", f"pr={pr_number}",
    )
    if result.returncode != 0:
        logger.warning("GraphQL query failed for PR #%d: %s", pr_number, result.stderr)
        return None
    try:
        data = json.loads(result.stdout)
        threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        unresolved = []
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
        return unresolved
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("Failed to parse GraphQL response for PR #%d: %s", pr_number, e)
        return None


def get_pr_checks(pr_number: int) -> list[dict]:
    """Fetch CI check status for a PR."""
    result = _run_gh(
        "pr", "checks", str(pr_number),
        "--repo", GITHUB_REPO,
        "--json", "name,state,bucket",
    )
    if result.returncode != 0:
        logger.warning("Failed to fetch PR #%d checks: %s", pr_number, result.stderr)
        return []
    try:
        return json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return []


def get_pr_branch(pr_number: int) -> str | None:
    """Get the head branch name for a PR."""
    result = _run_gh(
        "pr", "view", str(pr_number),
        "--repo", GITHUB_REPO,
        "--json", "headRefName",
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        return data.get("headRefName")
    except json.JSONDecodeError:
        return None


class PRMonitor:
    """Monitors PRs created by agents and dispatches fix agents when needed."""

    def __init__(self, dispatch_fix_callback):
        """
        Args:
            dispatch_fix_callback: function(pr_number, branch_name, issue_number, unresolved_threads) -> agent_id
                Called when a PR needs review fixes. unresolved_threads is a list of
                dicts with 'path', 'line', 'comments' keys, or None if GraphQL failed.
        """
        self._dispatch_fix = dispatch_fix_callback
        self._last_comment_counts: dict[int, int] = {}  # pr_number -> last known comment count
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
        """Check all PRs in 'pr_created' status for review comments."""
        issues_with_prs = db.get_issues_by_status("pr_created")

        for issue in issues_with_prs:
            pr_number = issue.get("pr_number")
            if not pr_number:
                continue

            issue_number = issue["issue_number"]
            logger.debug("Checking PR #%d for issue #%d", pr_number, issue_number)

            # Check how many fix iterations we've done
            reviews = db.get_pr_reviews(pr_number)
            iteration_count = len(reviews)

            if iteration_count >= MAX_PR_FIX_RETRIES:
                logger.warning(
                    "PR #%d exceeded max fix retries (%d), escalating to needs_human",
                    pr_number, MAX_PR_FIX_RETRIES,
                )
                db.update_issue(issue_number, status="needs_human")
                self._label_needs_human(issue_number)
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
            checks = get_pr_checks(pr_number)

            # Check if CI is still running or hasn't started yet
            if not checks:
                logger.debug("PR #%d has no CI checks yet, waiting for CI to start", pr_number)
                continue
            ci_pending = any(c.get("state") == "PENDING" or c.get("bucket") == "pending" for c in checks)
            if ci_pending:
                logger.debug("PR #%d CI still running, waiting", pr_number)
                continue

            # Check CI results
            ci_failed = any(
                c.get("bucket") == "fail" or c.get("state") in ("FAILURE", "ERROR")
                for c in checks
            )

            # Use GraphQL to get unresolved thread details (the ground truth).
            # Falls back to the REST comment-count heuristic if GraphQL fails.
            unresolved_threads = get_unresolved_threads(pr_number)

            if unresolved_threads is not None:
                # ── GraphQL path: use actual resolution status ──
                unresolved_count = len(unresolved_threads)
                logger.debug("PR #%d: %d unresolved review thread(s)", pr_number, unresolved_count)

                if unresolved_count == 0 and not ci_failed:
                    logger.info(
                        "PR #%d is clean (0 unresolved threads, CI passed). Resolving issue #%d",
                        pr_number, issue_number,
                    )
                    db.update_issue(issue_number, status="resolved")
                    continue

                if unresolved_count > 0 or ci_failed:
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
                    db.create_pr_review(pr_number, iteration_count + 1, unresolved_count, json.dumps(unresolved_threads))

                    branch_name = get_pr_branch(pr_number)
                    if not branch_name:
                        logger.error("Could not determine branch for PR #%d", pr_number)
                        continue

                    self._dispatch_fix(pr_number, branch_name, issue_number, unresolved_threads)
                    continue
            else:
                # ── Fallback: REST comment-count heuristic ──
                comments = get_pr_comments(pr_number)
                new_comment_count = len(comments)
                prev_count = self._last_comment_counts.get(pr_number, 0)

                if new_comment_count == 0 and not ci_failed:
                    logger.info("PR #%d is clean (0 comments, CI passed). Resolving issue #%d", pr_number, issue_number)
                    db.update_issue(issue_number, status="resolved")
                    continue

                if new_comment_count > prev_count or ci_failed:
                    reason = f"{new_comment_count} comments" if new_comment_count > prev_count else "CI failed"
                    logger.info("PR #%d needs fixes (%s). Dispatching fix agent (iteration %d)", pr_number, reason, iteration_count + 1)

                    self._last_comment_counts[pr_number] = new_comment_count
                    # Store REST comments as thread-like structures for UI display
                    rest_threads = [
                        {"path": c.get("path", "unknown"), "line": c.get("line"), "comments": [{"body": c.get("body", ""), "author": (c.get("user") or {}).get("login", "unknown")}]}
                        for c in comments
                    ] if comments else None
                    db.create_pr_review(pr_number, iteration_count + 1, new_comment_count, json.dumps(rest_threads) if rest_threads else None)

                    branch_name = get_pr_branch(pr_number)
                    if not branch_name:
                        logger.error("Could not determine branch for PR #%d", pr_number)
                        continue

                    # REST fallback — no thread details available, agent will fetch itself
                    self._dispatch_fix(pr_number, branch_name, issue_number, None)
                    continue

                if prev_count > 0 and new_comment_count <= prev_count and not ci_failed:
                    logger.info(
                        "PR #%d: CI passed and no new comments since last fix (%d comments). "
                        "Resolving issue #%d",
                        pr_number, new_comment_count, issue_number,
                    )
                    db.update_issue(issue_number, status="resolved")
                    continue

    def _label_needs_human(self, issue_number: int):
        """Add 'needs-human' label to the GitHub issue."""
        try:
            _run_gh(
                "issue", "edit", str(issue_number),
                "--repo", GITHUB_REPO,
                "--add-label", "needs-human",
            )
        except Exception as e:
            logger.error("Failed to label issue #%d: %s", issue_number, e)

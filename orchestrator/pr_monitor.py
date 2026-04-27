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
    MANUAL_PR_DISCOVERY_LIMIT,
    MAX_PR_FIX_RETRIES,
    PR_POLL_INTERVAL_SECONDS,
    TRACK_MANUAL_PRS,
)

logger = logging.getLogger(__name__)


def _run_gh(*args: str) -> subprocess.CompletedProcess:
    cmd = ["gh"] + list(args)
    env = {**os.environ, "GH_TOKEN": GH_TOKEN}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    return result


def get_pr_comments(pr_number: int, github_repo: str | None = None) -> list[dict]:
    """Fetch all review comments on a PR (REST API — no resolution status)."""
    if not github_repo:
        return []
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
        data = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        logger.error("Failed to parse PR #%d comments JSON", pr_number)
        return []
    if not isinstance(data, list):
        logger.warning("PR #%d comments response is not a list — treating as empty", pr_number)
        return []
    return data


def get_unresolved_threads(pr_number: int, github_repo: str | None = None) -> list[dict] | None:
    """Fetch unresolved review threads with full details using the GraphQL API.

    Paginates through all review threads to ensure none are missed when a PR
    has more than 100 threads.  Comments per thread are fetched up to 100
    (plenty for review context).
    """
    if not github_repo:
        return None
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
            if not isinstance(data, dict):
                logger.warning("GraphQL response for PR #%d is not a dict", pr_number)
                return None
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
    if not github_repo:
        return []
    result = _run_gh(
        "pr", "checks", str(pr_number),
        "--repo", github_repo,
        "--json", "name,state,bucket",
    )
    if result.returncode != 0:
        logger.warning("Failed to fetch PR #%d checks: %s", pr_number, result.stderr)
        return []
    try:
        data = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def get_pr_branch(pr_number: int, github_repo: str | None = None) -> str | None:
    """Get the head branch name for a PR."""
    if not github_repo:
        return None
    result = _run_gh(
        "pr", "view", str(pr_number),
        "--repo", github_repo,
        "--json", "headRefName",
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data.get("headRefName")


def list_open_prs(github_repo: str | None = None) -> list[dict]:
    """List open, non-draft PRs whose head branch lives in the same repo.

    Fork PRs are excluded because the orchestrator can't push fixes back to a
    fork's branch.  Drafts are excluded so we don't dispatch fixes against
    work-in-progress that the author hasn't asked for review on yet.
    """
    if not github_repo:
        return []
    result = _run_gh(
        "pr", "list",
        "--repo", github_repo,
        "--state", "open",
        "--json", "number,title,headRefName,headRepositoryOwner,isDraft",
        "--limit", str(MANUAL_PR_DISCOVERY_LIMIT),
    )
    if result.returncode != 0:
        logger.warning("Failed to list open PRs for %s: %s", github_repo, result.stderr)
        return []
    try:
        prs = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        logger.warning("Failed to parse open PRs JSON for %s", github_repo)
        return []
    # ``gh pr list --json ...`` should produce a JSON array, but if it returns
    # an error envelope or unexpected shape, downstream ``for pr in prs`` would
    # iterate dict keys (strings) and crash on ``pr.get(...)``.
    if not isinstance(prs, list):
        logger.warning("Unexpected open-PR response shape for %s (not a list)", github_repo)
        return []
    if len(prs) >= MANUAL_PR_DISCOVERY_LIMIT:
        logger.warning(
            "Open-PR list for %s hit the discovery cap (%d). Some PRs may be "
            "missed; raise MANUAL_PR_DISCOVERY_LIMIT if your repo has more.",
            github_repo, MANUAL_PR_DISCOVERY_LIMIT,
        )

    repo_owner = github_repo.split("/", 1)[0]
    eligible = []
    for pr in prs:
        if pr.get("isDraft"):
            continue
        head_owner = (pr.get("headRepositoryOwner") or {}).get("login")
        # Strict match: skip PRs whose head ref isn't in the same repo.  A null
        # head_owner means the fork repo was deleted, so the branch is also
        # unreachable — treat the same as a fork PR and skip.
        if head_owner != repo_owner:
            continue
        eligible.append(pr)
    return eligible


def is_pr_merged(pr_number: int, github_repo: str | None = None) -> bool:
    """Check if a PR has been merged."""
    return get_pr_terminal_state(pr_number, github_repo=github_repo) == "merged"


def get_pr_terminal_state(pr_number: int, github_repo: str | None = None) -> str | None:
    """Return ``'merged'``, ``'closed'`` (closed without merge), or ``None``.

    ``None`` covers still-open PRs, missing ``github_repo`` (workspace lookup
    failed), and PR-view failures.  Callers must treat ``None`` as "keep
    polling, can't conclude anything yet" so a transient error doesn't
    accidentally close the tracking record.
    """
    if not github_repo:
        return None
    result = _run_gh(
        "pr", "view", str(pr_number),
        "--repo", github_repo,
        "--json", "state,mergedAt",
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    # ``gh pr view --json state,mergedAt`` should return an object, but guard
    # against unexpected shapes (empty stdout, error envelopes, lists) so we
    # don't AttributeError the whole poll cycle on a malformed response.
    if not isinstance(data, dict):
        return None
    if data.get("state") == "MERGED" or data.get("mergedAt"):
        return "merged"
    if data.get("state") == "CLOSED":
        return "closed"
    return None


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

    def _discover_manual_prs(self):
        """Find open PRs that have no associated issue record and start tracking them.

        For each active workspace, list open PRs in the GitHub repo and seed a
        synthetic issue record for any PR not already tracked.  The synthetic
        record uses ``issue_number = pr_number`` (PRs and issues share a number
        namespace in GitHub) and starts at status ``pr_created`` so the regular
        ``_poll_prs`` flow processes it on the same cycle.
        """
        if not TRACK_MANUAL_PRS:
            return

        try:
            workspaces = db.get_active_workspaces()
        except Exception as e:
            logger.warning("Could not load workspaces for manual-PR discovery: %s", e)
            return

        for ws in workspaces:
            github_repo = ws.get("github_repo")
            workspace_id = ws.get("id")
            if not github_repo:
                continue
            try:
                prs = list_open_prs(github_repo=github_repo)
            except Exception as e:
                logger.warning("Failed to list open PRs for %s: %s", github_repo, e)
                continue

            for pr in prs:
                pr_number = pr.get("number")
                if not pr_number:
                    continue

                # If we already track this PR, normally skip — but if it's a
                # synthetic record we previously paused (status='resolved' from
                # a closed-without-merge) and the PR is open again, reactivate
                # monitoring.  ``gh pr list --state open`` only returns open
                # PRs, so seeing it here means it was reopened on GitHub.
                existing = db.get_issue_by_pr_number(pr_number, workspace_id=workspace_id)
                if existing:
                    if (
                        existing.get("is_manual_pr")
                        and existing.get("status") == "resolved"
                    ):
                        # Reset iteration count: the reopen is a "try again"
                        # signal from the user, so prior pr_reviews shouldn't
                        # instantly trip MAX_PR_FIX_RETRIES on the next cycle.
                        cleared = db.delete_pr_reviews(pr_number, workspace_id=workspace_id)
                        db.update_issue(
                            existing["issue_number"],
                            workspace_id=workspace_id,
                            status="pr_created",
                        )
                        logger.info(
                            "Manual PR #%d reopened — resuming monitoring "
                            "(cleared %d prior fix iteration(s))",
                            pr_number, cleared,
                        )
                    continue

                # Defense-in-depth: GitHub's invariant says issue #N and PR #N
                # cannot both exist in a repo, but if a real issue row already
                # holds issue_number == pr_number (e.g. stale DB import), refuse
                # to clobber it with a synthetic record.
                clash = db.get_issue(pr_number, workspace_id=workspace_id)
                if clash and not clash.get("is_manual_pr"):
                    logger.warning(
                        "Skipping manual-PR seed for #%d in %s: a real issue "
                        "row already exists with that number (status=%s)",
                        pr_number, github_repo, clash.get("status"),
                    )
                    continue

                title = (pr.get("title") or f"PR #{pr_number}").strip()
                if len(title) > 180:
                    title = title[:177] + "..."
                display_title = f"[Manual PR] {title}"
                try:
                    db.upsert_manual_pr_tracking(pr_number, display_title, workspace_id=workspace_id)
                    logger.info(
                        "Discovered manual PR #%d in %s — now monitoring for review comments",
                        pr_number, ws.get("name") or github_repo,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to seed tracking record for PR #%d in %s: %s",
                        pr_number, github_repo, e,
                    )

    def _poll_prs(self):
        """Check all PRs in 'pr_created' status for review comments and merge status."""
        self._discover_manual_prs()
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

            # Without a github_repo every gh call below would pass --repo None
            # and crash the whole poll cycle.  Skip and surface the bad state
            # so an operator can investigate.
            if not github_repo:
                logger.warning(
                    "Skipping PR #%d (issue #%d): cannot resolve github_repo "
                    "(workspace_id=%s missing or deleted)",
                    pr_number, issue_number, workspace_id,
                )
                continue

            logger.debug("Checking PR #%d for issue #%d", pr_number, issue_number)

            # Check terminal state (merged or closed-without-merge).  Merged PRs
            # are always 'resolved'.  For closed-without-merge: synthetic
            # (manual-PR) rows are 'resolved' (the PR == the tracking unit; if
            # it gets reopened later, _discover_manual_prs reactivates the row);
            # rows backed by a real issue go to 'needs_human' so the user can
            # decide whether to retry — the issue itself isn't actually fixed.
            terminal_state = get_pr_terminal_state(pr_number, github_repo=github_repo)
            if terminal_state == "merged":
                logger.info(
                    "PR #%d has been merged. Resolving issue #%d",
                    pr_number, issue_number,
                )
                db.update_issue(issue_number, workspace_id=workspace_id, status="resolved")
                continue
            if terminal_state == "closed":
                if issue.get("is_manual_pr"):
                    logger.info(
                        "Manual PR #%d closed without merge — pausing tracking",
                        pr_number,
                    )
                    db.update_issue(issue_number, workspace_id=workspace_id, status="resolved")
                else:
                    logger.warning(
                        "PR #%d for issue #%d closed without merge — escalating to needs_human",
                        pr_number, issue_number,
                    )
                    db.update_issue(issue_number, workspace_id=workspace_id, status="needs_human")
                    self._label_needs_human(issue_number, github_repo=github_repo)
                continue

            # Check how many fix iterations we've done (scoped to this
            # workspace so PRs with colliding numbers across repos don't share
            # an iteration budget).
            reviews = db.get_pr_reviews(pr_number, workspace_id=workspace_id)
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
                "api", f"repos/{repo}/issues/{issue_number}/labels",
                "--method", "POST",
                "-f", "labels[]=needs-human",
            )
        except Exception as e:
            logger.error("Failed to label issue #%d: %s", issue_number, e)

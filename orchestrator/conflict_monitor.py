"""Scans open PRs for merge conflicts and dispatches agents to resolve them.

This runs as its own background poller, independent of the review/CI loop in
``pr_monitor.py``.  For every open, same-repo, non-draft PR across all active
workspaces it asks GitHub whether the PR is mergeable.  When a PR is
``CONFLICTING`` it dispatches a ``resolve_conflict`` agent that merges the PR's
base branch into its head branch, resolves the conflicts, and pushes the merge
commit back to the head branch — after which GitHub re-marks the PR mergeable.

Coordination with the review loop: ``PRMonitor`` skips any PR that is currently
``CONFLICTING`` (see ``pr_monitor._poll_prs``), so a conflict resolver and a
review-fix agent never race on the same head branch.
"""

import logging
import os
import subprocess
import time

from orchestrator import db
from orchestrator.config import (
    CONFLICT_POLL_INTERVAL_SECONDS,
    GH_TOKEN,
    MAX_CONFLICT_FIX_RETRIES,
    TRACK_MERGE_CONFLICTS,
)
from orchestrator.pr_monitor import (
    get_pr_merge_info,
    get_pr_terminal_state,
    list_open_prs,
)

logger = logging.getLogger(__name__)


def _run_gh(*args: str) -> subprocess.CompletedProcess:
    cmd = ["gh"] + list(args)
    env = {**os.environ, "GH_TOKEN": GH_TOKEN}
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)


class ConflictMonitor:
    """Polls open PRs for merge conflicts and dispatches resolver agents."""

    def __init__(self, dispatch_conflict_callback, is_paused=None):
        """
        Args:
            dispatch_conflict_callback: function(pr_number, branch_name, base_branch, issue_number, workspace) -> agent_id
                Called when a PR needs its conflicts resolved.
            is_paused: optional zero-arg callable returning True when the swarm is
                hibernating for a rate limit.  When True the monitor skips its
                poll cycle so it doesn't record conflict-fix attempts that would
                be gated anyway.
        """
        self._dispatch_conflict = dispatch_conflict_callback
        self._is_paused = is_paused
        self._running = False

    def start(self):
        """Start the conflict-monitoring loop (blocking)."""
        if not TRACK_MERGE_CONFLICTS:
            logger.info("Merge-conflict resolution disabled (TRACK_MERGE_CONFLICTS=false)")
            return

        self._running = True
        logger.info(
            "Conflict Monitor started (poll interval: %ds)", CONFLICT_POLL_INTERVAL_SECONDS
        )

        while self._running:
            try:
                if self._is_paused and self._is_paused():
                    logger.debug("Swarm hibernating — Conflict Monitor skipping cycle")
                else:
                    self._poll_conflicts()
            except Exception as e:
                logger.error("Conflict Monitor poll error: %s", e)
            time.sleep(CONFLICT_POLL_INTERVAL_SECONDS)

    def stop(self):
        self._running = False

    def _poll_conflicts(self):
        """Scan every active workspace's open PRs for merge conflicts."""
        try:
            workspaces = db.get_active_workspaces()
        except Exception as e:
            logger.warning("Could not load workspaces for conflict scan: %s", e)
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
                try:
                    self._handle_pr(pr_number, ws, github_repo, workspace_id)
                except Exception as e:
                    logger.error("Error handling conflicts for PR #%s: %s", pr_number, e)

    def _handle_pr(self, pr_number: int, workspace: dict, github_repo: str, workspace_id: str | None):
        merge_info = get_pr_merge_info(pr_number, github_repo=github_repo)
        if not merge_info:
            # GitHub view failed — can't conclude anything this cycle.
            return

        mergeable = merge_info.get("mergeable")
        if mergeable != "CONFLICTING":
            # MERGEABLE, or UNKNOWN (GitHub still computing) — nothing to do.
            return

        # Don't act on a PR that's already on its way out.
        terminal_state = get_pr_terminal_state(pr_number, github_repo=github_repo)
        if terminal_state in ("merged", "closed"):
            return

        # Never run two agents against the same PR's head branch at once, and
        # never re-dispatch while an agent for this PR is rate-limited: that
        # agent's worktree is preserved for resumption, and create_worktree_for_pr
        # would delete it (then the rate-limit watcher would resume into the new
        # agent's worktree — two agents racing the same branch).  Scope by
        # workspace so identically-numbered PRs in different repos don't block
        # each other.
        busy = db.get_running_agents() + db.get_rate_limited_agents()
        if any(
            a.get("pr_number") == pr_number and a.get("workspace_id") == workspace_id
            for a in busy
        ):
            logger.debug("Agent already busy on PR #%d — skipping conflict dispatch", pr_number)
            return

        branch_name = merge_info.get("head_ref")
        base_branch = merge_info.get("base_ref")
        base_sha = merge_info.get("base_oid")
        head_sha = merge_info.get("head_oid")
        if not branch_name or not base_branch:
            logger.warning(
                "PR #%d is CONFLICTING but head/base branch is unknown — skipping",
                pr_number,
            )
            return

        # Bound retries *per base revision*: attempts against the current base
        # commit only.  When the base branch advances, base_sha changes and the
        # count resets, so a genuinely-new conflict gets a fresh budget.
        attempts = db.get_conflict_fixes(pr_number, workspace_id=workspace_id, base_sha=base_sha)

        # Already escalated this exact conflict — stay quiet, don't re-comment.
        if any(a.get("status") == "escalated" for a in attempts):
            return

        # Count only real resolution attempts toward the budget. 'escalated' is a
        # marker row, and 'dispatch_failed' means the pool was full so no agent
        # actually ran — neither should consume a retry.
        resolve_attempts = [
            a for a in attempts if a.get("status") not in ("escalated", "dispatch_failed")
        ]
        if len(resolve_attempts) >= MAX_CONFLICT_FIX_RETRIES:
            self._escalate(
                pr_number, base_branch, base_sha, head_sha,
                github_repo=github_repo, workspace_id=workspace_id,
                attempts=len(resolve_attempts),
            )
            return

        iteration = len(resolve_attempts) + 1
        logger.info(
            "PR #%d is CONFLICTING with %s. Dispatching conflict resolver (attempt %d/%d)",
            pr_number, base_branch, iteration, MAX_CONFLICT_FIX_RETRIES,
        )

        # Record the attempt before dispatch so a crash mid-dispatch still
        # counts against the retry budget (prevents infinite re-dispatch loops).
        conflict_fix_id = db.create_conflict_fix(
            pr_number,
            iteration,
            base_branch=base_branch,
            base_sha=base_sha,
            head_sha=head_sha,
            workspace_id=workspace_id,
        )

        # Reuse an existing tracked issue's number if one exists (manual-PR rows
        # use issue_number == pr_number); otherwise leave it as the PR number so
        # the agent record is still attributable.
        tracked = db.get_issue_by_pr_number(pr_number, workspace_id=workspace_id)
        issue_number = tracked["issue_number"] if tracked else pr_number

        agent_id = self._dispatch_conflict(
            pr_number, branch_name, base_branch, issue_number, workspace
        )
        if agent_id:
            db.update_conflict_fix(conflict_fix_id, agent_id=agent_id, status="dispatched")
        else:
            # Pool was full / dispatch failed — roll the attempt back so we
            # retry cleanly next cycle instead of burning the budget on a no-op.
            db.update_conflict_fix(conflict_fix_id, status="dispatch_failed")
            logger.info("Conflict dispatch deferred for PR #%d (pool full or error)", pr_number)

    def _escalate(
        self,
        pr_number: int,
        base_branch: str,
        base_sha: str | None,
        head_sha: str | None,
        github_repo: str,
        workspace_id: str | None,
        attempts: int,
    ):
        """Give up on a PR's conflicts after repeated failures: label + comment once."""
        logger.warning(
            "PR #%d still CONFLICTING after %d resolution attempt(s) — escalating to human",
            pr_number, attempts,
        )

        # Persist an 'escalated' marker so we don't re-comment every cycle. This
        # is a separate row (not a status flip on the last attempt) so the real
        # attempt count stays at/above the cap.
        marker_id = db.create_conflict_fix(
            pr_number,
            attempts + 1,
            base_branch=base_branch,
            base_sha=base_sha,
            head_sha=head_sha,
            workspace_id=workspace_id,
        )
        db.update_conflict_fix(marker_id, status="escalated")

        # Best-effort label (PRs accept issue labels via the issues endpoint).
        try:
            _run_gh(
                "api", f"repos/{github_repo}/issues/{pr_number}/labels",
                "--method", "POST",
                "-f", "labels[]=needs-human",
            )
        except Exception as e:
            logger.error("Failed to label PR #%d needs-human: %s", pr_number, e)

        # Best-effort comment explaining what happened.
        try:
            body = (
                f"⚠️ Automated conflict resolution gave up after {attempts} attempt(s).\n\n"
                f"This PR has merge conflicts with `{base_branch}` that the swarm could not "
                f"resolve safely. A human needs to merge `{base_branch}` in and resolve the "
                f"remaining conflicts manually."
            )
            _run_gh("pr", "comment", str(pr_number), "--repo", github_repo, "--body", body)
        except Exception as e:
            logger.error("Failed to comment on PR #%d: %s", pr_number, e)

        # If a tracked issue/PR row exists, reflect the escalation in its status.
        tracked = db.get_issue_by_pr_number(pr_number, workspace_id=workspace_id)
        if tracked:
            db.update_issue(tracked["issue_number"], workspace_id=workspace_id, status="needs_human")

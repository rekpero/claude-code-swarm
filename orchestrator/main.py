"""Entry point — starts all subsystems of the Claude Code Agent Swarm."""

import logging
import os
import signal
import sys
import threading
import time

from orchestrator import db
from orchestrator.agent_pool import AgentPool
from orchestrator.config import (
    DASHBOARD_PORT,
    POLL_INTERVAL_SECONDS,
    print_config,
    validate_environment,
)
from orchestrator.issue_poller import poll_issues
from orchestrator.pr_monitor import PRMonitor
from orchestrator.rate_limit_watcher import RateLimitWatcher
from orchestrator.worktree import cleanup_worktree

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("swarm")

# Global state for graceful shutdown
_shutdown_event = threading.Event()
_auth_paused = False


def _pid_is_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _recover_stale_agents():
    """On startup, handle agents still marked as 'running' or 'rate_limited' in the DB."""
    stale = db.get_running_agents()
    if not stale:
        return

    for agent in stale:
        pid = agent.get("pid")
        agent_id = agent["agent_id"]
        issue_num = agent["issue_number"]
        workspace_id = agent.get("workspace_id")

        if pid and _pid_is_alive(pid):
            logger.info(
                "Agent %s (PID %d) for issue #%s is still running — leaving it alone",
                agent_id, pid, issue_num,
            )
            continue

        logger.warning(
            "Agent %s (PID %s) for issue #%s is dead — marking as failed",
            agent_id, pid or "unknown", issue_num,
        )
        db.finish_agent(agent_id, status="failed", error_message="Agent process died during orchestrator restart")

        issue = db.get_issue(issue_num, workspace_id=workspace_id)
        if issue and issue["status"] == "in_progress":
            db.update_issue(issue_num, workspace_id=workspace_id, status="pending")

        if agent.get("worktree_path"):
            try:
                # Resolve repo_path from workspace for correct worktree cleanup
                ws = db.get_workspace(workspace_id) if workspace_id else None
                repo_path = ws["local_path"] if ws else None
                cleanup_worktree(agent["worktree_path"], repo_path=repo_path)
            except Exception:
                pass

    rate_limited = db.get_rate_limited_agents()
    if rate_limited:
        logger.info(
            "%d rate-limited agent(s) found from previous run — watcher will resume them: %s",
            len(rate_limited),
            ", ".join(a["agent_id"] for a in rate_limited),
        )


def main():
    print_config()

    # Validate environment
    errors = validate_environment()
    if errors:
        logger.error("Environment validation failed:")
        for err in errors:
            logger.error("  - %s", err)
        sys.exit(1)

    logger.info("Environment validation passed")

    # Initialize database
    db.init_db()
    logger.info("Database initialized")

    # Recover from previous crash
    _recover_stale_agents()

    # Create agent pool
    pool = AgentPool()

    # Create PR monitor with dispatch callback (now workspace-aware)
    pr_monitor = PRMonitor(
        dispatch_fix_callback=lambda pr_num, branch, issue_num, workspace=None, threads=None: pool.dispatch_fix_review(
            pr_num, branch, issue_num, workspace, threads
        )
    )

    # Create rate limit watcher
    rate_limit_watcher = RateLimitWatcher(agent_pool=pool)

    # Set up graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        _shutdown_event.set()
        pr_monitor.stop()
        rate_limit_watcher.stop()
        pool.shutdown()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Start dashboard in background thread
    dashboard_thread = threading.Thread(
        target=_start_dashboard, daemon=True, name="dashboard"
    )
    dashboard_thread.start()
    logger.info("Dashboard started on port %d", DASHBOARD_PORT)

    # Start PR monitor in background thread
    pr_monitor_thread = threading.Thread(
        target=pr_monitor.start, daemon=True, name="pr-monitor"
    )
    pr_monitor_thread.start()
    logger.info("PR Monitor started")

    # Start rate limit watcher in background thread
    rate_limit_thread = threading.Thread(
        target=rate_limit_watcher.start, daemon=True, name="rate-limit-watcher"
    )
    rate_limit_thread.start()
    logger.info("Rate limit watcher started")

    # Main loop: poll issues across all active workspaces and dispatch agents
    logger.info("Swarm orchestrator running. Poll interval: %ds", POLL_INTERVAL_SECONDS)
    logger.info("Dashboard: http://localhost:%d", DASHBOARD_PORT)

    consecutive_errors = 0
    while not _shutdown_event.is_set():
        try:
            _poll_and_dispatch(pool)
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            logger.error("Poll cycle error (%d consecutive): %s", consecutive_errors, e)
            if consecutive_errors >= 3:
                backoff = min(consecutive_errors * POLL_INTERVAL_SECONDS, 600)
                logger.warning("Backing off for %ds due to repeated errors", backoff)
                _shutdown_event.wait(timeout=backoff)
                continue

        _shutdown_event.wait(timeout=POLL_INTERVAL_SECONDS)

    logger.info("Swarm orchestrator stopped")


def _poll_and_dispatch(pool: AgentPool):
    """Poll for new issues across all active workspaces and dispatch agents."""
    workspaces = db.get_active_workspaces()

    if not workspaces:
        logger.debug("No active workspaces, skipping poll")
        return

    for workspace in workspaces:
        try:
            ready_issues = poll_issues(
                github_repo=workspace["github_repo"],
                workspace_id=workspace["id"],
            )

            for issue in ready_issues:
                if not pool.can_dispatch:
                    logger.info("Agent pool full, deferring remaining issues to next cycle")
                    return  # Return entirely — next cycle will pick up remaining

                issue_number = issue["number"]
                logger.info(
                    "Dispatching agent for issue #%d (%s): %s",
                    issue_number, workspace["name"], issue["title"],
                )
                agent_id = pool.dispatch_implement(issue_number, workspace=workspace)

                if agent_id:
                    logger.info("Agent %s dispatched for issue #%d", agent_id, issue_number)
                else:
                    logger.warning("Failed to dispatch agent for issue #%d", issue_number)

        except Exception as e:
            logger.error("Error polling workspace %s (%s): %s", workspace["name"], workspace["id"], e)


def _start_dashboard():
    """Start the FastAPI dashboard server."""
    import uvicorn
    from orchestrator.dashboard import app

    uvicorn.run(app, host="0.0.0.0", port=DASHBOARD_PORT, log_level="warning")


if __name__ == "__main__":
    main()

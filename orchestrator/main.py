"""Entry point — starts all subsystems of the Claude Code Agent Swarm."""

import logging
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


def _recover_stale_agents():
    """On startup, mark any agents still 'running' in the DB as failed (stale from a previous crash)."""
    stale = db.get_running_agents()
    for agent in stale:
        logger.warning(
            "Recovering stale agent %s (was running for issue #%s)",
            agent["agent_id"], agent["issue_number"],
        )
        db.finish_agent(agent["agent_id"], status="failed", error_message="Orchestrator restarted — agent marked as stale")
        # Reset the issue to pending so it can be retried
        issue = db.get_issue(agent["issue_number"])
        if issue and issue["status"] == "in_progress":
            db.update_issue(agent["issue_number"], status="pending")
        # Try to clean up the worktree
        if agent.get("worktree_path"):
            try:
                cleanup_worktree(agent["worktree_path"])
            except Exception:
                pass


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

    # Create PR monitor with dispatch callback
    pr_monitor = PRMonitor(
        dispatch_fix_callback=lambda pr_num, branch, issue_num: pool.dispatch_fix_review(
            pr_num, branch, issue_num
        )
    )

    # Set up graceful shutdown
    def shutdown_handler(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        _shutdown_event.set()
        pr_monitor.stop()
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

    # Main loop: poll issues and dispatch agents
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
            # If we get repeated failures, back off to avoid hammering
            if consecutive_errors >= 3:
                backoff = min(consecutive_errors * POLL_INTERVAL_SECONDS, 600)
                logger.warning("Backing off for %ds due to repeated errors", backoff)
                _shutdown_event.wait(timeout=backoff)
                continue

        # Wait for next poll interval (or shutdown)
        _shutdown_event.wait(timeout=POLL_INTERVAL_SECONDS)

    logger.info("Swarm orchestrator stopped")


def _poll_and_dispatch(pool: AgentPool):
    """Poll for new issues and dispatch agents."""
    ready_issues = poll_issues()

    for issue in ready_issues:
        if not pool.can_dispatch:
            logger.info("Agent pool full, deferring remaining issues to next cycle")
            break

        issue_number = issue["number"]
        logger.info("Dispatching agent for issue #%d: %s", issue_number, issue["title"])
        agent_id = pool.dispatch_implement(issue_number)

        if agent_id:
            logger.info("Agent %s dispatched for issue #%d", agent_id, issue_number)
        else:
            logger.warning("Failed to dispatch agent for issue #%d", issue_number)


def _start_dashboard():
    """Start the FastAPI dashboard server."""
    import uvicorn
    from orchestrator.dashboard import app

    uvicorn.run(app, host="0.0.0.0", port=DASHBOARD_PORT, log_level="warning")


if __name__ == "__main__":
    main()

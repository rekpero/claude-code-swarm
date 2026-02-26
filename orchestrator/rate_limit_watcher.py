"""Monitors rate-limited agents and resumes them when the limit resets."""

import logging
import os
import subprocess
import threading
import time

from orchestrator import db
from orchestrator.config import (
    CLAUDE_CODE_OAUTH_TOKEN,
    RATE_LIMIT_RETRY_INTERVAL,
)

logger = logging.getLogger(__name__)


def _probe_claude_available() -> bool:
    """Run a lightweight Claude CLI command to check if rate limits have reset.

    Sends a trivial prompt with --max-turns 1 and checks the exit code.
    Returns True if Claude responds successfully (no rate limit).
    """
    try:
        env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": CLAUDE_CODE_OAUTH_TOKEN}
        result = subprocess.run(
            ["claude", "-p", "Reply with just the word OK", "--max-turns", "1"],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if result.returncode == 0:
            return True
        # Check if still rate limited
        stderr_lower = result.stderr.lower()
        from orchestrator.agent_pool import _RATE_LIMIT_PATTERNS
        for pattern in _RATE_LIMIT_PATTERNS:
            if pattern in stderr_lower:
                return False
        # Non-zero exit for other reasons — assume available
        return True
    except subprocess.TimeoutExpired:
        logger.debug("Claude probe timed out — assuming still limited")
        return False
    except Exception as e:
        logger.debug("Claude probe failed: %s", e)
        return False


class RateLimitWatcher:
    """Background watcher that detects when rate limits reset and resumes paused agents."""

    def __init__(self, agent_pool):
        self._pool = agent_pool
        self._stop_event = threading.Event()

    def start(self):
        """Run the watcher loop (blocking — call from a thread)."""
        logger.info(
            "Rate limit watcher started (check interval: %ds)",
            RATE_LIMIT_RETRY_INTERVAL,
        )
        while not self._stop_event.is_set():
            try:
                self._check_and_resume()
            except Exception as e:
                logger.error("Rate limit watcher error: %s", e)
            self._stop_event.wait(timeout=RATE_LIMIT_RETRY_INTERVAL)

        logger.info("Rate limit watcher stopped")

    def stop(self):
        self._stop_event.set()

    def _check_and_resume(self):
        """Check for rate-limited agents and attempt to resume them."""
        limited_agents = db.get_rate_limited_agents()
        if not limited_agents:
            return

        logger.info(
            "Found %d rate-limited agent(s), probing Claude availability...",
            len(limited_agents),
        )

        if not _probe_claude_available():
            logger.info("Claude still rate-limited — will retry in %ds", RATE_LIMIT_RETRY_INTERVAL)
            return

        logger.info("Claude is available again — resuming rate-limited agents")

        for agent_record in limited_agents:
            if not self._pool.can_dispatch:
                logger.info("Agent pool full — deferring remaining resumes to next cycle")
                break

            old_id = agent_record["agent_id"]
            new_id = self._pool.resume_rate_limited_agent(agent_record)
            if new_id:
                logger.info("Resumed agent %s -> %s", old_id, new_id)
            else:
                logger.warning("Failed to resume agent %s", old_id)

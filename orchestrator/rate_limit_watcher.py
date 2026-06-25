"""Watches for the Claude rate limit to reset and wakes the swarm.

The probe used here lives in ``agent_pool`` so the same logic that confirms a
rate limit before hibernating also decides when to wake.
"""

import logging
import threading

from orchestrator import db
from orchestrator.agent_pool import _probe_claude_available
from orchestrator.config import RATE_LIMIT_RETRY_INTERVAL

logger = logging.getLogger(__name__)


class RateLimitWatcher:
    """Watches for the rate limit to reset and wakes the swarm from hibernation.

    When any agent hits a Claude usage/rate limit the pool enters *hibernation*
    (all in-flight agents killed, dispatch paused).  This watcher polls Claude on
    a fixed interval (default 15 min) and, once a probe succeeds, wakes the pool
    so the normal pollers restart the paused work from the beginning.
    """

    def __init__(self, agent_pool):
        self._pool = agent_pool
        self._stop_event = threading.Event()

    def start(self):
        """Run the watcher loop (blocking — call from a thread)."""
        logger.info(
            "Rate limit watcher started (probe interval while hibernating: %ds)",
            RATE_LIMIT_RETRY_INTERVAL,
        )
        while not self._stop_event.is_set():
            try:
                if self._pool.is_hibernating:
                    self._check_and_wake()
                else:
                    # Legacy: resume any pre-existing 'rate_limited' rows (e.g.
                    # left over from before hibernation was introduced).
                    self._resume_legacy_rate_limited()
            except Exception as e:
                logger.error("Rate limit watcher error: %s", e)
            self._stop_event.wait(timeout=RATE_LIMIT_RETRY_INTERVAL)

        logger.info("Rate limit watcher stopped")

    def stop(self):
        self._stop_event.set()

    def _check_and_wake(self):
        """While hibernating, probe Claude and wake the swarm once it responds."""
        logger.info("Swarm hibernating — probing Claude availability...")
        if not _probe_claude_available():
            logger.info(
                "Claude still rate-limited — staying hibernated, retrying in %ds",
                RATE_LIMIT_RETRY_INTERVAL,
            )
            return

        logger.info("Claude responded — waking the swarm from hibernation")
        self._pool.wake_from_hibernation()

    def _resume_legacy_rate_limited(self):
        """Resume any leftover 'rate_limited' agents from before hibernation."""
        limited_agents = db.get_rate_limited_agents()
        if not limited_agents:
            return

        if not _probe_claude_available():
            return

        for agent_record in limited_agents:
            if not self._pool.can_dispatch:
                break
            old_id = agent_record["agent_id"]
            new_id = self._pool.resume_rate_limited_agent(agent_record)
            if new_id:
                logger.info("Resumed legacy rate-limited agent %s -> %s", old_id, new_id)

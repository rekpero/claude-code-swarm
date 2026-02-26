"""Manages Claude Code agent subprocess lifecycle."""

import json
import logging
import os
import signal
import subprocess
import threading
import time
from typing import Callable

from orchestrator import db
from orchestrator.config import (
    AGENT_MAX_TURNS_FIX,
    AGENT_MAX_TURNS_IMPLEMENT,
    AGENT_TIMEOUT_SECONDS,
    CLAUDE_CODE_OAUTH_TOKEN,
    GH_TOKEN,
    MAX_CONCURRENT_AGENTS,
)
from orchestrator.prompts import build_fix_review_prompt, build_implement_prompt
from orchestrator.stream_parser import AgentEvent, extract_pr_number, parse_stream_line
from orchestrator.worktree import cleanup_worktree, create_worktree, create_worktree_for_pr, ensure_repo_updated

logger = logging.getLogger(__name__)


class AgentProcess:
    """Wraps a running claude -p subprocess."""

    def __init__(
        self,
        agent_id: str,
        process: subprocess.Popen,
        worktree_path: str,
        issue_number: int,
        agent_type: str,
        pr_number: int | None = None,
    ):
        self.agent_id = agent_id
        self.process = process
        self.worktree_path = worktree_path
        self.issue_number = issue_number
        self.agent_type = agent_type
        self.pr_number = pr_number
        self.events: list[AgentEvent] = []
        self.started_at = time.time()
        self._reader_thread: threading.Thread | None = None

    def start_reader(self):
        """Start a background thread to read stream-json output."""
        self._reader_thread = threading.Thread(
            target=self._read_stream, daemon=True, name=f"reader-{self.agent_id}"
        )
        self._reader_thread.start()

    def _read_stream(self):
        """Read stdout line by line and parse stream-json events."""
        try:
            for line in self.process.stdout:
                event = parse_stream_line(line)
                if event:
                    self.events.append(event)
                    db.insert_event(self.agent_id, event.event_type, json.dumps(event.raw))
                    if event.event_type == "tool_use":
                        logger.info("[%s] %s", self.agent_id, event.summary)
        except Exception as e:
            logger.error("[%s] Stream reader error: %s", self.agent_id, e)

    @property
    def is_running(self) -> bool:
        return self.process.poll() is None

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.started_at

    @property
    def is_timed_out(self) -> bool:
        return self.elapsed_seconds > AGENT_TIMEOUT_SECONDS

    def kill(self):
        """Kill the agent process."""
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


class AgentPool:
    """Manages the lifecycle of Claude Code agent subprocesses."""

    def __init__(self):
        self._agents: dict[str, AgentProcess] = {}
        self._lock = threading.Lock()
        self._on_agent_complete: Callable[[AgentProcess], None] | None = None

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for a in self._agents.values() if a.is_running)

    @property
    def can_dispatch(self) -> bool:
        return self.active_count < MAX_CONCURRENT_AGENTS

    def set_completion_callback(self, callback: Callable[[AgentProcess], None]):
        """Set a callback to be called when an agent completes."""
        self._on_agent_complete = callback

    def dispatch_implement(self, issue_number: int) -> str | None:
        """Dispatch an agent to implement an issue. Returns agent_id or None if pool is full."""
        if not self.can_dispatch:
            logger.warning("Agent pool full (%d/%d), cannot dispatch", self.active_count, MAX_CONCURRENT_AGENTS)
            return None

        agent_id = f"agent-issue-{issue_number}-{int(time.time())}"
        branch_name = f"fix/issue-{issue_number}"

        try:
            # Update repo and create worktree
            ensure_repo_updated()
            worktree_path = create_worktree(issue_number)
        except Exception as e:
            logger.error("Failed to create worktree for issue #%d: %s", issue_number, e)
            return None

        prompt = build_implement_prompt(issue_number)

        try:
            agent_proc = self._spawn_agent(
                agent_id=agent_id,
                prompt=prompt,
                worktree_path=worktree_path,
                max_turns=AGENT_MAX_TURNS_IMPLEMENT,
                issue_number=issue_number,
                agent_type="implement",
            )
        except Exception as e:
            logger.error("Failed to spawn agent for issue #%d: %s", issue_number, e)
            cleanup_worktree(worktree_path)
            return None

        # Record in DB
        db.create_agent(
            agent_id=agent_id,
            issue_number=issue_number,
            agent_type="implement",
            worktree_path=worktree_path,
            branch_name=branch_name,
        )
        db.update_issue(issue_number, status="in_progress", agent_id=agent_id, attempts=db.get_issue(issue_number)["attempts"] + 1)

        with self._lock:
            self._agents[agent_id] = agent_proc

        agent_proc.start_reader()
        logger.info("Dispatched agent %s for issue #%d", agent_id, issue_number)

        # Start monitoring thread
        threading.Thread(
            target=self._monitor_agent, args=(agent_id,), daemon=True, name=f"monitor-{agent_id}"
        ).start()

        return agent_id

    def dispatch_fix_review(self, pr_number: int, branch_name: str, issue_number: int) -> str | None:
        """Dispatch an agent to fix PR review comments. Returns agent_id or None."""
        if not self.can_dispatch:
            logger.warning("Agent pool full, cannot dispatch fix agent")
            return None

        agent_id = f"agent-pr-fix-{pr_number}-{int(time.time())}"

        try:
            ensure_repo_updated()
            worktree_path = create_worktree_for_pr(pr_number, branch_name)
        except Exception as e:
            logger.error("Failed to create worktree for PR #%d: %s", pr_number, e)
            return None

        prompt = build_fix_review_prompt(pr_number)

        try:
            agent_proc = self._spawn_agent(
                agent_id=agent_id,
                prompt=prompt,
                worktree_path=worktree_path,
                max_turns=AGENT_MAX_TURNS_FIX,
                issue_number=issue_number,
                agent_type="fix_review",
                pr_number=pr_number,
            )
        except Exception as e:
            logger.error("Failed to spawn fix agent for PR #%d: %s", pr_number, e)
            cleanup_worktree(worktree_path)
            return None

        db.create_agent(
            agent_id=agent_id,
            issue_number=issue_number,
            pr_number=pr_number,
            agent_type="fix_review",
            worktree_path=worktree_path,
            branch_name=branch_name,
        )

        with self._lock:
            self._agents[agent_id] = agent_proc

        agent_proc.start_reader()
        logger.info("Dispatched fix agent %s for PR #%d", agent_id, pr_number)

        threading.Thread(
            target=self._monitor_agent, args=(agent_id,), daemon=True, name=f"monitor-{agent_id}"
        ).start()

        return agent_id

    def _spawn_agent(
        self,
        agent_id: str,
        prompt: str,
        worktree_path: str,
        max_turns: int,
        issue_number: int,
        agent_type: str,
        pr_number: int | None = None,
    ) -> AgentProcess:
        """Spawn a claude -p subprocess."""
        cmd = [
            "claude", "-p", prompt,
            "--allowedTools", "Read,Edit,Bash,Write,Glob,Grep",
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", str(max_turns),
        ]

        env = {
            **os.environ,
            "CLAUDE_CODE_OAUTH_TOKEN": CLAUDE_CODE_OAUTH_TOKEN,
            "GH_TOKEN": GH_TOKEN,
        }

        logger.info("Spawning agent %s in %s", agent_id, worktree_path)
        process = subprocess.Popen(
            cmd,
            cwd=worktree_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        return AgentProcess(
            agent_id=agent_id,
            process=process,
            worktree_path=worktree_path,
            issue_number=issue_number,
            agent_type=agent_type,
            pr_number=pr_number,
        )

    def _monitor_agent(self, agent_id: str):
        """Monitor an agent until it finishes or times out."""
        with self._lock:
            agent = self._agents.get(agent_id)
        if not agent:
            return

        while agent.is_running:
            if agent.is_timed_out:
                logger.warning("Agent %s timed out after %ds, killing", agent_id, AGENT_TIMEOUT_SECONDS)
                agent.kill()
                db.finish_agent(agent_id, status="timeout", error_message="Agent exceeded timeout")
                cleanup_worktree(agent.worktree_path)
                return
            time.sleep(5)

        # Agent finished
        return_code = agent.process.returncode
        stderr_output = agent.process.stderr.read() if agent.process.stderr else ""

        if return_code == 0:
            logger.info("Agent %s completed successfully", agent_id)
            # Try to extract PR number from events
            pr_num = extract_pr_number(agent.events)
            db.finish_agent(agent_id, status="completed")
            db.update_agent(agent_id, turns_used=len([e for e in agent.events if e.event_type == "assistant"]))

            if agent.agent_type == "implement" and pr_num:
                db.update_agent(agent_id, pr_number=pr_num)
                db.update_issue(agent.issue_number, status="pr_created", pr_number=pr_num)
                logger.info("Agent %s created PR #%d for issue #%d", agent_id, pr_num, agent.issue_number)
            elif agent.agent_type == "implement":
                # Agent completed but we couldn't detect a PR number
                logger.warning("Agent %s completed but no PR number detected", agent_id)
                db.update_issue(agent.issue_number, status="pr_created")
        else:
            error_msg = stderr_output[:500] if stderr_output else f"Exit code {return_code}"
            logger.error("Agent %s failed: %s", agent_id, error_msg)
            db.finish_agent(agent_id, status="failed", error_message=error_msg)

            if agent.agent_type == "implement":
                # Reset issue to pending so it can be retried
                db.update_issue(agent.issue_number, status="pending")

        # Clean up worktree
        cleanup_worktree(agent.worktree_path)

        # Call completion callback
        if self._on_agent_complete:
            try:
                self._on_agent_complete(agent)
            except Exception as e:
                logger.error("Completion callback error: %s", e)

    def get_active_agents(self) -> list[dict]:
        """Return info about all active agents for the dashboard."""
        with self._lock:
            results = []
            for agent_id, agent in self._agents.items():
                recent_events = agent.events[-5:] if agent.events else []
                results.append({
                    "agent_id": agent_id,
                    "issue_number": agent.issue_number,
                    "pr_number": agent.pr_number,
                    "agent_type": agent.agent_type,
                    "is_running": agent.is_running,
                    "elapsed_seconds": round(agent.elapsed_seconds),
                    "event_count": len(agent.events),
                    "recent_events": [
                        {"type": e.event_type, "summary": e.summary}
                        for e in recent_events
                    ],
                })
            return results

    def shutdown(self):
        """Kill all running agents and clean up."""
        logger.info("Shutting down agent pool...")
        with self._lock:
            for agent_id, agent in self._agents.items():
                if agent.is_running:
                    logger.info("Killing agent %s", agent_id)
                    agent.kill()
                    db.finish_agent(agent_id, status="failed", error_message="Orchestrator shutdown")
                    cleanup_worktree(agent.worktree_path)
        logger.info("Agent pool shutdown complete")

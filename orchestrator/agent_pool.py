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
    MAX_RATE_LIMIT_RESUMES,
    SKILLS_ENABLED,
)
from orchestrator.prompts import (
    build_fix_review_prompt,
    build_implement_prompt,
    build_resume_fix_review_prompt,
    build_resume_implement_prompt,
)
from orchestrator.stream_parser import AgentEvent, extract_pr_number, extract_session_id, parse_stream_line
from orchestrator.worktree import cleanup_worktree, create_worktree, create_worktree_for_pr, ensure_repo_updated

# Patterns that indicate Claude usage/rate limit errors (case-insensitive).
_RATE_LIMIT_PATTERNS = [
    "rate limit",
    "usage limit",
    "too many requests",
    "429",
    "token limit exceeded",
    "exceeded your",
    "capacity",
    "overloaded",
    "try again later",
    "rate_limit",
    "throttl",
]

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
            pid=agent_proc.process.pid,
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

    def dispatch_fix_review(self, pr_number: int, branch_name: str, issue_number: int, unresolved_threads: list[dict] | None = None) -> str | None:
        """Dispatch an agent to fix PR review comments. Returns agent_id or None.

        Args:
            unresolved_threads: Pre-fetched unresolved thread details from GraphQL,
                or None to have the agent fetch comments itself (REST fallback).
        """
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

        prompt = build_fix_review_prompt(pr_number, unresolved_threads)

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
            pid=agent_proc.process.pid,
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
        """Spawn a claude -p subprocess.

        Note: We do NOT pass --max-turns to claude CLI. The agent timeout
        (AGENT_TIMEOUT_SECONDS) is the safety net. Max-turns would silently
        stop the agent mid-work on large features.
        """
        allowed_tools = "Read,Edit,Bash,Write,Glob,Grep"
        if SKILLS_ENABLED:
            allowed_tools += ",Skill"

        cmd = [
            "claude", "-p", prompt,
            "--allowedTools", allowed_tools,
            "--output-format", "stream-json",
            "--verbose",
        ]

        env = {
            **os.environ,
            "CLAUDE_CODE_OAUTH_TOKEN": CLAUDE_CODE_OAUTH_TOKEN,
            "GH_TOKEN": GH_TOKEN,
        }

        logger.info("Spawning agent %s in %s (PID will be independent)", agent_id, worktree_path)
        process = subprocess.Popen(
            cmd,
            cwd=worktree_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,  # Agent survives orchestrator restart
        )

        return AgentProcess(
            agent_id=agent_id,
            process=process,
            worktree_path=worktree_path,
            issue_number=issue_number,
            agent_type=agent_type,
            pr_number=pr_number,
        )

    @staticmethod
    def _is_rate_limit_error(stderr_output: str, events: list[AgentEvent]) -> bool:
        """Check if the agent failure was caused by a rate/usage limit."""
        # Check stderr
        text = stderr_output.lower()
        for pattern in _RATE_LIMIT_PATTERNS:
            if pattern in text:
                return True
        # Check error events from stream-json
        for event in events:
            if event.event_type == "error":
                error_text = event.summary.lower()
                for pattern in _RATE_LIMIT_PATTERNS:
                    if pattern in error_text:
                        return True
        return False

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
        turns = len([e for e in agent.events if e.event_type == "assistant"])

        # Extract session ID for potential resumption
        session_id = extract_session_id(agent.events)
        if session_id:
            db.update_agent(agent_id, session_id=session_id)

        if return_code == 0:
            logger.info("Agent %s finished (exit 0, %d turns)", agent_id, turns)
            db.update_agent(agent_id, turns_used=turns)

            if agent.agent_type == "implement":
                self._handle_implement_complete(agent)
            else:
                db.finish_agent(agent_id, status="completed")
                cleanup_worktree(agent.worktree_path)
        elif self._is_rate_limit_error(stderr_output, agent.events):
            # ── Rate limit detected — preserve worktree, don't count as failure ──
            logger.warning(
                "Agent %s hit rate limit — preserving worktree at %s for later resumption",
                agent_id, agent.worktree_path,
            )
            from datetime import datetime
            db.update_agent(agent_id, turns_used=turns)
            db.finish_agent(agent_id, status="rate_limited", error_message=stderr_output[:500])
            db.update_agent(agent_id, rate_limited_at=datetime.utcnow().isoformat())
            # Issue stays in "in_progress" — do NOT reset to pending or increment attempts.
            # The rate_limit_watcher will pick this up and resume when the limit resets.
        else:
            error_msg = stderr_output[:500] if stderr_output else f"Exit code {return_code}"
            logger.error("Agent %s failed: %s", agent_id, error_msg)
            db.finish_agent(agent_id, status="failed", error_message=error_msg)
            db.update_agent(agent_id, turns_used=turns)

            if agent.agent_type == "implement":
                db.update_issue(agent.issue_number, status="pending")

            cleanup_worktree(agent.worktree_path)

        # Call completion callback
        if self._on_agent_complete:
            try:
                self._on_agent_complete(agent)
            except Exception as e:
                logger.error("Completion callback error: %s", e)

    def _handle_implement_complete(self, agent: AgentProcess):
        """Handle completion of an implement agent — verify PR was actually created."""
        agent_id = agent.agent_id
        branch_name = f"fix/issue-{agent.issue_number}"

        # 1. Try to detect PR number from agent events
        pr_num = extract_pr_number(agent.events)

        # 2. If not found in events, check GitHub directly
        if not pr_num:
            pr_num = self._find_pr_for_branch(branch_name)

        if pr_num:
            logger.info("Agent %s created PR #%d for issue #%d", agent_id, pr_num, agent.issue_number)
            db.finish_agent(agent_id, status="completed")
            db.update_agent(agent_id, pr_number=pr_num)
            db.update_issue(agent.issue_number, status="pr_created", pr_number=pr_num)
            cleanup_worktree(agent.worktree_path)
            return

        # 3. No PR found — check if branch was at least pushed
        branch_pushed = self._is_branch_pushed(branch_name, agent.worktree_path)

        if branch_pushed:
            # Branch was pushed but no PR — agent probably ran out of turns mid-work.
            # Create the PR ourselves.
            logger.warning("Agent %s pushed branch but no PR — creating PR automatically", agent_id)
            auto_pr = self._create_pr_for_branch(branch_name, agent.issue_number)
            if auto_pr:
                db.finish_agent(agent_id, status="completed")
                db.update_agent(agent_id, pr_number=auto_pr)
                db.update_issue(agent.issue_number, status="pr_created", pr_number=auto_pr)
                cleanup_worktree(agent.worktree_path)
                return

        # 4. Check if there are local commits that weren't pushed
        has_local_commits = self._has_unpushed_commits(agent.worktree_path)

        if has_local_commits:
            # Push the branch, then create PR
            logger.warning("Agent %s has unpushed commits — pushing and creating PR", agent_id)
            push_ok = self._push_branch(branch_name, agent.worktree_path)
            if push_ok:
                auto_pr = self._create_pr_for_branch(branch_name, agent.issue_number)
                if auto_pr:
                    db.finish_agent(agent_id, status="completed")
                    db.update_agent(agent_id, pr_number=auto_pr)
                    db.update_issue(agent.issue_number, status="pr_created", pr_number=auto_pr)
                    cleanup_worktree(agent.worktree_path)
                    return

        # 5. Agent did nothing useful — mark as failed
        logger.warning("Agent %s completed but produced no commits or PR", agent_id)
        db.finish_agent(agent_id, status="failed", error_message="Agent finished without creating commits or PR")
        db.update_issue(agent.issue_number, status="pending")
        cleanup_worktree(agent.worktree_path)

    def _find_pr_for_branch(self, branch_name: str) -> int | None:
        """Check GitHub for an existing PR from this branch."""
        try:
            from orchestrator.config import GITHUB_REPO, GH_TOKEN
            result = subprocess.run(
                ["gh", "pr", "list", "--repo", GITHUB_REPO, "--head", branch_name, "--json", "number", "--limit", "1"],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "GH_TOKEN": GH_TOKEN},
            )
            if result.returncode == 0 and result.stdout.strip():
                import json
                prs = json.loads(result.stdout)
                if prs:
                    return prs[0]["number"]
        except Exception as e:
            logger.debug("Error checking PR for branch %s: %s", branch_name, e)
        return None

    def _is_branch_pushed(self, branch_name: str, worktree_path: str) -> bool:
        """Check if the branch exists on the remote."""
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--heads", "origin", branch_name],
                capture_output=True, text=True, timeout=30, cwd=worktree_path,
            )
            return branch_name in result.stdout
        except Exception:
            return False

    def _has_unpushed_commits(self, worktree_path: str) -> bool:
        """Check if the worktree has commits ahead of the base branch."""
        try:
            from orchestrator.config import BASE_BRANCH
            result = subprocess.run(
                ["git", "log", f"origin/{BASE_BRANCH}..HEAD", "--oneline"],
                capture_output=True, text=True, timeout=15, cwd=worktree_path,
            )
            return bool(result.stdout.strip())
        except Exception:
            return False

    def _push_branch(self, branch_name: str, worktree_path: str) -> bool:
        """Push the branch to origin."""
        try:
            result = subprocess.run(
                ["git", "push", "-u", "origin", branch_name],
                capture_output=True, text=True, timeout=60, cwd=worktree_path,
            )
            if result.returncode == 0:
                logger.info("Pushed branch %s", branch_name)
                return True
            logger.error("Failed to push branch %s: %s", branch_name, result.stderr)
        except Exception as e:
            logger.error("Error pushing branch %s: %s", branch_name, e)
        return False

    def _create_pr_for_branch(self, branch_name: str, issue_number: int) -> int | None:
        """Create a PR for the given branch."""
        try:
            from orchestrator.config import GITHUB_REPO, GH_TOKEN
            result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--repo", GITHUB_REPO,
                    "--head", branch_name,
                    "--title", f"Fix #{issue_number}: Auto-created from agent work",
                    "--body", f"Closes #{issue_number}\n\nThis PR was auto-created by the swarm orchestrator because the agent completed its work but didn't create a PR itself.",
                ],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "GH_TOKEN": GH_TOKEN},
            )
            if result.returncode == 0:
                import re
                match = re.search(r'pull/(\d+)', result.stdout + result.stderr)
                if match:
                    pr_num = int(match.group(1))
                    logger.info("Auto-created PR #%d for issue #%d", pr_num, issue_number)
                    return pr_num
            else:
                logger.error("Failed to create PR: %s", result.stderr)
        except Exception as e:
            logger.error("Error creating PR for branch %s: %s", branch_name, e)
        return None

    def resume_rate_limited_agent(self, agent_record: dict) -> str | None:
        """Resume an agent that was paused due to rate limiting.

        Re-uses the preserved worktree and spawns a new agent subprocess with a
        continuation prompt.  Returns new agent_id or None on failure.
        """
        if not self.can_dispatch:
            logger.info("Agent pool full, cannot resume rate-limited agent %s yet", agent_record["agent_id"])
            return None

        old_agent_id = agent_record["agent_id"]
        issue_number = agent_record["issue_number"]
        agent_type = agent_record["agent_type"]
        worktree_path = agent_record["worktree_path"]
        branch_name = agent_record["branch_name"]
        pr_number = agent_record.get("pr_number")
        old_session_id = agent_record.get("session_id")
        resume_count = (agent_record.get("resume_count") or 0) + 1

        if resume_count > MAX_RATE_LIMIT_RESUMES:
            logger.warning(
                "Agent %s has been resumed %d times (max %d) — giving up",
                old_agent_id, resume_count - 1, MAX_RATE_LIMIT_RESUMES,
            )
            db.finish_agent(old_agent_id, status="failed", error_message="Exceeded max rate-limit resumes")
            if agent_type == "implement":
                db.update_issue(issue_number, status="pending")
            cleanup_worktree(worktree_path)
            return None

        # Verify worktree still exists
        from pathlib import Path
        if not Path(worktree_path).exists():
            logger.error("Worktree %s no longer exists — cannot resume agent %s", worktree_path, old_agent_id)
            db.finish_agent(old_agent_id, status="failed", error_message="Worktree lost during rate limit wait")
            if agent_type == "implement":
                db.update_issue(issue_number, status="pending")
            return None

        # Build the appropriate resume prompt
        if agent_type == "implement":
            prompt = build_resume_implement_prompt(issue_number)
            max_turns = AGENT_MAX_TURNS_IMPLEMENT
        else:
            # Re-fetch unresolved threads at resume time for freshest data
            from orchestrator.pr_monitor import get_unresolved_threads
            unresolved_threads = get_unresolved_threads(pr_number) if pr_number else None
            prompt = build_resume_fix_review_prompt(pr_number, unresolved_threads)
            max_turns = AGENT_MAX_TURNS_FIX

        new_agent_id = f"agent-resume-{issue_number}-{int(time.time())}"

        # Build command — try --resume with session_id, fall back to --continue, or plain prompt
        cmd = ["claude"]
        if old_session_id:
            cmd += ["--resume", old_session_id, "-p", prompt]
            logger.info("Resuming session %s for agent %s", old_session_id, old_agent_id)
        else:
            cmd += ["--continue", "-p", prompt]
            logger.info("Continuing last session in worktree for agent %s", old_agent_id)

        resume_allowed_tools = "Read,Edit,Bash,Write,Glob,Grep"
        if SKILLS_ENABLED:
            resume_allowed_tools += ",Skill"

        cmd += [
            "--allowedTools", resume_allowed_tools,
            "--output-format", "stream-json",
            "--verbose",
        ]

        env = {
            **os.environ,
            "CLAUDE_CODE_OAUTH_TOKEN": CLAUDE_CODE_OAUTH_TOKEN,
            "GH_TOKEN": GH_TOKEN,
        }

        try:
            process = subprocess.Popen(
                cmd,
                cwd=worktree_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
        except Exception as e:
            logger.error("Failed to resume agent %s: %s", old_agent_id, e)
            return None

        agent_proc = AgentProcess(
            agent_id=new_agent_id,
            process=process,
            worktree_path=worktree_path,
            issue_number=issue_number,
            agent_type=agent_type,
            pr_number=pr_number,
        )

        # Mark old agent as superseded
        db.update_agent(old_agent_id, status="resumed")

        # Create new agent record
        db.create_agent(
            agent_id=new_agent_id,
            issue_number=issue_number,
            agent_type=agent_type,
            worktree_path=worktree_path,
            branch_name=branch_name,
            pr_number=pr_number,
            pid=process.pid,
        )
        db.update_agent(new_agent_id, resume_count=resume_count)

        # Update issue to point to new agent
        db.update_issue(issue_number, agent_id=new_agent_id)

        with self._lock:
            self._agents[new_agent_id] = agent_proc

        agent_proc.start_reader()
        logger.info(
            "Resumed rate-limited agent: %s -> %s (resume #%d) in %s",
            old_agent_id, new_agent_id, resume_count, worktree_path,
        )

        # Start monitoring thread
        threading.Thread(
            target=self._monitor_agent, args=(new_agent_id,), daemon=True, name=f"monitor-{new_agent_id}"
        ).start()

        return new_agent_id

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
        """Gracefully shut down the pool — let running agents continue independently.

        Since agents are spawned with start_new_session=True, they survive the
        orchestrator stopping.  On next startup, _recover_stale_agents() will
        check their PIDs and either wait for them or mark them as stale.
        """
        logger.info("Shutting down agent pool (agents will keep running)...")
        with self._lock:
            running = [a for a in self._agents.values() if a.is_running]
            if running:
                logger.info(
                    "%d agent(s) still running — they will continue independently: %s",
                    len(running),
                    ", ".join(a.agent_id for a in running),
                )
        logger.info("Agent pool shutdown complete")

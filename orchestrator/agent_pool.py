"""Manages Claude Code agent subprocess lifecycle."""

import json
import logging
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from orchestrator import db
from orchestrator.config import (
    AGENT_MAX_TURNS_FIX,
    AGENT_MAX_TURNS_IMPLEMENT,
    AGENT_TIMEOUT_SECONDS,
    CLAUDE_CODE_OAUTH_TOKEN,
    GH_TOKEN,
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    MAX_CONCURRENT_AGENTS,
    MAX_RATE_LIMIT_RESUMES,
    SKILLS_ENABLED,
    WORKSPACES_DIR,
)

AGENT_LOGS_DIR = WORKSPACES_DIR / ".agent-logs"
from orchestrator.prompts import (
    build_fix_review_prompt,
    build_implement_prompt,
    build_resume_fix_review_prompt,
    build_resume_implement_prompt,
)
from orchestrator.stream_parser import AgentEvent, extract_pr_number, extract_session_id, parse_stream_line
from orchestrator.worktree import cleanup_worktree, copy_env_files_to_worktree, create_worktree, create_worktree_for_pr, ensure_repo_updated

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


def _workspace_config(workspace: dict) -> tuple[str, str, str, str]:
    """Extract (github_repo, local_path, worktree_dir, base_branch) from workspace dict."""
    local_path = workspace["local_path"]
    worktree_dir = local_path + "-worktrees"
    return (
        workspace["github_repo"],
        local_path,
        worktree_dir,
        workspace.get("base_branch", "main"),
    )


def _ensure_log_dir():
    """Create the agent logs directory if it doesn't exist."""
    AGENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)


def agent_log_path(agent_id: str) -> Path:
    """Return the path for an agent's stream-json log file."""
    return AGENT_LOGS_DIR / f"{agent_id}.jsonl"


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
        workspace_id: str | None = None,
    ):
        self.agent_id = agent_id
        self.process = process
        self.worktree_path = worktree_path
        self.issue_number = issue_number
        self.agent_type = agent_type
        self.pr_number = pr_number
        self.workspace_id = workspace_id
        self.events: list[AgentEvent] = []
        self.started_at = time.time()
        self._reader_thread: threading.Thread | None = None
        # Store workspace config for use in completion handlers
        self._workspace: dict | None = None
        self.log_file = agent_log_path(agent_id)
        # Set to True by AgentPool.mark_externally_stopped() so _monitor_agent
        # knows to skip completion DB writes when restart_agent kills this process.
        self.stopped_externally: bool = False

    def start_reader(self):
        """Start a background thread to tail the log file for events."""
        self._reader_thread = threading.Thread(
            target=self._tail_log, daemon=True, name=f"reader-{self.agent_id}"
        )
        self._reader_thread.start()

    def _tail_log(self):
        """Tail the agent's log file and ingest events into the DB."""
        try:
            with open(self.log_file) as f:
                while True:
                    line = f.readline()
                    if line:
                        event = parse_stream_line(line)
                        if event:
                            self.events.append(event)
                            db.insert_event(self.agent_id, event.event_type, json.dumps(event.raw))
                            if event.event_type == "tool_use":
                                logger.info("[%s] %s", self.agent_id, event.summary)
                        # Persist the current file position after every line so a
                        # restart via reattach_agent can seek to the right spot.
                        db.update_agent(self.agent_id, log_offset=f.tell())
                    else:
                        # No new data — check if process exited
                        if self.process.poll() is not None:
                            # Read any final lines
                            for remaining in f:
                                event = parse_stream_line(remaining)
                                if event:
                                    self.events.append(event)
                                    db.insert_event(self.agent_id, event.event_type, json.dumps(event.raw))
                            db.update_agent(self.agent_id, log_offset=f.tell())
                            break
                        time.sleep(0.5)
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
        # Agent IDs that were stopped externally (via restart_agent) so that
        # _monitor_agent / _monitor_pid skip their completion DB writes.
        self._stopped_agent_ids: set[str] = set()

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

    def mark_externally_stopped(self, agent_id: str) -> None:
        """Signal that an agent is being stopped externally (e.g. via restart_agent).

        Must be called *before* sending SIGTERM so that _monitor_agent and
        _monitor_pid see the flag before they process the process exit and
        skip their own DB completion writes, preventing a race where the
        monitor thread overwrites the 'stopped' status set by restart_agent.
        """
        with self._lock:
            self._stopped_agent_ids.add(agent_id)
            agent = self._agents.get(agent_id)
            if agent:
                agent.stopped_externally = True

    def dispatch_implement(self, issue_number: int, workspace: dict | None = None) -> str | None:
        """Dispatch an agent to implement an issue. Returns agent_id or None if pool is full."""
        if not self.can_dispatch:
            logger.warning("Agent pool full (%d/%d), cannot dispatch", self.active_count, MAX_CONCURRENT_AGENTS)
            return None

        github_repo, local_path, worktree_dir, base_branch = _workspace_config(workspace)
        workspace_id = workspace["id"] if workspace else None
        agent_id = f"agent-issue-{issue_number}-{int(time.time())}"
        branch_name = f"fix/issue-{issue_number}"

        try:
            ensure_repo_updated(repo_path=local_path, base_branch=base_branch)
            worktree_path = create_worktree(
                issue_number,
                repo_path=local_path,
                worktree_dir=worktree_dir,
                base_branch=base_branch,
            )
        except Exception as e:
            logger.error("Failed to create worktree for issue #%d: %s", issue_number, e)
            return None

        # Copy .env files from the workspace into the worktree (they are gitignored)
        copy_env_files_to_worktree(worktree_path, local_path, workspace_id=workspace.get("id") if workspace else None)

        prompt = build_implement_prompt(issue_number, github_repo=github_repo, target_repo_path=local_path)

        try:
            agent_proc = self._spawn_agent(
                agent_id=agent_id,
                prompt=prompt,
                worktree_path=worktree_path,
                max_turns=AGENT_MAX_TURNS_IMPLEMENT,
                issue_number=issue_number,
                agent_type="implement",
                workspace_id=workspace_id,
            )
            agent_proc._workspace = workspace
        except Exception as e:
            logger.error("Failed to spawn agent for issue #%d: %s", issue_number, e)
            cleanup_worktree(worktree_path, repo_path=local_path)
            return None

        # Record in DB
        db.create_agent(
            agent_id=agent_id,
            issue_number=issue_number,
            agent_type="implement",
            worktree_path=worktree_path,
            branch_name=branch_name,
            pid=agent_proc.process.pid,
            workspace_id=workspace_id,
        )
        issue = db.get_issue(issue_number, workspace_id=workspace_id)
        db.update_issue(issue_number, workspace_id=workspace_id, status="in_progress", agent_id=agent_id, attempts=issue["attempts"] + 1)

        with self._lock:
            self._agents[agent_id] = agent_proc

        agent_proc.start_reader()
        logger.info("Dispatched agent %s for issue #%d", agent_id, issue_number)

        # Start monitoring thread
        threading.Thread(
            target=self._monitor_agent, args=(agent_id,), daemon=True, name=f"monitor-{agent_id}"
        ).start()

        return agent_id

    def dispatch_fix_review(self, pr_number: int, branch_name: str, issue_number: int, workspace: dict | None = None, unresolved_threads: list[dict] | None = None) -> str | None:
        """Dispatch an agent to fix PR review comments. Returns agent_id or None."""
        if not self.can_dispatch:
            logger.warning("Agent pool full, cannot dispatch fix agent")
            return None

        github_repo, local_path, worktree_dir, base_branch = _workspace_config(workspace)
        workspace_id = workspace["id"] if workspace else None
        agent_id = f"agent-pr-fix-{pr_number}-{int(time.time())}"

        try:
            ensure_repo_updated(repo_path=local_path, base_branch=base_branch)
            worktree_path = create_worktree_for_pr(
                pr_number, branch_name,
                repo_path=local_path,
                worktree_dir=worktree_dir,
            )
        except Exception as e:
            logger.error("Failed to create worktree for PR #%d: %s", pr_number, e)
            return None

        # Copy .env files from the workspace into the worktree (they are gitignored)
        copy_env_files_to_worktree(worktree_path, local_path, workspace_id=workspace.get("id") if workspace else None)

        prompt = build_fix_review_prompt(pr_number, unresolved_threads, github_repo=github_repo, target_repo_path=local_path)

        try:
            agent_proc = self._spawn_agent(
                agent_id=agent_id,
                prompt=prompt,
                worktree_path=worktree_path,
                max_turns=AGENT_MAX_TURNS_FIX,
                issue_number=issue_number,
                agent_type="fix_review",
                pr_number=pr_number,
                workspace_id=workspace_id,
            )
            agent_proc._workspace = workspace
        except Exception as e:
            logger.error("Failed to spawn fix agent for PR #%d: %s", pr_number, e)
            cleanup_worktree(worktree_path, repo_path=local_path)
            return None

        db.create_agent(
            agent_id=agent_id,
            issue_number=issue_number,
            pr_number=pr_number,
            agent_type="fix_review",
            worktree_path=worktree_path,
            branch_name=branch_name,
            pid=agent_proc.process.pid,
            workspace_id=workspace_id,
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
        workspace_id: str | None = None,
    ) -> AgentProcess:
        """Spawn a claude -p subprocess."""
        allowed_tools = "Read,Edit,Bash,Write,Glob,Grep,WebFetch,WebSearch,Agent,TodoWrite,NotebookEdit"
        if SKILLS_ENABLED:
            allowed_tools += ",Skill"

        cmd = [
            "stdbuf", "-oL",
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

        # Set git author identity so commits are attributed to a real GitHub user
        # (avoids Vercel / deploy rejections for unknown commit authors).
        if GIT_AUTHOR_NAME:
            env["GIT_AUTHOR_NAME"] = GIT_AUTHOR_NAME
            env["GIT_COMMITTER_NAME"] = GIT_AUTHOR_NAME
        if GIT_AUTHOR_EMAIL:
            env["GIT_AUTHOR_EMAIL"] = GIT_AUTHOR_EMAIL
            env["GIT_COMMITTER_EMAIL"] = GIT_AUTHOR_EMAIL

        # Inject workspace-specific env vars
        if workspace_id:
            ws_env = db.get_workspace_env(workspace_id)
            env.update(ws_env)

        _ensure_log_dir()
        log_file = agent_log_path(agent_id)
        stdout_file = open(log_file, "a")
        try:
            logger.info("Spawning agent %s in %s (PID will be independent)", agent_id, worktree_path)
            process = subprocess.Popen(
                cmd,
                cwd=worktree_path,
                stdout=stdout_file,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,  # Agent survives orchestrator restart
            )
        finally:
            # Close our copy of the file descriptor — the child process keeps its own
            stdout_file.close()

        return AgentProcess(
            agent_id=agent_id,
            process=process,
            worktree_path=worktree_path,
            issue_number=issue_number,
            agent_type=agent_type,
            pr_number=pr_number,
            workspace_id=workspace_id,
        )

    @staticmethod
    def _is_rate_limit_error(stderr_output: str, events: list[AgentEvent]) -> bool:
        """Check if the agent failure was caused by a rate/usage limit."""
        text = stderr_output.lower()
        for pattern in _RATE_LIMIT_PATTERNS:
            if pattern in text:
                return True
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

        # Resolve repo_path for worktree cleanup
        repo_path = agent._workspace["local_path"] if agent._workspace else None

        while agent.is_running:
            if agent.is_timed_out:
                logger.warning("Agent %s timed out after %ds, killing", agent_id, AGENT_TIMEOUT_SECONDS)
                agent.kill()
                db.finish_agent(agent_id, status="timeout", error_message="Agent exceeded timeout")
                cleanup_worktree(agent.worktree_path, repo_path=repo_path)
                return
            time.sleep(5)

        # Agent finished — skip completion logic if externally stopped to avoid
        # racing with restart_agent's own DB writes.
        if agent.stopped_externally:
            logger.info("Agent %s was externally stopped — skipping completion logic", agent_id)
            if self._on_agent_complete:
                try:
                    self._on_agent_complete(agent)
                except Exception as e:
                    logger.error("Completion callback error: %s", e)
            return

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
                cleanup_worktree(agent.worktree_path, repo_path=repo_path)
        elif self._is_rate_limit_error(stderr_output, agent.events):
            logger.warning(
                "Agent %s hit rate limit — preserving worktree at %s for later resumption",
                agent_id, agent.worktree_path,
            )
            from datetime import datetime
            db.update_agent(agent_id, turns_used=turns)
            db.finish_agent(agent_id, status="rate_limited", error_message=stderr_output[:500])
            db.update_agent(agent_id, rate_limited_at=datetime.utcnow().isoformat())
        else:
            error_msg = stderr_output[:500] if stderr_output else f"Exit code {return_code}"
            logger.error("Agent %s failed: %s", agent_id, error_msg)
            db.finish_agent(agent_id, status="failed", error_message=error_msg)
            db.update_agent(agent_id, turns_used=turns)

            if agent.agent_type == "implement":
                db.update_issue(agent.issue_number, workspace_id=agent.workspace_id, status="pending")

            cleanup_worktree(agent.worktree_path, repo_path=repo_path)

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
        workspace = agent._workspace
        github_repo = workspace["github_repo"]
        repo_path = workspace["local_path"]

        # 1. Try to detect PR number from agent events
        pr_num = extract_pr_number(agent.events)

        # 2. If not found in events, check GitHub directly
        if not pr_num:
            pr_num = self._find_pr_for_branch(branch_name, github_repo=github_repo)

        if pr_num:
            logger.info("Agent %s created PR #%d for issue #%d", agent_id, pr_num, agent.issue_number)
            db.finish_agent(agent_id, status="completed")
            db.update_agent(agent_id, pr_number=pr_num)
            db.update_issue(agent.issue_number, workspace_id=agent.workspace_id, status="pr_created", pr_number=pr_num)
            cleanup_worktree(agent.worktree_path, repo_path=repo_path)
            return

        # 3. No PR found — check if branch was at least pushed
        branch_pushed = self._is_branch_pushed(branch_name, agent.worktree_path)

        if branch_pushed:
            logger.warning("Agent %s pushed branch but no PR — creating PR automatically", agent_id)
            auto_pr = self._create_pr_for_branch(branch_name, agent.issue_number, github_repo=github_repo)
            if auto_pr:
                db.finish_agent(agent_id, status="completed")
                db.update_agent(agent_id, pr_number=auto_pr)
                db.update_issue(agent.issue_number, workspace_id=agent.workspace_id, status="pr_created", pr_number=auto_pr)
                cleanup_worktree(agent.worktree_path, repo_path=repo_path)
                return

        # 4. Check if there are local commits that weren't pushed
        base_branch = workspace.get("base_branch", "main") if workspace else "main"
        has_local_commits = self._has_unpushed_commits(agent.worktree_path, base_branch=base_branch)

        if has_local_commits:
            logger.warning("Agent %s has unpushed commits — pushing and creating PR", agent_id)
            push_ok = self._push_branch(branch_name, agent.worktree_path)
            if push_ok:
                auto_pr = self._create_pr_for_branch(branch_name, agent.issue_number, github_repo=github_repo)
                if auto_pr:
                    db.finish_agent(agent_id, status="completed")
                    db.update_agent(agent_id, pr_number=auto_pr)
                    db.update_issue(agent.issue_number, workspace_id=agent.workspace_id, status="pr_created", pr_number=auto_pr)
                    cleanup_worktree(agent.worktree_path, repo_path=repo_path)
                    return

        # 5. Agent did nothing useful — mark as failed
        logger.warning("Agent %s completed but produced no commits or PR", agent_id)
        db.finish_agent(agent_id, status="failed", error_message="Agent finished without creating commits or PR")
        db.update_issue(agent.issue_number, workspace_id=agent.workspace_id, status="pending")
        cleanup_worktree(agent.worktree_path, repo_path=repo_path)

    def _find_pr_for_branch(self, branch_name: str, github_repo: str | None = None) -> int | None:
        """Check GitHub for an existing PR from this branch."""
        repo = github_repo
        try:
            result = subprocess.run(
                ["gh", "pr", "list", "--repo", repo, "--head", branch_name, "--json", "number", "--limit", "1"],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "GH_TOKEN": GH_TOKEN},
            )
            if result.returncode == 0 and result.stdout.strip():
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

    def _has_unpushed_commits(self, worktree_path: str, base_branch: str = "main") -> bool:
        """Check if the worktree has commits ahead of the base branch."""
        try:
            result = subprocess.run(
                ["git", "log", f"origin/{base_branch}..HEAD", "--oneline"],
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

    def _create_pr_for_branch(self, branch_name: str, issue_number: int, github_repo: str | None = None) -> int | None:
        """Create a PR for the given branch."""
        repo = github_repo
        try:
            result = subprocess.run(
                [
                    "gh", "pr", "create",
                    "--repo", repo,
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
        """Resume an agent that was paused due to rate limiting."""
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
        workspace_id = agent_record.get("workspace_id")

        # Resolve repo_path for worktree cleanup
        workspace = db.get_workspace(workspace_id) if workspace_id else None
        repo_path = workspace["local_path"] if workspace else None

        if resume_count > MAX_RATE_LIMIT_RESUMES:
            logger.warning(
                "Agent %s has been resumed %d times (max %d) — giving up",
                old_agent_id, resume_count - 1, MAX_RATE_LIMIT_RESUMES,
            )
            db.finish_agent(old_agent_id, status="failed", error_message="Exceeded max rate-limit resumes")
            if agent_type == "implement":
                db.update_issue(issue_number, workspace_id=workspace_id, status="pending")
            cleanup_worktree(worktree_path, repo_path=repo_path)
            return None

        # Verify worktree still exists
        if not Path(worktree_path).exists():
            logger.error("Worktree %s no longer exists — cannot resume agent %s", worktree_path, old_agent_id)
            db.finish_agent(old_agent_id, status="failed", error_message="Worktree lost during rate limit wait")
            if agent_type == "implement":
                db.update_issue(issue_number, workspace_id=workspace_id, status="pending")
            return None

        # Resolve workspace for prompt building
        workspace = db.get_workspace(workspace_id) if workspace_id else None
        github_repo = workspace["github_repo"] if workspace else None
        local_path = workspace["local_path"] if workspace else None

        # Build the appropriate resume prompt
        if agent_type == "implement":
            prompt = build_resume_implement_prompt(issue_number, github_repo=github_repo, target_repo_path=local_path)
            max_turns = AGENT_MAX_TURNS_IMPLEMENT
        else:
            from orchestrator.pr_monitor import get_unresolved_threads
            unresolved_threads = get_unresolved_threads(pr_number, github_repo=github_repo) if pr_number else None
            prompt = build_resume_fix_review_prompt(pr_number, unresolved_threads, github_repo=github_repo, target_repo_path=local_path)
            max_turns = AGENT_MAX_TURNS_FIX

        new_agent_id = f"agent-resume-{issue_number}-{time.monotonic_ns()}"

        # Build command
        cmd = ["stdbuf", "-oL", "claude"]
        if old_session_id:
            cmd += ["--resume", old_session_id, "-p", prompt]
            logger.info("Resuming session %s for agent %s", old_session_id, old_agent_id)
        else:
            cmd += ["--continue", "-p", prompt]
            logger.info("Continuing last session in worktree for agent %s", old_agent_id)

        resume_allowed_tools = "Read,Edit,Bash,Write,Glob,Grep,WebFetch,WebSearch,Agent,TodoWrite,NotebookEdit"
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

        if GIT_AUTHOR_NAME:
            env["GIT_AUTHOR_NAME"] = GIT_AUTHOR_NAME
            env["GIT_COMMITTER_NAME"] = GIT_AUTHOR_NAME
        if GIT_AUTHOR_EMAIL:
            env["GIT_AUTHOR_EMAIL"] = GIT_AUTHOR_EMAIL
            env["GIT_COMMITTER_EMAIL"] = GIT_AUTHOR_EMAIL

        # Inject workspace-specific env vars
        if workspace_id:
            ws_env = db.get_workspace_env(workspace_id)
            env.update(ws_env)

        try:
            _ensure_log_dir()
            resume_log_file = agent_log_path(new_agent_id)
            resume_stdout = open(resume_log_file, "a")
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=worktree_path,
                    stdout=resume_stdout,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                    start_new_session=True,
                )
            finally:
                resume_stdout.close()
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
            workspace_id=workspace_id,
        )
        agent_proc._workspace = workspace

        # Mark old agent as superseded (but keep its log file)
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
            workspace_id=workspace_id,
        )
        db.update_agent(new_agent_id, resume_count=resume_count)

        # Update issue to point to new agent
        db.update_issue(issue_number, workspace_id=workspace_id, agent_id=new_agent_id)

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
                    "workspace_id": agent.workspace_id,
                    "recent_events": [
                        {"type": e.event_type, "summary": e.summary}
                        for e in recent_events
                    ],
                })
            return results

    # ------------------------------------------------------------------
    # Reattach surviving agents after orchestrator restart
    # ------------------------------------------------------------------

    def reattach_agent(self, agent_record: dict, workspace: dict | None = None):
        """Reattach a monitor thread to an agent that survived a restart.

        Starts a log-file tailer to continue ingesting stream events, and
        a PID monitor to detect when the agent exits.
        """
        agent_id = agent_record["agent_id"]
        pid = agent_record["pid"]
        issue_number = agent_record["issue_number"]
        agent_type = agent_record.get("agent_type", "implement")
        worktree_path = agent_record.get("worktree_path", "")
        pr_number = agent_record.get("pr_number")
        workspace_id = agent_record.get("workspace_id")

        logger.info(
            "Reattaching monitor for agent %s (PID %d, issue #%s)",
            agent_id, pid, issue_number,
        )

        # Start log file tailer to continue ingesting events
        log_file = agent_log_path(agent_id)
        tailer_done = threading.Event()
        if log_file.exists():
            # Use the persisted byte offset so the tailer resumes from the exact
            # position it last reached.  Falling back to 0 makes the tailer
            # re-read the whole file (safe, though slower) when no offset has
            # been stored yet (e.g. for agents started before this migration).
            log_offset = agent_record.get("log_offset") or 0
            threading.Thread(
                target=self._tail_log_file,
                args=(agent_id, log_file, pid, log_offset, tailer_done),
                daemon=True,
                name=f"tail-{agent_id}",
            ).start()
        else:
            # No log file — signal immediately so the monitor doesn't wait
            tailer_done.set()

        # Parse the agent's original start time from the DB record so that
        # _monitor_pid uses the true elapsed time rather than resetting the
        # timeout clock to the moment of reattachment.
        started_at_str = agent_record.get("started_at")
        try:
            agent_started_at = datetime.fromisoformat(
                started_at_str.replace(" ", "T")
            ).replace(tzinfo=timezone.utc).timestamp()
        except (ValueError, AttributeError, TypeError):
            agent_started_at = time.time()

        threading.Thread(
            target=self._monitor_pid,
            args=(agent_id, pid, issue_number, agent_type, worktree_path, pr_number, workspace_id, workspace, tailer_done, agent_started_at),
            daemon=True,
            name=f"monitor-reattach-{agent_id}",
        ).start()

    def _tail_log_file(self, agent_id: str, log_file: Path, pid: int, log_offset: int = 0, done_event: threading.Event | None = None):
        """Tail an agent's log file and ingest new events into the DB.

        Uses a byte offset (not a line count) to resume from the correct position
        after an orchestrator restart.  Tracking total bytes consumed rather than
        only successfully-stored events avoids re-processing lines that were read
        but not stored (e.g. non-JSON output or lines parse_stream_line ignores).
        """
        logger.info("Tailing log file for agent %s from offset %d: %s", agent_id, log_offset, log_file)
        try:
            with open(log_file) as f:
                # Seek to the last processed byte offset so we skip lines that
                # have already been consumed (both stored and non-stored).
                if log_offset > 0:
                    f.seek(log_offset)

                # Now tail for new lines
                while True:
                    line = f.readline()
                    if line:
                        event = parse_stream_line(line)
                        if event:
                            db.insert_event(agent_id, event.event_type, json.dumps(event.raw))
                            if event.event_type == "tool_use":
                                logger.info("[%s] %s", agent_id, event.summary)
                        # Persist the current file position after every line
                        # (stored or not) so a restart can seek to the right spot.
                        db.update_agent(agent_id, log_offset=f.tell())
                    else:
                        # No new data — check if process is still alive
                        try:
                            os.kill(pid, 0)
                        except (OSError, ProcessLookupError):
                            # Process is dead, read any remaining lines
                            for remaining in f:
                                event = parse_stream_line(remaining)
                                if event:
                                    db.insert_event(agent_id, event.event_type, json.dumps(event.raw))
                            db.update_agent(agent_id, log_offset=f.tell())
                            break
                        time.sleep(1)
        except Exception as e:
            logger.error("[%s] Log tailer error: %s", agent_id, e)
        finally:
            if done_event is not None:
                done_event.set()

    def _monitor_pid(
        self,
        agent_id: str,
        pid: int,
        issue_number: int,
        agent_type: str,
        worktree_path: str,
        pr_number: int | None,
        workspace_id: str | None,
        workspace: dict | None,
        tailer_done: threading.Event | None = None,
        started_at: float | None = None,
    ):
        """Poll a PID until it exits, then handle agent completion."""
        if started_at is None:
            started_at = time.time()

        while True:
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError):
                # Process has exited
                break

            elapsed = time.time() - started_at
            if elapsed > AGENT_TIMEOUT_SECONDS:
                logger.warning(
                    "Reattached agent %s (PID %d) timed out after %ds, killing",
                    agent_id, pid, AGENT_TIMEOUT_SECONDS,
                )
                try:
                    os.kill(pid, signal.SIGTERM)
                    time.sleep(5)
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        pass
                except (OSError, ProcessLookupError):
                    pass
                turns = db.get_agent_turn_count(agent_id)
                if turns:
                    db.update_agent(agent_id, turns_used=turns)
                db.finish_agent(agent_id, status="timeout", error_message="Agent exceeded timeout (reattached)")
                db.update_issue(issue_number, workspace_id=workspace_id, status="pending")
                repo_path = workspace.get("local_path") if workspace else None
                if worktree_path and repo_path:
                    cleanup_worktree(worktree_path, repo_path=repo_path)
                elif worktree_path and not repo_path:
                    logger.warning(
                        "Skipping git worktree deregistration for agent %s: workspace is None, "
                        "worktree_path=%s may be orphaned",
                        agent_id,
                        worktree_path,
                    )
                return

            time.sleep(5)

        # PID exited — handle completion
        logger.info("Reattached agent %s (PID %d) has exited", agent_id, pid)

        # Skip completion logic if this agent was externally stopped (e.g. via
        # restart_agent) to avoid overwriting the DB state set by the caller.
        with self._lock:
            externally_stopped = agent_id in self._stopped_agent_ids
            self._stopped_agent_ids.discard(agent_id)
        if externally_stopped:
            logger.info("Reattached agent %s was externally stopped — skipping completion logic", agent_id)
            return

        # Wait for the log tailer to finish ingesting remaining events before
        # reading the turn count so we get a complete picture.
        if tailer_done is not None:
            tailer_done.wait(timeout=30)

        # Update turns_used from DB events (reattached agents don't track in-memory)
        turns = db.get_agent_turn_count(agent_id)
        if turns:
            db.update_agent(agent_id, turns_used=turns)

        repo_path = workspace.get("local_path") if workspace else None
        github_repo = workspace.get("github_repo") if workspace else None

        if agent_type == "implement":
            # Check if a PR was created
            branch_name = f"fix/issue-{issue_number}"
            found_pr = self._find_pr_for_branch(branch_name, github_repo=github_repo) if github_repo else None

            if found_pr:
                logger.info("Reattached agent %s created PR #%d for issue #%d", agent_id, found_pr, issue_number)
                db.finish_agent(agent_id, status="completed")
                db.update_agent(agent_id, pr_number=found_pr)
                db.update_issue(issue_number, workspace_id=workspace_id, status="pr_created", pr_number=found_pr)
            elif worktree_path and self._is_branch_pushed(branch_name, worktree_path):
                logger.warning("Reattached agent %s pushed branch but no PR — creating automatically", agent_id)
                auto_pr = self._create_pr_for_branch(branch_name, issue_number, github_repo=github_repo)
                if auto_pr:
                    db.finish_agent(agent_id, status="completed")
                    db.update_agent(agent_id, pr_number=auto_pr)
                    db.update_issue(issue_number, workspace_id=workspace_id, status="pr_created", pr_number=auto_pr)
                else:
                    db.finish_agent(agent_id, status="failed", error_message="Agent exited without creating PR (reattached)")
                    db.update_issue(issue_number, workspace_id=workspace_id, status="pending")
            else:
                # Can't tell if it succeeded or failed without stdout — check for unpushed commits
                base_branch = workspace.get("base_branch", "main") if workspace else "main"
                if worktree_path and self._has_unpushed_commits(worktree_path, base_branch=base_branch):
                    logger.warning("Reattached agent %s has unpushed commits — pushing and creating PR", agent_id)
                    if self._push_branch(branch_name, worktree_path):
                        auto_pr = self._create_pr_for_branch(branch_name, issue_number, github_repo=github_repo)
                        if auto_pr:
                            db.finish_agent(agent_id, status="completed")
                            db.update_agent(agent_id, pr_number=auto_pr)
                            db.update_issue(issue_number, workspace_id=workspace_id, status="pr_created", pr_number=auto_pr)
                            if worktree_path and repo_path:
                                cleanup_worktree(worktree_path, repo_path=repo_path)
                            elif worktree_path:
                                logger.warning("repo_path is None for agent %s — skipping git worktree deregistration", agent_id)
                            return

                db.finish_agent(agent_id, status="failed", error_message="Agent exited without creating PR (reattached)")
                db.update_issue(issue_number, workspace_id=workspace_id, status="pending")
        else:
            # fix_review agent — just mark as completed (can't read stderr to determine status)
            db.finish_agent(agent_id, status="completed")
            db.update_issue(issue_number, workspace_id=workspace_id, status="pr_created")

        if worktree_path and repo_path:
            cleanup_worktree(worktree_path, repo_path=repo_path)
        elif worktree_path:
            logger.warning("repo_path is None for agent %s — skipping git worktree deregistration", agent_id)

    def shutdown(self):
        """Gracefully shut down the pool — let running agents continue independently."""
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

"""Planning agent — analyzes codebase and produces implementation plans."""

import json
import logging
import os
import re
import subprocess
import threading

from orchestrator import db
from orchestrator.config import CLAUDE_CODE_OAUTH_TOKEN, GH_TOKEN, ISSUE_LABEL
from orchestrator.prompts import build_planning_prompt

logger = logging.getLogger(__name__)

# Tracks active planning subprocesses: session_id -> subprocess.Popen
_active: dict[str, subprocess.Popen] = {}
# Sessions that have been claimed for a new start but whose subprocess has not
# yet been registered in _active.  Both sets are protected by _active_lock.
_starting: set[str] = set()
# Sessions that were externally cancelled via cancel_planning() while their
# subprocess was already running.  _run_planning_agent checks this set after
# the finally block and skips the post-run DB status update so that the
# cancel_planning() write of status='active' is never overwritten.
_cancelled: set[str] = set()
_active_lock = threading.Lock()


def is_generating(session_id: str) -> bool:
    """Return True if a planning subprocess is currently running for this session."""
    with _active_lock:
        if session_id in _starting:
            return True
        proc = _active.get(session_id)
    if proc is None:
        return False
    return proc.poll() is None


def start_planning(session_id: str, workspace_id: str, user_message: str) -> str:
    """Add user message, build prompt, and launch background planning thread.

    If the session already has messages (refinement), the full conversation
    history is included in the prompt.

    Returns a status string indicating the outcome:
      - ``"ok"``                  — planning was successfully started.
      - ``"already_generating"``  — a generation is already in progress.
      - ``"workspace_not_found"`` — the workspace no longer exists.

    The check and the claim are performed atomically under _active_lock to
    eliminate the TOCTOU race between callers that call is_generating() and
    start_planning() separately.
    """
    # Atomically check and claim the session slot before doing any work.
    with _active_lock:
        proc = _active.get(session_id)
        if session_id in _starting or (proc is not None and proc.poll() is None):
            return "already_generating"
        _starting.add(session_id)

    try:
        workspace = db.get_workspace(workspace_id)
        if not workspace:
            with _active_lock:
                _starting.discard(session_id)
            db.update_planning_session(session_id, status="error")
            logger.error("Planning session %s: workspace %s not found", session_id, workspace_id)
            return "workspace_not_found"

        # Build conversation history before adding the new user message
        history_messages = db.get_planning_messages(session_id)
        history = [{"role": m["role"], "content": m["content"]} for m in history_messages]

        # Persist user message (after workspace validation so no orphaned message on failure)
        db.add_planning_message(session_id, "user", user_message)

        prompt = build_planning_prompt(user_message, conversation_history=history if history else None)

        db.update_planning_session(session_id, status="generating")

        thread = threading.Thread(
            target=_run_planning_agent,
            args=(session_id, workspace, prompt),
            daemon=True,
            name=f"planner-{session_id[:8]}",
        )
        thread.start()
    except Exception:
        with _active_lock:
            _starting.discard(session_id)
        try:
            db.update_planning_session(session_id, status="error")
        except Exception:
            pass
        logger.exception("Failed to start planning for session %s", session_id)
        raise
    return "ok"


def _run_planning_agent(session_id: str, workspace: dict, prompt: str):
    """Spawn claude -p in the workspace directory to produce a plan.

    Uses Read, Glob, Grep only — fully read-only, no worktree needed.
    """
    # Outermost guard: ensure _starting sentinel is always released even if an
    # exception occurs before the inner try/finally block that normally handles
    # this cleanup (e.g. a KeyError on the workspace dict or a DB failure).
    try:
        _run_planning_agent_impl(session_id, workspace, prompt)
    finally:
        with _active_lock:
            _starting.discard(session_id)


def _run_planning_agent_impl(session_id: str, workspace: dict, prompt: str):
    """Inner implementation — called exclusively from _run_planning_agent."""
    local_path = workspace["local_path"]
    workspace_id = workspace["id"]

    cmd = [
        "claude", "-p", prompt,
        "--allowedTools", "Read,Glob,Grep",
        "--output-format", "stream-json",
        "--verbose",
    ]

    env = {
        **os.environ,
        "CLAUDE_CODE_OAUTH_TOKEN": CLAUDE_CODE_OAUTH_TOKEN,
        "GH_TOKEN": GH_TOKEN,
    }

    # Inject workspace-specific env vars
    ws_env = db.get_workspace_env(workspace_id)
    env.update(ws_env)

    logger.info("Starting planning agent for session %s in %s", session_id, local_path)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=local_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except Exception as e:
        logger.error("Failed to spawn planning agent for session %s: %s", session_id, e)
        with _active_lock:
            _starting.discard(session_id)
            _cancelled.discard(session_id)
        db.update_planning_session(session_id, status="error")
        return

    # Replace the _starting sentinel with the actual process atomically so that
    # is_generating() always sees a consistent state.
    # If cancel_planning() was called while we were spawning, session_id will
    # no longer be in _starting — detect that and abort rather than registering
    # a process the caller believes was already cancelled.
    with _active_lock:
        cancelled = session_id not in _starting
        _starting.discard(session_id)
        if not cancelled:
            _active[session_id] = process

    if cancelled:
        logger.info("Planning session %s was cancelled during spawn; terminating process", session_id)
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Process for session %s did not exit after SIGKILL", session_id)
        db.update_planning_session(session_id, status="active")
        with _active_lock:
            _cancelled.discard(session_id)
        return

    plan_text: str | None = None
    # Accumulates text across ALL assistant messages for live draft display.
    accumulated_draft: list[str] = []

    # Drain stderr in a background thread to prevent pipe buffer deadlock.
    # The subprocess emits significant output on stderr (due to --verbose), and
    # leaving stderr unread while blocking on stdout causes a classic deadlock
    # when the 64 KB OS pipe buffer fills up.
    stderr_chunks: list[str] = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_chunks.extend(process.stderr.readlines()),
        daemon=True,
        name=f"stderr-{session_id[:8]}",
    )
    stderr_thread.start()

    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")
            if msg_type == "result":
                result_data = data.get("result", "")
                if isinstance(result_data, str):
                    plan_text = result_data
                elif isinstance(result_data, dict):
                    plan_text = json.dumps(result_data)
            elif msg_type == "assistant":
                # Capture the last assistant text block as fallback
                content_blocks = data.get("message", {}).get("content", [])
                text_parts = []
                tool_use_summaries = []
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")
                    if block_type == "text":
                        text = block.get("text", "")
                        text_parts.append(text)
                    elif block_type == "tool_use":
                        tool_name = block.get("name", "tool")
                        tool_input = block.get("input", {})
                        if tool_name == "Read":
                            summary = f"Reading {tool_input.get('file_path', '?')}"
                        elif tool_name == "Glob":
                            summary = f"Searching for {tool_input.get('pattern', '?')}"
                        elif tool_name == "Grep":
                            pattern = tool_input.get('pattern', '?')
                            path = tool_input.get('path', '')
                            summary = f"Grepping for '{pattern}'" + (f" in {path}" if path else "")
                        else:
                            summary = f"Using {tool_name}"
                        tool_use_summaries.append(summary)
                # Emit intermediate reasoning text before tool-use events so the
                # chat UI shows Claude's thinking inline (like Claude.ai / ChatGPT).
                if text_parts and tool_use_summaries:
                    reasoning = " ".join(t.strip() for t in text_parts if t.strip())
                    if reasoning:
                        if len(reasoning) > 200:
                            reasoning = reasoning[:197] + "..."
                        try:
                            db.insert_planning_event(session_id, "thinking", reasoning)
                        except Exception:
                            pass
                # Emit each tool_use call as a separate step event
                for summary in tool_use_summaries:
                    try:
                        db.insert_planning_event(session_id, "tool_use", summary)
                    except Exception:
                        pass
                if text_parts:
                    plan_text = "\n".join(text_parts)
                    # Accumulate across all assistant turns and emit a live draft event
                    # so the UI can show the plan growing in real-time.
                    accumulated_draft.append(plan_text)
                    draft_text = "\n\n".join(accumulated_draft).strip()
                    if draft_text:
                        try:
                            db.insert_planning_event(session_id, "draft", draft_text)
                        except Exception:
                            pass
            elif msg_type == "user":
                # Capture tool results so the UI can show what Claude found
                content_blocks = data.get("message", {}).get("content", [])
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        content = block.get("content", [])
                        if isinstance(content, str):
                            line_count = content.count("\n") + 1 if content else 0
                            result_summary = f"Got {line_count} line{'s' if line_count != 1 else ''}"
                        elif isinstance(content, list):
                            total_lines = 0
                            for item in content:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    text = item.get("text", "")
                                    total_lines += text.count("\n") + 1 if text else 0
                            result_summary = f"Got {total_lines} line{'s' if total_lines != 1 else ''}"
                        else:
                            result_summary = "Got result"
                        try:
                            db.insert_planning_event(session_id, "tool_result", result_summary)
                        except Exception:
                            pass

        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            logger.warning(
                "Process for session %s did not exit after 60s; killing", session_id
            )
            process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Process for session %s did not exit after SIGKILL", session_id
                )
        stderr_thread.join()
    except Exception as e:
        logger.error("Planning agent stream error for session %s: %s", session_id, e)
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Process for session %s did not exit after SIGKILL", session_id)
        stderr_thread.join(timeout=5.0)
        if stderr_thread.is_alive():
            logger.warning(
                "stderr thread for session %s did not finish after SIGKILL; "
                "process may still be alive — session may need server restart to recover",
                session_id,
            )
    finally:
        with _active_lock:
            _starting.discard(session_id)
            _active.pop(session_id, None)

    # If cancel_planning() terminated this subprocess externally, skip the
    # post-run status update entirely.  cancel_planning() is responsible for
    # writing status='active' and has already done so (or will do so); writing
    # 'error' or a stale 'active' here would race with and potentially
    # overwrite that update.
    with _active_lock:
        was_cancelled = session_id in _cancelled
        _cancelled.discard(session_id)

    if was_cancelled:
        # Perform the cancellation status update here (inside the thread) rather
        # than in cancel_planning() to eliminate the TOCTOU race: cancel_planning
        # only waits for the subprocess to exit, but this thread may still be
        # running (draining stderr, executing finally).  Writing status here
        # ensures the final DB state is set after all thread cleanup is done.
        logger.info("Planning session %s was cancelled externally", session_id)
        try:
            db.update_planning_session(session_id, status="active")
        except Exception:
            pass
        return

    return_code = process.returncode
    # Wrap all final DB writes in a try/except so they degrade gracefully when
    # the session row has already been deleted (e.g. delete_planning_session was
    # called while the background thread was still running).
    try:
        if return_code == 0 and plan_text:
            db.add_planning_message(session_id, "assistant", plan_text)
            db.update_planning_session(session_id, status="active")
            logger.info("Planning agent completed for session %s", session_id)
        else:
            stderr_output = "".join(stderr_chunks)
            error_detail = stderr_output[:300] if stderr_output else f"Exit code {return_code}"
            logger.error("Planning agent failed for session %s: %s", session_id, error_detail)
            # Store whatever partial plan we got, or an error message
            if plan_text:
                db.add_planning_message(session_id, "assistant", plan_text)
                db.update_planning_session(session_id, status="active")
            else:
                db.update_planning_session(session_id, status="error")
    except Exception:
        logger.warning(
            "DB write failed for session %s (session may have been deleted)",
            session_id,
        )


def _generate_title_from_plan(plan_body: str) -> str:
    """Auto-generate a concise issue title from the plan body (regex fallback)."""
    # Try to extract from ## Summary section (first non-empty line after heading)
    summary_match = re.search(r"^## Summary\s*\n+(.+?)(?:\n\n|\n#)", plan_body, re.MULTILINE | re.DOTALL)
    if summary_match:
        first_line = summary_match.group(1).strip().split("\n")[0].strip()
        first_line = re.sub(r"^\s*[-*]\s*", "", first_line)  # strip list marker
        first_line = re.sub(r"\*+|`+", "", first_line)  # strip markdown emphasis
        if first_line and len(first_line) <= 120:
            return first_line[:100]

    # Try first markdown heading
    heading_match = re.search(r"^#{1,3}\s+(.+)$", plan_body, re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()[:100]

    # Fallback: first non-empty, non-heading line
    for line in plan_body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            return re.sub(r"\*+|`+", "", line)[:100]

    return "Implementation Plan"


def _generate_title_with_ai(plan_body: str) -> str:
    """Use Claude to generate a concise GitHub issue title from the plan body.

    Falls back to regex extraction if the AI call fails.
    """
    prompt = (
        "Generate a concise GitHub issue title (under 80 characters) for the following "
        "implementation plan. Output ONLY the plain title text — no quotes, no markdown, "
        "no explanation.\n\n"
        + plan_body[:3000]
    )
    try:
        env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": CLAUDE_CODE_OAUTH_TOKEN}
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0:
            title = result.stdout.strip().strip('"\'`')
            if title and len(title) <= 120:
                logger.info("AI generated title: %s", title)
                return title[:100]
    except Exception as e:
        logger.warning("AI title generation failed, falling back to regex: %s", e)
    return _generate_title_from_plan(plan_body)


def create_issue_from_plan(session_id: str, title: str = "") -> dict:
    """Create a GitHub issue from the last assistant message in the session.

    If *title* is empty, a title is auto-generated from the plan content.
    Returns a dict with issue_number and issue_url on success, or raises on error.
    """
    session = db.get_planning_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    workspace = db.get_workspace(session["workspace_id"])
    if not workspace:
        raise ValueError(f"Workspace {session['workspace_id']} not found")

    messages = db.get_planning_messages(session_id)
    # Find the last assistant message as the plan body
    plan_body = None
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            plan_body = msg["content"]
            break

    if not plan_body:
        raise ValueError("No plan found in session — generate a plan first")

    # Strip conversational preamble — find the first markdown heading and use
    # everything from there onward as the actual issue body.
    heading_match = re.search(r"^(#{1,3}\s)", plan_body, re.MULTILINE)
    if heading_match:
        plan_body = plan_body[heading_match.start():]

    # Auto-generate title if not provided — use AI for a natural, descriptive title
    if not title:
        title = _generate_title_with_ai(plan_body)
        logger.info("Auto-generated issue title for session %s: %s", session_id, title)

    github_repo = workspace["github_repo"]

    env = {**os.environ, "GH_TOKEN": GH_TOKEN}

    cmd = [
        "gh", "issue", "create",
        "--repo", github_repo,
        "--title", title,
        "--body", plan_body,
        "--label", ISSUE_LABEL,
    ]

    logger.info("Creating GitHub issue for session %s in repo %s", session_id, github_repo)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(f"gh issue create failed: {result.stderr.strip()}")

    output = result.stdout.strip()
    logger.info("Issue created: %s", output)

    # Parse issue number and URL from output (gh outputs the URL)
    # e.g. "https://github.com/owner/repo/issues/42"
    issue_url = output
    issue_number = None
    match = re.search(r"/issues/(\d+)", output)
    if match:
        issue_number = int(match.group(1))

    db.update_planning_session(
        session_id,
        status="completed",
        issue_number=issue_number,
        issue_url=issue_url,
        title=title,
    )

    return {"issue_number": issue_number, "issue_url": issue_url}


def cancel_planning(session_id: str):
    """Terminate the active planning subprocess for this session, if any."""
    with _active_lock:
        proc = _active.pop(session_id, None)
        in_starting = session_id in _starting
        _starting.discard(session_id)  # also cancel sessions still starting
        # Only add to _cancelled when there is an actively-tracked subprocess
        # to signal.  If the session is not in _starting and not in _active,
        # the planning thread has already finished and consumed its own
        # _cancelled sentinel.  Unconditionally adding here in that case would
        # leave a stale entry that silently discards the next refinement plan
        # started on the same session_id (secondary stale-sentinel scenario).
        if proc is not None or in_starting:
            _cancelled.add(session_id)

    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Process for session %s did not exit after SIGKILL", session_id)
        logger.info("Cancelled planning agent for session %s", session_id)
    # NOTE: do NOT write status here — the background thread (_run_planning_agent_impl)
    # detects cancellation via the _cancelled set and performs the status='active'
    # write itself, after all cleanup is done.  Writing here would race with the
    # thread's own DB writes (TOCTOU: the status check below would be stale by
    # the time the write occurs, and the thread may overwrite it afterwards).

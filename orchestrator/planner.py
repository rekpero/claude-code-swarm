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


def start_planning(session_id: str, workspace_id: str, user_message: str) -> bool:
    """Add user message, build prompt, and launch background planning thread.

    If the session already has messages (refinement), the full conversation
    history is included in the prompt.

    Returns True if planning was successfully started, False if a generation is
    already in progress for this session.  The check and the claim are performed
    atomically under _active_lock to eliminate the TOCTOU race between callers
    that call is_generating() and start_planning() separately.
    """
    # Atomically check and claim the session slot before doing any work.
    with _active_lock:
        proc = _active.get(session_id)
        if session_id in _starting or (proc is not None and proc.poll() is None):
            return False
        _starting.add(session_id)

    # Persist user message
    db.add_planning_message(session_id, "user", user_message)

    workspace = db.get_workspace(workspace_id)
    if not workspace:
        with _active_lock:
            _starting.discard(session_id)
        db.update_planning_session(session_id, status="error")
        logger.error("Planning session %s: workspace %s not found", session_id, workspace_id)
        return False

    # Build conversation history (all messages before the one we just added)
    all_messages = db.get_planning_messages(session_id)
    # The last message is the one we just added; history = everything before it
    history = [{"role": m["role"], "content": m["content"]} for m in all_messages[:-1]]

    prompt = build_planning_prompt(user_message, conversation_history=history if history else None)

    db.update_planning_session(session_id, status="generating")

    thread = threading.Thread(
        target=_run_planning_agent,
        args=(session_id, workspace, prompt),
        daemon=True,
        name=f"planner-{session_id[:8]}",
    )
    thread.start()
    return True


def _run_planning_agent(session_id: str, workspace: dict, prompt: str):
    """Spawn claude -p in the workspace directory to produce a plan.

    Uses Read, Glob, Grep only — fully read-only, no worktree needed.
    """
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
        db.update_planning_session(session_id, status="error")
        return

    # Replace the _starting sentinel with the actual process atomically so that
    # is_generating() always sees a consistent state.
    with _active_lock:
        _starting.discard(session_id)
        _active[session_id] = process

    plan_text: str | None = None

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
                text_parts = [
                    b.get("text", "")
                    for b in content_blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                if text_parts:
                    plan_text = "\n".join(text_parts)

        process.wait()
        stderr_thread.join()
    except Exception as e:
        logger.error("Planning agent stream error for session %s: %s", session_id, e)
        stderr_thread.join()
    finally:
        with _active_lock:
            _starting.discard(session_id)
            _active.pop(session_id, None)

    return_code = process.returncode
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


def create_issue_from_plan(session_id: str, title: str) -> dict:
    """Create a GitHub issue from the last assistant message in the session.

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

    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        logger.info("Cancelled planning agent for session %s", session_id)

    session = db.get_planning_session(session_id)
    if session and session["status"] == "generating":
        db.update_planning_session(session_id, status="active")

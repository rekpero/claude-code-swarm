"""FastAPI dashboard server for the swarm orchestrator."""

import asyncio
import json
import logging
import os
import secrets
import signal
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orchestrator import db
from orchestrator import planner
from orchestrator import worktree
from orchestrator import workspace_manager as wm
from orchestrator.config import ADMIN_USERNAME, ADMIN_PASSWORD

app = FastAPI(title="SwarmOps Dashboard")

SESSION_DURATION_DAYS = 30


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # Allow: login endpoint, static assets, and SPA HTML (non-API paths)
    if path in ("/api/auth/login",) or not path.startswith("/api/"):
        return await call_next(request)

    # All other /api/* routes require a valid session token
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    token = auth_header[7:]  # strip "Bearer "
    session = db.get_session(token)
    if session is None:
        return JSONResponse({"detail": "Invalid or expired session"}, status_code=401)

    return await call_next(request)

STATIC_DIR = Path(__file__).parent / "static"

# Set by main.py after the AgentPool is created so dashboard endpoints can
# dispatch / restart agents.
_agent_pool = None


def set_agent_pool(pool):
    global _agent_pool
    _agent_pool = pool


# === Pydantic Models ===

class LoginRequest(BaseModel):
    username: str
    password: str


class CreateWorkspaceRequest(BaseModel):
    repo_url: str
    name: str | None = None
    base_branch: str = "main"


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = None
    repo_url: str | None = None
    base_branch: str | None = None


class SaveEnvRequest(BaseModel):
    vars: dict[str, str]
    env_file: str = ".env"


# === Dashboard HTML ===

@app.get("/", response_class=FileResponse)
async def index():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not built")
    return FileResponse(str(index))


# === Auth Endpoints ===

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """Validate credentials and return a session token."""
    u_ok = secrets.compare_digest(req.username.encode(), ADMIN_USERNAME.encode())
    p_ok = secrets.compare_digest(req.password.encode(), ADMIN_PASSWORD.encode())
    valid = ADMIN_PASSWORD and u_ok and p_ok
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(days=SESSION_DURATION_DAYS)).isoformat()
    db.create_session(token, expires_at)
    db.cleanup_expired_sessions()
    return {"token": token, "expires_at": expires_at}


@app.get("/api/auth/check")
async def auth_check():
    """Verify the current session is valid (middleware handles the actual check)."""
    return {"ok": True}


@app.post("/api/auth/logout")
async def logout(request: Request):
    """Invalidate the current session token."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        db.delete_session(auth_header[7:])
    return {"ok": True}


# === Workspace Endpoints ===

@app.post("/api/workspaces")
async def create_workspace(req: CreateWorkspaceRequest):
    """Create a new workspace — clones repo in background."""
    try:
        workspace = wm.create_workspace(
            repo_url=req.repo_url,
            name=req.name,
            base_branch=req.base_branch,
        )
        return {"workspace": workspace}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)


@app.get("/api/workspaces")
async def list_workspaces():
    """List all workspaces."""
    workspaces = db.get_all_workspaces()
    return {"workspaces": workspaces}


@app.get("/api/workspaces/{workspace_id}")
async def get_workspace(workspace_id: str):
    """Get workspace details including repo structure."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    # Parse structure_json
    try:
        workspace["structure"] = json.loads(workspace.get("structure_json") or "{}")
    except json.JSONDecodeError:
        workspace["structure"] = {}
    return {"workspace": workspace}


@app.put("/api/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, req: UpdateWorkspaceRequest):
    """Update workspace details."""
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    if not kwargs:
        return {"error": "No fields to update"}
    workspace = wm.update_workspace(workspace_id, **kwargs)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    return {"workspace": workspace}


@app.delete("/api/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str):
    """Delete a workspace and all associated data."""
    ok = wm.delete_workspace(workspace_id)
    if not ok:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    return {"ok": True}


@app.get("/api/workspaces/{workspace_id}/structure")
async def get_workspace_structure(workspace_id: str):
    """Get detected repo structure (monorepo packages, env files)."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    structure = wm.detect_repo_structure(workspace["local_path"])
    # Update cached structure
    db.update_workspace(workspace_id, structure_json=json.dumps(structure))
    return {"structure": structure}


@app.get("/api/workspaces/{workspace_id}/git-status")
async def workspace_git_status(workspace_id: str):
    """Check if the workspace's base branch is in sync with the remote."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    local_path = workspace.get("local_path")
    if not local_path or not Path(local_path).exists():
        return JSONResponse(content={"error": "Workspace repo not cloned yet"}, status_code=400)
    try:
        status = await asyncio.to_thread(worktree.get_sync_status, local_path, workspace.get("base_branch", "main"))
        return status
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/api/workspaces/{workspace_id}/git-pull")
async def workspace_git_pull(workspace_id: str):
    """Pull latest changes from the remote for the workspace's base branch."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    local_path = workspace.get("local_path")
    if not local_path or not Path(local_path).exists():
        return JSONResponse(content={"error": "Workspace repo not cloned yet"}, status_code=400)
    try:
        await asyncio.to_thread(worktree.ensure_repo_updated, local_path, workspace.get("base_branch", "main"))
        status = await asyncio.to_thread(worktree.get_sync_status, local_path, workspace.get("base_branch", "main"))
        return {"ok": True, **status}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.put("/api/workspaces/{workspace_id}/env")
async def save_workspace_env(workspace_id: str, req: SaveEnvRequest):
    """Save env vars for a workspace (writes to DB + disk)."""
    try:
        wm.save_env_vars(workspace_id, req.vars, req.env_file)
        return {"ok": True, "env_file": req.env_file, "count": len(req.vars)}
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=404)


@app.get("/api/workspaces/{workspace_id}/env")
async def get_workspace_env(workspace_id: str, env_file: str = Query(".env")):
    """Get env vars for a workspace."""
    env_vars = wm.get_env_vars(workspace_id, env_file)
    return {"vars": env_vars, "env_file": env_file}


@app.delete("/api/workspaces/{workspace_id}/env")
async def delete_workspace_env_file(workspace_id: str, env_file: str = Query(".env")):
    """Delete all env vars for a specific env file in a workspace and remove the file from disk."""
    db.delete_workspace_env_file(workspace_id, env_file)
    # Also delete the actual file from disk
    ws = db.get_workspace(workspace_id)
    if ws and ws.get("local_path"):
        from pathlib import Path
        file_path = Path(ws["local_path"]) / env_file
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    return {"ok": True, "env_file": env_file}


@app.get("/api/workspaces/{workspace_id}/env-files")
async def get_workspace_env_files(workspace_id: str):
    """List all env files — both discovered on disk and managed in DB."""
    managed = wm.get_all_env_files(workspace_id)
    discovered = wm.discover_existing_env_files(workspace_id)
    return {"managed": managed, "discovered": discovered}


@app.post("/api/workspaces/{workspace_id}/env-load")
async def load_env_from_disk(workspace_id: str, env_file: str = Query(".env")):
    """Load env vars from an existing .env file on disk into DB."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    local_path = workspace.get("local_path")
    if not local_path or not Path(local_path).exists():
        return JSONResponse(content={"error": "Workspace repo not cloned yet"}, status_code=400)
    file_path = Path(local_path) / env_file
    # Guard against path traversal: resolve both paths and ensure the file is
    # contained within the workspace directory.  pathlib silently discards
    # local_path when env_file is absolute, and ../ sequences can escape the
    # workspace, so we must check after resolving.
    resolved_workspace = Path(local_path).resolve()
    if not file_path.resolve().is_relative_to(resolved_workspace):
        return JSONResponse(content={"error": "Access denied: path is outside the workspace"}, status_code=403)
    if not file_path.exists():
        return JSONResponse(content={"error": f"File {env_file} not found on disk"}, status_code=404)
    try:
        env_vars = wm.load_env_from_disk(workspace_id, env_file)
        return {"vars": env_vars, "env_file": env_file, "count": len(env_vars)}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


# === Existing Endpoints (now workspace-filterable) ===

@app.get("/api/agents")
async def list_agents(
    workspace_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List agents with server-side pagination."""
    agents = db.get_all_agents(workspace_id=workspace_id, limit=limit, offset=offset)
    total = db.count_agents(workspace_id=workspace_id)
    for agent in agents:
        if agent["status"] == "running" and not agent.get("turns_used"):
            agent["turns_used"] = db.get_agent_turn_count(agent["agent_id"])
    return {"agents": agents, "total": total, "limit": limit, "offset": offset}


@app.get("/api/agents/{agent_id}/logs")
async def agent_logs(agent_id: str, since: int = Query(0)):
    """Get stream-json events for a specific agent."""
    events = db.get_agent_events(agent_id, since_id=since, limit=200)
    return {"events": events}


@app.post("/api/agents/{agent_id}/restart")
async def restart_agent(agent_id: str):
    """Kill a running agent and dispatch a fresh one for the same issue/PR."""
    agent = db.get_agent(agent_id)
    if not agent:
        return JSONResponse(content={"error": "Agent not found"}, status_code=404)
    if agent["status"] != "running":
        return JSONResponse(content={"error": "Agent is not running"}, status_code=400)
    if not _agent_pool:
        return JSONResponse(content={"error": "Agent pool not available"}, status_code=503)

    # Validate workspace before any destructive operations so we never kill
    # the agent and mutate the DB only to discover we cannot redispatch.
    workspace_id = agent.get("workspace_id")
    ws = db.get_workspace(workspace_id) if workspace_id else None
    if not ws:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)

    # Validate dispatch preconditions BEFORE sending SIGTERM so that if they
    # fail the old agent is left alive and the issue is never stranded in a
    # stopped state with no replacement agent.
    branch = None
    threads = None
    if agent.get("agent_type") == "fix_review":
        if not agent.get("pr_number"):
            return JSONResponse(
                content={"error": "Cannot restart: fix_review agent has no pr_number"},
                status_code=400,
            )
        from orchestrator.pr_monitor import get_pr_branch, get_unresolved_threads
        github_repo = ws.get("github_repo")
        if not github_repo:
            return JSONResponse(
                content={"error": "Workspace has no github_repo configured"},
                status_code=409,
            )
        branch = get_pr_branch(agent["pr_number"], github_repo=github_repo)
        threads = get_unresolved_threads(agent["pr_number"], github_repo=github_repo)
        if not branch:
            return JSONResponse(
                content={"error": "Cannot restart: could not resolve PR branch"},
                status_code=400,
            )
    else:
        if agent["issue_number"] is None:
            return JSONResponse(
                content={"error": "Cannot restart: no issue number"},
                status_code=400,
            )

    # Validate PID before marking externally stopped. If a 'running' agent has
    # no PID (e.g. the PID write raced with a DB failure), we must not flag it
    # as stopped without sending SIGTERM — the original process would keep
    # running alongside any replacement, and _monitor_agent/_monitor_pid would
    # skip their completion DB writes when it eventually exits.
    pid = agent.get("pid")
    if not pid:
        return JSONResponse(
            content={"error": "Cannot restart: running agent has no PID recorded"},
            status_code=409,
        )

    # Mark the agent as externally stopped *before* sending SIGTERM so that
    # _monitor_agent / _monitor_pid skip their own completion DB writes and
    # don't race with the writes below.
    _agent_pool.mark_externally_stopped(agent_id)

    # Kill the old process group and wait for it to die.
    # Agents are spawned with start_new_session=True, so they lead their own
    # process group.  Signalling only the agent PID leaves any child processes
    # it spawned (e.g. subprocess claude invocations) as orphans.  Send SIGTERM
    # to the entire process group instead.
    if pid:
        try:
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            # Wait up to 10s for the process to exit
            for _ in range(20):
                await asyncio.sleep(0.5)
                try:
                    os.kill(pid, 0)
                except (OSError, ProcessLookupError):
                    break  # Process is dead
            else:
                # Force kill if still alive
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    await asyncio.sleep(0.5)
                except (OSError, ProcessLookupError):
                    pass
        except (OSError, ProcessLookupError):
            pass
    # Re-fetch the agent record after the kill to check whether it had already
    # completed naturally (e.g. just created a PR) before we sent SIGTERM.
    # Use this single snapshot for both status decisions and cleanup operations
    # to avoid acting on a stale worktree_path while using a fresh status.
    current_agent = db.get_agent(agent_id)
    if current_agent and current_agent["status"] == "running":
        # Mark the old agent finished BEFORE dispatching the new one.  The
        # _monitor_agent/_monitor_pid thread was told to skip its own DB
        # completion writes (via mark_externally_stopped) and may have already
        # exited by now.  Writing finish_agent here — before dispatch — ensures
        # the old record is never left permanently in 'running' state even if
        # the dispatch call succeeds but a subsequent DB write fails.
        try:
            db.finish_agent(agent_id, status="stopped", error_message="Manually restarted by user")
        except Exception:
            _agent_pool.unmark_externally_stopped(agent_id)
            raise

        # update_issue failure is non-fatal: the agent is already stopped and we
        # still want to dispatch a replacement.  Ignore errors and continue.
        if current_agent["issue_number"] is not None and current_agent.get("agent_type") == "fix_review":
            try:
                db.update_issue(current_agent["issue_number"], workspace_id=workspace_id, status="pending")
            except Exception:
                pass

        # Dispatch preconditions were validated before the kill; proceed to dispatch.
        new_agent_id = None
        try:
            if current_agent.get("agent_type") == "fix_review":
                new_agent_id = _agent_pool.dispatch_fix_review(
                    current_agent["pr_number"], branch, current_agent["issue_number"], ws, threads,
                )
            else:
                new_agent_id = _agent_pool.dispatch_implement(current_agent["issue_number"], workspace=ws)
        except Exception:
            _agent_pool.unmark_externally_stopped(agent_id)
            raise

        if not new_agent_id:
            # The old agent process is already dead (SIGTERM was sent and
            # waited on above).  finish_agent was already called above.
            _agent_pool.unmark_externally_stopped(agent_id)
            return JSONResponse(content={"error": "Failed to dispatch new agent"}, status_code=500)

        # Clean up the old worktree now that the new agent has its own.
        # Use current_agent to ensure we target the fresh worktree_path.
        repo_path = ws["local_path"]
        if current_agent.get("worktree_path"):
            try:
                worktree.cleanup_worktree(current_agent["worktree_path"], repo_path=repo_path)
            except Exception:
                pass

        return {"ok": True, "old_agent_id": agent_id, "new_agent_id": new_agent_id}

    # The agent had already completed naturally before we could restart it.
    # Remove agent_id from _stopped_agent_ids so it doesn't leak in the set.
    _agent_pool.unmark_externally_stopped(agent_id)
    return JSONResponse(content={"error": "Agent completed before restart could dispatch a new one"}, status_code=409)


@app.get("/api/issues")
async def list_issues(workspace_id: str | None = Query(None)):
    """List all tracked issues and their state."""
    issues = db.get_all_issues(workspace_id=workspace_id)
    return {"issues": issues}


@app.get("/api/prs")
async def list_prs(workspace_id: str | None = Query(None)):
    """List all tracked PRs and their review loop count."""
    reviews = db.get_all_pr_reviews(workspace_id=workspace_id)

    # Build a lookup of (workspace_id, pr_number) -> issue status so we can
    # mark merged PRs.  Using a composite key prevents PRs with the same
    # number in different workspaces from overwriting each other.
    all_issues = db.get_all_issues(workspace_id=workspace_id)
    pr_issue_status: dict[tuple, str] = {}
    for issue in all_issues:
        if issue.get("pr_number"):
            key = (issue.get("workspace_id"), issue["pr_number"])
            pr_issue_status[key] = issue["status"]

    pr_map: dict[tuple, dict] = {}
    for review in reviews:
        pr_num = review["pr_number"]
        ws_id = review.get("workspace_id")
        key = (ws_id, pr_num)
        if key not in pr_map:
            pr_map[key] = {
                "pr_number": pr_num,
                "iterations": 0,
                "latest_status": review["status"],
                "total_comments": 0,
                "review_threads": [],
                "workspace_id": ws_id,
            }
        pr_map[key]["iterations"] = max(pr_map[key]["iterations"], review["iteration"])
        pr_map[key]["latest_status"] = review["status"]
        pr_map[key]["total_comments"] += review.get("comments_count", 0)

        comments_json = review.get("comments_json")
        if comments_json:
            try:
                pr_map[key]["review_threads"] = json.loads(comments_json)
            except (json.JSONDecodeError, TypeError):
                pass

    # Enrich PR statuses from issue state:
    # - issue "resolved" → PR was merged
    # - issue "needs_human" → PR needs human intervention
    for (ws_id, pr_num), pr_data in pr_map.items():
        issue_status = pr_issue_status.get((ws_id, pr_num))
        if issue_status == "resolved":
            pr_data["latest_status"] = "merged"
        elif issue_status == "needs_human":
            pr_data["latest_status"] = "needs_human"

    # Sort: active statuses first, resolved/merged last
    pr_status_order = {"pending_fix": 0, "pending": 1, "open": 2, "needs_human": 3, "closed": 4, "merged": 5}
    sorted_prs = sorted(pr_map.values(), key=lambda p: pr_status_order.get(p["latest_status"], 3))
    return {"prs": sorted_prs}


class StartPlanningRequest(BaseModel):
    workspace_id: str
    message: str


class RefinePlanRequest(BaseModel):
    message: str


class CreateIssueRequest(BaseModel):
    title: str = ""
    message_index: int | None = None


# === Planning Endpoints ===

@app.get("/api/workspaces/{workspace_id}/planning-sessions")
async def list_planning_sessions(workspace_id: str):
    """List all planning sessions for a workspace."""
    workspace = db.get_workspace(workspace_id)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    sessions = db.list_planning_sessions(workspace_id)
    return {"sessions": sessions}


@app.delete("/api/planning/{session_id}")
def delete_planning_session(session_id: str):
    """Delete a planning session and its messages."""
    session = db.get_planning_session(session_id)
    if not session:
        return JSONResponse(content={"error": "Session not found"}, status_code=404)
    planner.cancel_planning(session_id)
    planner.cleanup_session_issue_keys(session_id)
    db.delete_planning_session(session_id)
    return {"ok": True}


@app.post("/api/planning")
async def start_planning(req: StartPlanningRequest):
    """Create a planning session and start generating a plan."""
    workspace = db.get_workspace(req.workspace_id)
    if not workspace:
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)

    session_id = str(uuid.uuid4())
    db.create_planning_session(session_id, req.workspace_id)

    try:
        result = planner.start_planning(session_id, req.workspace_id, req.message)
    except Exception:
        db.delete_planning_session(session_id)
        raise
    if result == "workspace_not_found":
        db.delete_planning_session(session_id)
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)
    if result == "already_generating":
        db.delete_planning_session(session_id)
        return JSONResponse(content={"error": "Generation already in progress"}, status_code=409)

    session = db.get_planning_session(session_id)
    messages = db.get_planning_messages(session_id)
    return {"session": session, "messages": messages}


@app.get("/api/planning/{session_id}")
async def get_planning_session(session_id: str):
    """Get planning session status and all messages."""
    session = db.get_planning_session(session_id)
    if not session:
        return JSONResponse(content={"error": "Session not found"}, status_code=404)

    messages = db.get_planning_messages(session_id)
    generating = planner.is_generating(session_id)
    return {"session": session, "messages": messages, "generating": generating}


@app.get("/api/planning/{session_id}/events")
async def get_planning_events(session_id: str, since: int = Query(0)):
    """Get streaming progress events for a planning session."""
    session = db.get_planning_session(session_id)
    if not session:
        return JSONResponse(content={"error": "Session not found"}, status_code=404)
    events = db.get_planning_events(session_id, since_id=since)
    return {"events": events}


@app.post("/api/planning/{session_id}/messages")
async def refine_plan(session_id: str, req: RefinePlanRequest):
    """Send a refinement message to continue the planning conversation."""
    session = db.get_planning_session(session_id)
    if not session:
        return JSONResponse(content={"error": "Session not found"}, status_code=404)

    # start_planning atomically checks and claims the session slot, eliminating
    # the TOCTOU race between is_generating() and start_planning().
    result = planner.start_planning(session_id, session["workspace_id"], req.message)
    if result == "already_generating":
        return JSONResponse(content={"error": "Generation already in progress"}, status_code=409)
    if result == "workspace_not_found":
        return JSONResponse(content={"error": "Workspace not found"}, status_code=404)

    session = db.get_planning_session(session_id)
    messages = db.get_planning_messages(session_id)
    return {"session": session, "messages": messages}


@app.post("/api/planning/{session_id}/create-issue")
def create_issue_from_plan(session_id: str, req: CreateIssueRequest):
    """Create a GitHub issue from the generated plan."""
    session = db.get_planning_session(session_id)
    if not session:
        return JSONResponse(content={"error": "Session not found"}, status_code=404)

    try:
        result = planner.create_issue_from_plan(session_id, req.title, message_index=req.message_index)
        return result
    except RuntimeError as e:
        status_code = 409 if "in progress" in str(e) else 400
        return JSONResponse(content={"error": str(e)}, status_code=status_code)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)


@app.post("/api/planning/{session_id}/cancel")
def cancel_planning(session_id: str):
    """Cancel active generation for a planning session."""
    session = db.get_planning_session(session_id)
    if not session:
        return JSONResponse(content={"error": "Session not found"}, status_code=404)

    planner.cancel_planning(session_id)
    return {"ok": True}


class UpdateIssueStatusRequest(BaseModel):
    status: str


@app.put("/api/issues/{issue_number}/status")
async def update_issue_status(issue_number: int, req: UpdateIssueStatusRequest, workspace_id: str | None = Query(None)):
    """Update an issue's status (e.g. retry a needs_human issue)."""
    allowed = {"pending", "pr_created", "needs_human", "resolved"}
    if req.status not in allowed:
        return JSONResponse(content={"error": f"Invalid status. Allowed: {allowed}"}, status_code=400)
    issue = db.get_issue(issue_number, workspace_id=workspace_id)
    if not issue:
        return JSONResponse(content={"error": "Issue not found"}, status_code=404)
    db.update_issue(issue_number, workspace_id=workspace_id, status=req.status)
    return {"ok": True, "issue_number": issue_number, "status": req.status}


@app.get("/api/metrics")
async def get_metrics(workspace_id: str | None = Query(None)):
    """Aggregate stats, optionally filtered by workspace."""
    metrics = db.get_metrics(workspace_id=workspace_id)
    return metrics


# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Serve Vite-built assets at /assets/ (index.html references them with root-relative /assets/... paths)
# Only mount if the directory exists; otherwise log a warning and let the spa_fallback return 404.
_assets_dir = STATIC_DIR / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")
else:
    logging.getLogger(__name__).warning(
        "Assets directory '%s' not found — frontend build may be missing. "
        "Requests to /assets/... will return 404.",
        _assets_dir,
    )


# SPA catch-all — must be registered LAST, after all /api/* routes and static mount.
# Returns index.html for any non-API, non-static path so React Router handles navigation.
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    if full_path.startswith("assets/") or full_path.startswith("static/"):
        raise HTTPException(status_code=404)
    index = STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Frontend not built")
    return FileResponse(str(index))

"""FastAPI dashboard server for the swarm orchestrator."""

import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from orchestrator import db
from orchestrator import workspace_manager as wm

app = FastAPI(title="Claude Code Swarm Dashboard")

STATIC_DIR = Path(__file__).parent / "static"


# === Pydantic Models ===

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

@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = STATIC_DIR / "index.html"
    return index_file.read_text()


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
    env_vars = wm.load_env_from_disk(workspace_id, env_file)
    return {"vars": env_vars, "env_file": env_file, "count": len(env_vars)}


# === Existing Endpoints (now workspace-filterable) ===

@app.get("/api/agents")
async def list_agents(workspace_id: str | None = Query(None)):
    """List all agents with current status."""
    agents = db.get_all_agents(workspace_id=workspace_id)
    for agent in agents:
        if agent["status"] == "running" and not agent.get("turns_used"):
            agent["turns_used"] = db.get_agent_turn_count(agent["agent_id"])
    return {"agents": agents}


@app.get("/api/agents/{agent_id}/logs")
async def agent_logs(agent_id: str, since: int = Query(0)):
    """Get stream-json events for a specific agent."""
    events = db.get_agent_events(agent_id, since_id=since, limit=200)
    return {"events": events}


@app.get("/api/issues")
async def list_issues(workspace_id: str | None = Query(None)):
    """List all tracked issues and their state."""
    issues = db.get_all_issues(workspace_id=workspace_id)
    return {"issues": issues}


@app.get("/api/prs")
async def list_prs(workspace_id: str | None = Query(None)):
    """List all tracked PRs and their review loop count."""
    reviews = db.get_all_pr_reviews(workspace_id=workspace_id)
    pr_map: dict[int, dict] = {}
    for review in reviews:
        pr_num = review["pr_number"]
        if pr_num not in pr_map:
            pr_map[pr_num] = {
                "pr_number": pr_num,
                "iterations": 0,
                "latest_status": review["status"],
                "total_comments": 0,
                "review_threads": [],
            }
        pr_map[pr_num]["iterations"] = max(pr_map[pr_num]["iterations"], review["iteration"])
        pr_map[pr_num]["latest_status"] = review["status"]
        pr_map[pr_num]["total_comments"] += review.get("comments_count", 0)

        comments_json = review.get("comments_json")
        if comments_json:
            try:
                pr_map[pr_num]["review_threads"] = json.loads(comments_json)
            except (json.JSONDecodeError, TypeError):
                pass

    return {"prs": list(pr_map.values())}


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

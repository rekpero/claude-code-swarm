"""FastAPI dashboard server for the swarm orchestrator."""

from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from orchestrator import db

app = FastAPI(title="Claude Code Swarm Dashboard")

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = STATIC_DIR / "index.html"
    return index_file.read_text()


@app.get("/api/agents")
async def list_agents():
    """List all agents with current status."""
    agents = db.get_all_agents()
    return {"agents": agents}


@app.get("/api/agents/{agent_id}/logs")
async def agent_logs(agent_id: str, since: int = Query(0)):
    """Get stream-json events for a specific agent."""
    events = db.get_agent_events(agent_id, since_id=since, limit=200)
    return {"events": events}


@app.get("/api/issues")
async def list_issues():
    """List all tracked issues and their state."""
    issues = db.get_all_issues()
    return {"issues": issues}


@app.get("/api/prs")
async def list_prs():
    """List all tracked PRs and their review loop count."""
    reviews = db.get_all_pr_reviews()
    # Group by PR number
    pr_map: dict[int, dict] = {}
    for review in reviews:
        pr_num = review["pr_number"]
        if pr_num not in pr_map:
            pr_map[pr_num] = {
                "pr_number": pr_num,
                "iterations": 0,
                "latest_status": review["status"],
                "total_comments": 0,
            }
        pr_map[pr_num]["iterations"] = max(pr_map[pr_num]["iterations"], review["iteration"])
        pr_map[pr_num]["latest_status"] = review["status"]
        pr_map[pr_num]["total_comments"] += review.get("comments_count", 0)
    return {"prs": list(pr_map.values())}


@app.get("/api/metrics")
async def get_metrics():
    """Aggregate stats."""
    metrics = db.get_metrics()
    return metrics


# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

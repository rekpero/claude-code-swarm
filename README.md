# Claude Code Agent Swarm

A 24/7 autonomous orchestrator that watches a GitHub repository for open issues, dispatches parallel [Claude Code](https://docs.anthropic.com/en/docs/claude-code) agents to implement fixes and features, creates PRs, handles CI review feedback in a loop, and iterates until all issues are resolved.

## How It Works

```
Issue created (labeled "agent")
    │
    ▼
You write the full plan in the issue body...
    │
    ▼
Comment "@claude-swarm start" when ready
    │
    ▼
Orchestrator polls GitHub ──▶ Dispatches Claude Code agent
    │                              │
    │                              ▼
    │                         Agent reads issue body (the implementation plan),
    │                         implements changes in an isolated git worktree,
    │                         runs tests, pushes branch, creates PR
    │                              │
    │                              ▼
    │                         CI / bugbot reviews the PR diff,
    │                         posts comments on issues found
    │                              │
    │                              ▼
    │                         Orchestrator detects comments ──▶ Dispatches fix agent
    │                              │
    │                              ▼
    │                         Fix agent addresses every comment, pushes again
    │                              │
    │                              ▼
    │                         (loop until 0 comments or max retries hit)
    │
    ▼
Dashboard shows live progress at http://localhost:8420
```

Each issue must contain a **full implementation plan** in the body (like Claude Code plan mode output). Agents read this as their spec — no guesswork needed.

## Prerequisites

- **Python 3.10+**
- **Claude Code CLI** (`claude`) — authenticated via `claude setup-token` with a Max subscription
- **GitHub CLI** (`gh`) — installed ([cli.github.com](https://cli.github.com))
- **Git 2.20+**
- A GitHub fine-grained PAT with permissions: Contents, Issues, Pull Requests, Metadata

## Quick Start

```bash
# 1. Clone and set up
git clone <this-repo> && cd claude-code-swarm
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env with your tokens and target repo path

# 3. Run
python -m orchestrator.main
```

The dashboard will be available at `http://localhost:8420`.

## Configuration

All settings are in `.env` (or environment variables):

| Variable | Default | Description |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | *(required)* | From `claude setup-token` (Max plan) |
| `GH_TOKEN` | *(required)* | GitHub PAT for private repo access |
| `GITHUB_REPO` | *(required)* | Target repo, e.g. `owner/repo` |
| `TARGET_REPO_PATH` | *(required)* | Local clone path, e.g. `/home/user/my-project` |
| `BASE_BRANCH` | `main` | Branch agents fork from |
| `MAX_CONCURRENT_AGENTS` | `3` | Max parallel agents |
| `AGENT_MAX_TURNS_IMPLEMENT` | `30` | Max Claude turns for new issues |
| `AGENT_MAX_TURNS_FIX` | `20` | Max Claude turns for fixing review comments |
| `AGENT_TIMEOUT_SECONDS` | `1800` | Hard timeout per agent (30 min) |
| `POLL_INTERVAL_SECONDS` | `300` | How often to check for new issues (5 min) |
| `PR_POLL_INTERVAL_SECONDS` | `120` | How often to check PRs for comments (2 min) |
| `ISSUE_LABEL` | `agent` | Only issues with this label are picked up |
| `TRIGGER_MENTION` | `@claude-swarm` | Agents only start when a comment with this mention exists (set empty to disable) |
| `MAX_ISSUE_RETRIES` | `3` | Retry limit per issue before escalation |
| `MAX_PR_FIX_RETRIES` | `5` | Max review-fix cycles per PR |
| `DASHBOARD_PORT` | `8420` | Dashboard web UI port |

## Production Deployment (Ubuntu)

The `run.sh` script manages the orchestrator as a systemd service:

```bash
# Install as a systemd service (auto-start on boot, auto-restart on crash)
sudo ./run.sh install

# Day-to-day management
./run.sh status      # Check if running
./run.sh logs        # Tail live logs (journalctl)
./run.sh restart     # After config changes
./run.sh stop        # Graceful shutdown

# Remove the service
sudo ./run.sh uninstall
```

Without systemd (local dev), `start`/`stop` fall back to `nohup` with a PID file.

## Target Repository Setup

Your target repo needs two things:

**1. `AGENT.md`** at the repo root — coding guidelines for agents (style, conventions, test commands).

**2. `CLAUDE.md`** at the repo root — auto-loaded by Claude Code on every session:

```markdown
# CLAUDE.md

## CRITICAL: Read AGENT.md First
Before making ANY changes, read and follow all guidelines in @AGENT.md.

## Workflow Rules for Automated Agents
1. ALWAYS read AGENT.md before starting work.
2. ALWAYS run tests before creating a PR or pushing fixes.
3. NEVER modify files unrelated to your assigned issue.
4. NEVER push directly to main. Always use feature branches.
5. Reference the issue number in every commit message.
```

**3. Issues** must be labeled with the configured label (default: `agent`) and contain a detailed implementation plan in the body. When you're done writing the plan, comment **`@claude-swarm start`** on the issue to trigger the agent. Issues without this trigger comment are ignored until activated.

**4. CI reviewer** — optionally set up a PR review action (e.g. `rekpero/claude-bugbot-github-action`) to post review comments that the orchestrator will detect and dispatch fix agents for.

## Architecture

```
claude-code-swarm/              ← This project (orchestrator)
├── orchestrator/
│   ├── main.py                 # Entry point — starts all subsystems
│   ├── config.py               # Configuration + environment validation
│   ├── db.py                   # SQLite (issues, agents, events, PR reviews)
│   ├── issue_poller.py         # Polls GitHub for labeled issues
│   ├── agent_pool.py           # Manages claude -p subprocess lifecycle
│   ├── pr_monitor.py           # Watches PRs for review comments / CI status
│   ├── worktree.py             # Git worktree create/cleanup
│   ├── stream_parser.py        # Parses claude stream-json output
│   ├── prompts.py              # Agent prompt templates
│   ├── dashboard.py            # FastAPI server
│   └── static/index.html       # Dashboard UI
├── run.sh                      # Service management script
└── .env                        # Tokens and config

~/my-project/                   ← Target repo (separate directory)
~/my-project-worktrees/         ← Auto-created isolated worktrees for each agent
```

Agents run in isolated git worktrees as siblings of the target repo. The orchestrator never touches the target repo's working directory — each agent gets its own copy.

## Dashboard

The web dashboard at `http://localhost:8420` shows:

- **Metrics bar** — resolved, pending, in progress, open PRs, needs human, avg turns
- **Active agents** — live log stream, issue/PR assignment, turn count, elapsed time
- **Issue queue** — all tracked issues with status and retry count
- **PR tracker** — open PRs with review iteration count and comment totals

Auto-refreshes every 3 seconds. No build step — plain HTML + vanilla JS.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/metrics` | Aggregate stats |
| `GET /api/agents` | All agents with status |
| `GET /api/agents/{id}/logs?since=N` | Stream-json events for an agent |
| `GET /api/issues` | All tracked issues |
| `GET /api/prs` | PR review loop status |

## Safety Guardrails

- **Concurrency cap** — max 3 parallel agents (configurable)
- **Turn limits** — 30 turns for implementation, 20 for fixes
- **Hard timeout** — agents killed after 30 minutes
- **Retry limits** — 3 attempts per issue, 5 review-fix cycles per PR
- **Escalation** — exhausted issues labeled `needs-human` on GitHub
- **Crash recovery** — stale agents from previous runs are cleaned up on restart
- **Error backoff** — repeated poll failures trigger exponential backoff
- **Graceful shutdown** — SIGTERM/SIGINT waits for running agents, cleans up worktrees

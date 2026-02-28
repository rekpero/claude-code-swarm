# Claude Code Agent Swarm — System Design & Implementation Plan

## 1. Overview

This document describes the complete architecture for a **24/7 autonomous agent swarm** powered by Claude Code. The system watches a GitHub repository for open issues, dispatches parallel Claude Code agents to implement fixes or features, creates PRs, handles CI review feedback in a loop, and iterates until all issues are resolved.

**Authentication:** All agents use `claude setup-token` with a Claude Code Max subscription — no Anthropic API key is needed. A `GH_TOKEN` (GitHub PAT) is required for private repo access.

**Key constraints:**
- The Claude Agent SDK (Python/TypeScript) does not support `setup-token` / Max plan billing. All agent invocations must go through `claude -p` (headless CLI mode).
- The swarm orchestrator lives in its **own separate directory** from the target repository. It points to the target repo via a `TARGET_REPO_PATH` config variable. This keeps the swarm tooling completely decoupled from the codebase being worked on.
- Issues contain **full implementation plans** (like Claude Code plan mode output) in the issue body. Agents read the entire issue description as their implementation spec — no guesswork needed.

---

## 2. Requirements

### Functional Requirements

- Poll GitHub repository for open issues (labeled for automation)
- Dispatch one Claude Code agent per issue, working in an isolated git worktree
- Each agent reads `AGENT.md` from the repo before making any changes
- Agent implements the fix/feature, runs tests, and creates a PR referencing the issue
- Your existing `rekpero/claude-bugbot-github-action` reviews the PR diff and posts bug comments
- When review comments appear, a new agent (or the same agent via `--resume`) picks them up, fixes all reported issues, and pushes to the same PR branch
- The review → fix cycle repeats until CI passes with zero comments
- The orchestrator runs 24/7, continuously picking up new issues and monitoring existing PRs
- A live dashboard shows what each agent is doing in real time

### Non-Functional Requirements

- **Cost-aware:** Use Max plan via `setup-token`; enforce per-agent turn limits and budget caps
- **Conflict-free:** Agents never work on overlapping files simultaneously
- **Observable:** Every agent streams structured logs to a central dashboard
- **Resilient:** Failed agents are retried up to a configurable limit, then escalated
- **Terminable:** Feedback loops have a max iteration cap to prevent infinite cost burn

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         YOUR MACHINE / SERVER                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────┐              │
│  │  SWARM ORCHESTRATOR (separate directory)           │              │
│  │  e.g., ~/claude-swarm/                             │              │
│  │                                                    │              │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────┐│              │
│  │  │  Issue   │ │  Agent   │ │ PR Review│ │ Dash- ││              │
│  │  │  Poller  │ │  Pool    │ │ Monitor  │ │ board ││              │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬───┘│              │
│  │       └─────────────┼────────────┼───────────┘    │              │
│  │                     │            │                 │              │
│  │              ┌──────▼──────┐  ┌──▼────────┐       │              │
│  │              │ Event Store │  │Agent State │       │              │
│  │              │  (SQLite)   │  │ (SQLite)   │       │              │
│  │              └─────────────┘  └───────────┘       │              │
│  └────────────────────────────────────────────────────┘              │
│          │                                                           │
│          │ points to TARGET_REPO_PATH                                │
│          ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  TARGET REPO (your project — separate directory)               │  │
│  │  e.g., ~/my-project/  (contains AGENT.md, CLAUDE.md, src/)    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│          │                                                           │
│          │ git worktree add (created as sibling directories)         │
│          ▼                                                           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  WORKTREE POOL (sibling of target repo)                        │  │
│  │  e.g., ~/my-project-worktrees/                                 │  │
│  │                                                                │  │
│  │  ├── issue-42/    ← Agent 1 (claude -p, stream-json)         │  │
│  │  ├── issue-87/    ← Agent 2 (claude -p, stream-json)         │  │
│  │  ├── pr-fix-101/  ← Agent 3 (fixing review comments)         │  │
│  │  └── issue-103/   ← Agent 4 (claude -p, stream-json)         │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
         │                                           │
         │  gh issue list / gh pr list               │  git push
         │  (uses GH_TOKEN for private repo)         │  (uses GH_TOKEN)
         ▼                                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                           GITHUB                                     │
│                                                                      │
│  Issues ──▶ Orchestrator polls ──▶ Agent implements ──▶ PR created  │
│                                                                      │
│  PR ──▶ rekpero/claude-bugbot-github-action ──▶ Bug comments posted  │
│                                                                      │
│  Bug comments ──▶ Orchestrator detects ──▶ Agent fixes ──▶ Push     │
│                                                                      │
│  (repeat until bugbot posts 0 comments)                             │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 4. Component Design

### 4.1 Authentication Setup

Two tokens are required: `claude setup-token` for Claude Code (Max plan), and a GitHub PAT (`GH_TOKEN`) for private repo access. No `ANTHROPIC_API_KEY` is used anywhere.

```bash
# 1. Claude Code auth — generate the long-lived OAuth token
claude setup-token
# Output: sk-ant-oat01-...

# 2. GitHub PAT — create a fine-grained personal access token with these permissions:
#    - Repository access: the target private repo
#    - Permissions: Contents (read/write), Issues (read/write), Pull requests (read/write), Metadata (read)
#    Generate at: https://github.com/settings/tokens?type=beta

# Store both in .env for the orchestrator
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
export GH_TOKEN="ghp_..."
```

**Why `GH_TOKEN` is needed:**
- The target repository is **private** — `gh` CLI commands (issue list, PR create, API calls) require authentication
- The `gh` CLI automatically picks up `GH_TOKEN` from the environment (no `gh auth login` needed)
- All agent subprocesses inherit the env var, so `gh issue view`, `gh pr create`, etc. just work
- The same token is used in GitHub Actions as a repository secret for the bugbot

**Token management:**
- Store both tokens in a `.env` file (git-ignored) in the orchestrator directory
- Store `CLAUDE_CODE_OAUTH_TOKEN` as a GitHub repository secret for GitHub Actions
- Store `GH_TOKEN` as a GitHub repository secret (or use the built-in `GITHUB_TOKEN` for Actions)
- The orchestrator process inherits both env vars; all child `claude -p` processes inherit them automatically
- Build a health check: if any agent fails with an auth error, log a warning and pause dispatching until the token is refreshed

### 4.2 Orchestrator (Python)

The orchestrator is a single Python process that runs 24/7. It has four subsystems:

#### 4.2.1 Issue Poller

Polls GitHub every N minutes for new issues matching automation criteria.

```
File: orchestrator/issue_poller.py

Responsibilities:
- Run `gh issue list --repo {GITHUB_REPO} --label "agent" --state open --json number,title,labels,body`
  (GH_TOKEN env var provides auth for private repo)
- Filter out issues that are already assigned to an agent (tracked in SQLite)
- Filter out issues that have been attempted >= MAX_RETRIES times
- Return a list of issue objects ready for dispatch
- NOTE: The issue `body` field contains the FULL IMPLEMENTATION PLAN.
  The agent reads this via `gh issue view {N}` at runtime — the poller
  only needs the body for logging/dashboard display purposes.

Configuration:
- POLL_INTERVAL_SECONDS: 300 (5 minutes)
- ISSUE_LABEL: "agent" (only issues with this label are picked up)
- MAX_ISSUE_RETRIES: 3 (after 3 failed attempts, mark as "needs-human")
```

#### 4.2.2 Agent Pool Manager

Manages the lifecycle of Claude Code agent subprocesses.

```
File: orchestrator/agent_pool.py

Responsibilities:
- Maintain a pool of up to MAX_CONCURRENT_AGENTS running agents
- For each dispatched agent:
  1. Create a git worktree via worktree.py (runs against TARGET_REPO_PATH)
  2. Spawn: `claude -p "<prompt>" --allowedTools "Read,Edit,Bash,Write" --output-format stream-json --verbose --max-turns 30`
     CRITICAL: The subprocess cwd is set to the WORKTREE directory (e.g., ~/my-project-worktrees/issue-42),
     NOT the orchestrator directory. This way claude -p runs inside the target codebase.
  3. Pass env vars to subprocess: CLAUDE_CODE_OAUTH_TOKEN + GH_TOKEN (both inherited from parent)
  4. Capture stdout (stream-json) in a reader thread, push events to the Event Store
  5. Track process state (running, completed, failed) in Agent State DB
- When an agent process exits:
  - Parse final output for success/failure
  - If PR was created: update Agent State, begin monitoring the PR
  - If failed: increment retry count, clean up worktree, re-queue if under retry limit
- Clean up finished worktrees via worktree.py

Configuration:
- MAX_CONCURRENT_AGENTS: 3 (start conservative, scale up)
- AGENT_MAX_TURNS: 30
- AGENT_TIMEOUT_SECONDS: 1800 (30 minutes hard timeout)
```

**Agent prompt template for new issues:**

The issue body contains a **full implementation plan** (like Claude Code plan mode output). The agent reads it as its complete spec.

```
Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: Implement the feature or fix described in issue #{issue_number}.

Step 1 — Read the implementation plan:
Run `gh issue view {issue_number}` to read the full issue description.
The issue body contains a DETAILED IMPLEMENTATION PLAN. This is your complete spec.
Read it carefully — it describes exactly what to build, which files to modify,
what approach to take, and any edge cases to handle.

Step 2 — Implement:
Follow the plan in the issue body step by step.
Follow AGENT.md coding standards for all code you write.

Step 3 — Test:
Run the project's test suite to verify your changes work.
If tests fail, fix the issues and re-run tests until they pass.

Step 4 — Commit and push:
Stage your changes and commit with a descriptive message referencing #{issue_number}.
Push the branch: `git push -u origin fix/issue-{issue_number}`

Step 5 — Create PR:
Create a PR: `gh pr create --title "Fix #{issue_number}: <concise title>" --body "Closes #{issue_number}\n\n<summary of what was implemented based on the plan>"`

Important:
- The issue body IS the plan. Follow it precisely.
- Do NOT modify files unrelated to what the plan specifies.
- If the plan is unclear or something seems wrong, create the PR as a draft and note your questions in the PR body.
- Always run tests before creating the PR.
```

**Agent prompt template for fixing PR review comments:**

```
Read the AGENT.md file at the root of this repository FIRST and follow every guideline strictly.

Your task: Fix all review comments on PR #{pr_number}.

Steps:
1. Run `gh pr view {pr_number} --comments` to see the PR description and all comments.
2. Run `gh api repos/{owner}/{repo}/pulls/{pr_number}/comments` to get all inline review comments.
3. For each review comment, understand the issue and implement the fix.
4. Run the project's test suite to verify your changes.
5. If tests fail, fix the issues and re-run tests.
6. Commit all fixes with message: "fix: address review comments on PR #{pr_number}"
7. Push to the existing branch.

Important:
- Address EVERY comment — do not skip any.
- Do NOT modify files unrelated to the review comments.
- If a comment is unclear, add a reply comment asking for clarification using `gh pr comment`.
```

#### 4.2.3 PR Review Monitor

Watches open PRs created by agents for new review comments from CI.

```
File: orchestrator/pr_monitor.py

Responsibilities:
- Track all PRs created by agents (from Agent State DB)
- Poll each PR for:
  - New review comments: `gh api repos/{owner}/{repo}/pulls/{pr_number}/comments`
  - CI check status: `gh pr checks {pr_number} --json name,state,conclusion`
- Decision logic:
  - If CI checks all pass AND no unresolved comments → Mark issue as resolved, close
  - If CI checks fail OR new comments exist → Dispatch a "fix" agent
  - If fix attempts >= MAX_PR_FIX_RETRIES → Label PR "needs-human", stop retrying
- Track the number of fix iterations per PR

Configuration:
- PR_POLL_INTERVAL_SECONDS: 120 (2 minutes)
- MAX_PR_FIX_RETRIES: 5 (max review→fix cycles before escalation)
- CI_WAIT_TIMEOUT_SECONDS: 600 (wait up to 10 min for CI to complete)
```

#### 4.2.4 Dashboard Server

A FastAPI web server that reads from the Event Store and Agent State DB.

```
File: orchestrator/dashboard.py

Responsibilities:
- Serve a web UI at http://localhost:8420
- API endpoints:
  - GET /api/agents          → list all agents with current status
  - GET /api/agents/{id}/logs → stream-json events for a specific agent (supports ?since=N for polling)
  - GET /api/issues          → all tracked issues and their state
  - GET /api/prs             → all tracked PRs and their review loop count
  - GET /api/metrics         → aggregate stats (success rate, avg turns, active agents, queue depth)
- The frontend is a single React (or plain HTML) page that:
  - Shows a card per active agent with: issue title, branch, status, turns used, live log tail
  - Shows a queue of pending issues
  - Shows PR status (awaiting CI, fixing comments, iteration count)
  - Shows aggregate metrics: issues resolved today, total cost estimate, success rate
  - Auto-refreshes every 3 seconds via polling
```

### 4.3 Data Store (SQLite)

Two tables in a single SQLite database at `orchestrator/swarm.db`:

```sql
-- Tracks every issue the system has seen
CREATE TABLE issues (
    issue_number INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    -- status: pending | in_progress | pr_created | resolved | needs_human
    agent_id TEXT,
    pr_number INTEGER,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tracks every agent invocation
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY,  -- e.g., "agent-issue-42-attempt-1"
    issue_number INTEGER,
    pr_number INTEGER,
    agent_type TEXT NOT NULL,   -- "implement" or "fix_review"
    status TEXT NOT NULL DEFAULT 'running',
    -- status: running | completed | failed | timeout
    worktree_path TEXT,
    branch_name TEXT,
    turns_used INTEGER DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (issue_number) REFERENCES issues(issue_number)
);

-- Stores stream-json events for the dashboard
CREATE TABLE agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    event_type TEXT,        -- "tool_use", "text", "error", "result"
    event_data TEXT,        -- raw JSON from stream-json
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

-- Tracks PR review loop iterations
CREATE TABLE pr_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number INTEGER NOT NULL,
    iteration INTEGER NOT NULL,
    comments_count INTEGER,
    agent_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    -- status: pending | fixing | fixed | failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);
```

### 4.4 Git Worktree Management

Each agent works in an isolated worktree to prevent conflicts.

```
File: orchestrator/worktree.py

IMPORTANT: All git commands run against the TARGET REPO, not the swarm orchestrator directory.
Worktrees are created as siblings of the target repo (in WORKTREE_DIR), not inside it.

Functions:
- create_worktree(issue_number, base_branch="main") -> str (path)
    Runs (from TARGET_REPO_PATH):
      git -C {TARGET_REPO_PATH} worktree add {WORKTREE_DIR}/issue-{N} -b fix/issue-{N} {base_branch}
    Returns: absolute path to worktree (e.g., ~/my-project-worktrees/issue-42)

- create_worktree_for_pr(pr_number, branch_name) -> str (path)
    Runs (from TARGET_REPO_PATH):
      git -C {TARGET_REPO_PATH} worktree add {WORKTREE_DIR}/pr-fix-{N} {branch_name}
    Returns: absolute path to worktree

- cleanup_worktree(path)
    Runs: git -C {TARGET_REPO_PATH} worktree remove {path} --force

- list_worktrees() -> list
    Runs: git -C {TARGET_REPO_PATH} worktree list --porcelain
    Returns: list of active worktree paths

- ensure_repo_updated()
    Runs: git -C {TARGET_REPO_PATH} fetch origin && git -C {TARGET_REPO_PATH} pull origin {BASE_BRANCH}
    Called before creating new worktrees to ensure agents start from latest code.

Conflict prevention:
- Before creating a worktree, check Agent State DB for any running agent on the same issue
- The orchestrator NEVER dispatches two agents for the same issue simultaneously
- For PR fixes, only one fix agent runs per PR at a time
```

### 4.5 GitHub Actions Bug Finder (Existing — `rekpero/claude-bugbot-github-action`)

**You already have this.** The bug finder action at `rekpero/claude-bugbot-github-action` is already set up in your repo. It checks the PR diff and posts bug comments directly on the PR. No new CI reviewer needs to be built.

**What it does:**
- Triggers on PR open / new push (synchronize)
- Analyzes the diff for bugs, logic errors, and issues
- Posts structured comments on the PR pointing to specific lines

**What the orchestrator needs to know about it:**
- The PR Monitor (section 4.2.3) reads comments posted by this action — it doesn't care who posted them
- The monitor polls `gh api repos/{owner}/{repo}/pulls/{pr_number}/comments` and treats ALL comments as issues to fix
- When the bugbot posts zero comments after a push, the PR is considered clean

**Integration with the swarm:**
```
Agent creates PR → bugbot action triggers → bugbot posts comments
                                                    ↓
PR Monitor detects comments → dispatches fix agent → fix agent pushes
                                                    ↓
                              bugbot triggers again → fewer/zero comments
                                                    ↓
                              (loop until zero comments)
```

**No changes needed to your existing action.** The orchestrator simply reacts to whatever comments appear on the PR, regardless of source. If you later add more CI checks (linter, tests, etc.), the same loop handles those comments too.

### 4.6 Dashboard Frontend

```
File: orchestrator/static/index.html (single-page app)

Layout:
┌─────────────────────────────────────────────────────────────────┐
│  SWARM DASHBOARD                              Agents: 3/5 active│
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  METRICS BAR                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Resolved │ │ In Queue │ │ Fixing   │ │ Needs    │           │
│  │ Today: 7 │ │ 4 issues │ │ PRs: 2   │ │ Human: 1 │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                  │
│  ACTIVE AGENTS                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ ● Agent: issue-42         Status: RUNNING                │   │
│  │   Issue: "Fix auth token expiry"                         │   │
│  │   Branch: fix/issue-42    Turns: 12/30                   │   │
│  │   Started: 4 min ago                                     │   │
│  │                                                           │   │
│  │   > [12:03:25] Bash: npm test -- --grep "auth"           │   │
│  │   > [12:03:22] Edit: src/auth/token.ts lines 42-58      │   │
│  │   > [12:03:18] Read: src/auth/token.ts                   │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ ● Agent: pr-fix-87       Status: RUNNING                 │   │
│  │   PR: #101 (fix iteration 2/5)                           │   │
│  │   Fixing: 3 review comments                              │   │
│  │   Branch: fix/issue-87    Turns: 6/20                    │   │
│  │                                                           │   │
│  │   > [12:05:01] Bash: gh api repos/.../comments           │   │
│  │   > [12:05:05] Read: src/api/handler.ts                  │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ISSUE QUEUE                                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ #103 - Add rate limiting to /api/upload      [pending]   │   │
│  │ #105 - Fix memory leak in WebSocket handler  [pending]   │   │
│  │ #108 - Update README for v2 API              [pending]   │   │
│  │ #91  - Refactor auth middleware     [needs-human, 3/3]   │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  PR TRACKER                                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ PR #99  - Fix #42: Auth token expiry    [CI running]     │   │
│  │ PR #101 - Fix #87: API error handling   [fixing, iter 2] │   │
│  │ PR #98  - Fix #39: Cache invalidation   [merged ✓]       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

Tech: Plain HTML + vanilla JS + fetch() polling every 3s.
No build step, no React, no dependencies. Just serve static files from FastAPI.
```

---

## 5. File Structure

The swarm orchestrator and the target repo are **completely separate directories**.

```
~/claude-swarm/                   ← SWARM ORCHESTRATOR (this project)
├── orchestrator/
│   ├── __init__.py
│   ├── main.py                   # Entry point — starts all subsystems
│   ├── config.py                 # All configuration constants + .env loading
│   ├── issue_poller.py           # Polls GitHub for new issues
│   ├── agent_pool.py             # Manages agent subprocess lifecycle
│   ├── pr_monitor.py             # Monitors PRs for review comments
│   ├── worktree.py               # Git worktree create/cleanup helpers
│   ├── stream_parser.py          # Parses claude stream-json output
│   ├── db.py                     # SQLite database setup + queries
│   ├── dashboard.py              # FastAPI server for dashboard API
│   ├── prompts.py                # Agent prompt templates
│   ├── static/
│   │   └── index.html            # Dashboard single-page frontend
│   └── swarm.db                  # SQLite database (auto-created)
├── .env                          # CLAUDE_CODE_OAUTH_TOKEN + GH_TOKEN + TARGET_REPO_PATH + GITHUB_REPO
├── requirements.txt              # Python dependencies
└── README.md                     # Setup instructions

~/my-project/                     ← TARGET REPO (your codebase — pointed to by TARGET_REPO_PATH)
├── .github/
│   └── workflows/
│       └── (your existing bugbot action)
├── AGENT.md                      # Project guidelines for agents
├── CLAUDE.md                     # Claude Code auto-discovery file (references AGENT.md)
├── src/                          # Your actual code
└── ...

~/my-project-worktrees/           ← WORKTREES (auto-created by orchestrator, sibling of target repo)
├── issue-42/                     # Agent 1's isolated copy
├── issue-87/                     # Agent 2's isolated copy
└── pr-fix-101/                   # Agent 3's isolated copy (fixing review comments)
```

---

## 6. Configuration

All configuration lives in `orchestrator/config.py` and can be overridden via environment variables:

```python
# orchestrator/config.py
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# === Authentication ===
# Claude Code Max plan (NO Anthropic API key)
CLAUDE_CODE_OAUTH_TOKEN = os.environ["CLAUDE_CODE_OAUTH_TOKEN"]
# GitHub PAT for private repo access (gh CLI picks this up automatically)
GH_TOKEN = os.environ["GH_TOKEN"]

# === Repository ===
GITHUB_REPO = os.environ.get("GITHUB_REPO", "owner/repo")  # e.g., "rekpero/my-project"
BASE_BRANCH = os.environ.get("BASE_BRANCH", "main")

# === Target Repo Path ===
# CRITICAL: The swarm orchestrator is a SEPARATE project from the target repo.
# TARGET_REPO_PATH points to the local clone of the repo where agents will work.
# Worktrees are created INSIDE the target repo's directory structure.
# Example: if swarm lives at ~/swarm/ and your project at ~/my-project/,
#          set TARGET_REPO_PATH=~/my-project
TARGET_REPO_PATH = Path(os.environ["TARGET_REPO_PATH"]).resolve()

# === Issue Polling ===
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
ISSUE_LABEL = os.environ.get("ISSUE_LABEL", "agent")
MAX_ISSUE_RETRIES = int(os.environ.get("MAX_ISSUE_RETRIES", "3"))

# === Agent Pool ===
MAX_CONCURRENT_AGENTS = int(os.environ.get("MAX_CONCURRENT_AGENTS", "3"))
AGENT_MAX_TURNS_IMPLEMENT = int(os.environ.get("AGENT_MAX_TURNS_IMPLEMENT", "30"))
AGENT_MAX_TURNS_FIX = int(os.environ.get("AGENT_MAX_TURNS_FIX", "20"))
AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "1800"))

# === PR Review Loop ===
PR_POLL_INTERVAL_SECONDS = int(os.environ.get("PR_POLL_INTERVAL_SECONDS", "120"))
MAX_PR_FIX_RETRIES = int(os.environ.get("MAX_PR_FIX_RETRIES", "5"))
CI_WAIT_TIMEOUT_SECONDS = int(os.environ.get("CI_WAIT_TIMEOUT_SECONDS", "600"))

# === Dashboard ===
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8420"))

# === Paths ===
# Worktrees are created as siblings of the target repo to avoid polluting it
# e.g., if TARGET_REPO_PATH=/home/user/my-project, worktrees go to /home/user/my-project-worktrees/
WORKTREE_DIR = Path(os.environ.get("WORKTREE_DIR", str(TARGET_REPO_PATH.parent / f"{TARGET_REPO_PATH.name}-worktrees")))
DB_PATH = os.environ.get("DB_PATH", "orchestrator/swarm.db")
```

**Example `.env` file for the orchestrator:**

```bash
# .env (in the swarm orchestrator directory — NOT in the target repo)
CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
GH_TOKEN=ghp_...
GITHUB_REPO=rekpero/my-project
TARGET_REPO_PATH=/home/user/my-project
BASE_BRANCH=main
MAX_CONCURRENT_AGENTS=3
DASHBOARD_PORT=8420
```

---

## 7. Data Flow — Complete Lifecycle of an Issue

```
Step 1: Issue Created
  Human creates GitHub issue with label "agent".
  The issue body contains a FULL IMPLEMENTATION PLAN — detailed steps,
  files to modify, approach, edge cases (like plan mode output from Claude Code).

Step 2: Issue Poller Detects It (every 5 min)
  `gh issue list --repo {GITHUB_REPO} --label agent --state open --json number,title,labels,body`
  (uses GH_TOKEN env var for private repo auth)
  → Issue #42 found, not in DB → insert into `issues` table as "pending"

Step 3: Agent Pool Dispatches Agent
  Check: active agents < MAX_CONCURRENT_AGENTS? Yes.
  → Fetch latest: `git -C {TARGET_REPO_PATH} fetch origin && git pull origin main`
  → Create worktree: `git -C {TARGET_REPO_PATH} worktree add {WORKTREE_DIR}/issue-42 -b fix/issue-42 main`
  → Spawn process (cwd = worktree, NOT orchestrator dir):
      claude -p "<implement prompt for #42>" \
        --allowedTools "Read,Edit,Bash,Write" \
        --output-format stream-json \
        --verbose \
        --max-turns 30
      (env: CLAUDE_CODE_OAUTH_TOKEN + GH_TOKEN inherited)
  → Insert into `agents` table as "running"
  → Update `issues` table: status = "in_progress"
  → Start streaming thread: reads stdout line by line, inserts into `agent_events`

Step 4: Agent Works (inside the worktree, which is a full copy of the target repo)
  Agent reads AGENT.md → reads issue via `gh issue view` (gets the full implementation plan)
  → follows the plan step by step → edits files → runs tests → commits → pushes → creates PR
  All activity visible in dashboard via stream-json events.

Step 5: Agent Completes
  Process exits with code 0.
  → Parse output: extract PR number from `gh pr create` output
  → Update `agents` table: status = "completed"
  → Update `issues` table: status = "pr_created", pr_number = 99
  → Clean up worktree

Step 6: Bug Finder Runs on PR #99
  Your existing `rekpero/claude-bugbot-github-action` triggers on PR push.
  → Analyzes the diff for bugs and issues
  → If bugs found: posts comments on the PR pointing to specific lines
  → If no bugs: no comments posted

Step 7: PR Monitor Detects Review Comments (every 2 min)
  `gh api repos/{owner}/{repo}/pulls/99/comments` → 3 comments found
  `gh pr checks 99` → CI failed
  → Insert into `pr_reviews`: iteration 1, 3 comments
  → Dispatch fix agent:
      Create worktree for PR branch
      claude -p "<fix review comments prompt for PR #99>" --max-turns 20
  → Agent reads comments, fixes code, runs tests, pushes

Step 8: CI Runs Again
  New push triggers CI again.
  → This time: 1 comment (1 remaining issue)
  → PR Monitor dispatches another fix agent (iteration 2)

Step 9: All Issues Fixed
  CI passes. `gh pr checks 99` → all passing, 0 new comments.
  → Update `issues` table: status = "resolved"
  → Optionally: auto-merge if configured

Step 10: Escalation (if needed)
  If iteration count hits MAX_PR_FIX_RETRIES (5):
  → Update `issues` table: status = "needs_human"
  → Add label "needs-human" to the GitHub issue
  → Stop retrying, move on to next issue
```

---

## 8. CLAUDE.md File (Required in Repo Root)

This file is auto-loaded by Claude Code at the start of every agent session. It should reference your AGENT.md:

```markdown
# CLAUDE.md

## CRITICAL: Read AGENT.md First
Before making ANY changes, read and follow all guidelines in @AGENT.md.

## Project Context
- Repository: {your repo description}
- Language: {language}
- Test command: `npm test` (or whatever your test command is)
- Lint command: `npm run lint`
- Build command: `npm run build`

## Workflow Rules for Automated Agents
1. ALWAYS read AGENT.md before starting work.
2. ALWAYS run tests before creating a PR or pushing fixes.
3. NEVER modify files unrelated to your assigned issue.
4. NEVER push directly to main. Always use feature branches.
5. Reference the issue number in every commit message.
6. If you cannot complete the task, create a draft PR explaining what's blocking you.
7. Keep commits atomic and focused. One logical change per commit.
```

---

## 9. Implementation Order

Build and test in this exact order. Each phase should be fully working before moving to the next.

### Phase 1: Foundation (Day 1)
1. Set up project structure (`orchestrator/` directory, `requirements.txt`) — this is a STANDALONE project, separate from the target repo
2. Implement `config.py` with all configuration constants including `TARGET_REPO_PATH`, `GH_TOKEN`, and `CLAUDE_CODE_OAUTH_TOKEN`
3. Implement `db.py` with SQLite schema creation and basic CRUD operations
4. Implement `worktree.py` with create/cleanup/list functions — all git commands run against `TARGET_REPO_PATH`, worktrees created in sibling directory
5. Implement `prompts.py` with both prompt templates (implement with plan-from-issue-body + fix review)
6. Add startup validation: verify `TARGET_REPO_PATH` exists, is a git repo, `GH_TOKEN` works (`gh auth status`), `claude` CLI is available
7. Test: manually run `claude -p` with the implement prompt on a test issue in the target repo

### Phase 2: Agent Lifecycle (Day 2)
1. Implement `stream_parser.py` — parse stream-json lines into structured events
2. Implement `agent_pool.py` — spawn agents, capture streams, track state
3. Implement `issue_poller.py` — poll GitHub, filter, deduplicate
4. Wire them together in `main.py` with a basic polling loop
5. Test: orchestrator picks up a labeled issue and dispatches an agent that creates a PR

### Phase 3: Review Loop (Day 3)
1. Implement `pr_monitor.py` — poll PRs for comments and CI status
2. Add the "fix review comments" dispatch path to `agent_pool.py`
3. Verify `rekpero/claude-bugbot-github-action` is configured on the target repo (already exists — no new workflow needed)
4. Implement retry counting and escalation logic
5. Test: full loop — issue → agent → PR → bugbot posts comments → fix agent → bugbot finds zero bugs

### Phase 4: Dashboard (Day 4)
1. Implement `dashboard.py` FastAPI server with all API endpoints
2. Build `static/index.html` dashboard frontend
3. Add real-time log streaming from agent_events table
4. Add metrics aggregation endpoint
5. Test: open dashboard while agents are running, verify live updates

### Phase 5: Hardening (Day 5)
1. Add agent timeout enforcement (kill process after AGENT_TIMEOUT_SECONDS)
2. Add graceful shutdown (SIGTERM handler, wait for running agents, clean up worktrees)
3. Add token refresh health check (detect auth failures, pause dispatching)
4. Add file overlap detection (prevent two agents touching same files)
5. Add logging throughout (structured JSON logs to stdout + file)
6. Test: kill orchestrator mid-run, restart, verify it recovers state from DB

---

## 10. Dependencies

### Python (requirements.txt)
```
fastapi>=0.104.0
uvicorn>=0.24.0
python-dotenv>=1.0.0
```

### System Requirements
- Python 3.10+
- Claude Code CLI (`claude`) installed and authenticated via `claude setup-token`
- GitHub CLI (`gh`) installed and authenticated
- Git 2.20+ (for worktree support)
- Node.js / npm (if your project requires it for tests)

### GitHub Repository Requirements (target repo — private)
- Repository must be cloned locally at the path specified by `TARGET_REPO_PATH`
- `GH_TOKEN` (fine-grained PAT) with permissions: Contents, Issues, Pull Requests, Metadata on the target repo
- `CLAUDE_CODE_OAUTH_TOKEN` added as a repository secret (for bugbot GitHub Action)
- `AGENT.md` present at repository root with coding guidelines
- `CLAUDE.md` present at repository root (see Section 8)
- `rekpero/claude-bugbot-github-action` already configured (analyzes diffs and posts bug comments on PRs)
- Issues to be automated must carry the configured label (default: "agent")
- Issues must contain the full implementation plan in the body (detailed steps, files to modify, approach)

---

## 11. Trade-offs and Risks

| Decision | Trade-off | Mitigation |
|----------|-----------|------------|
| `claude -p` CLI over Agent SDK | Less programmatic control, but required for Max plan billing | stream-json gives sufficient observability; CLI flags cover most needs |
| SQLite over PostgreSQL | Single-writer limitation, but zero ops overhead | For a single orchestrator process, SQLite is more than sufficient |
| Polling over webhooks | Slight delay (up to poll interval), but simpler to implement and debug | 2-5 minute intervals are fine for this use case; webhooks can be added later |
| Max concurrent agents = 3 | Conservative, may under-utilize Max plan capacity | Start at 3, monitor for throttling, increase incrementally |
| Plain HTML dashboard over React | Less interactive, but zero build step, instant to modify | Fetch polling at 3s is sufficient for monitoring; add WebSocket later if needed |
| Git worktrees over full clones | Shares .git directory (disk efficient), but all worktrees share the same remote | Agents only push to their own branches, so no conflicts |
| Flat retry limits | May abandon solvable issues too early | Start with 3 issue retries / 5 PR fix retries, tune based on observed success rates |

---

## 12. Future Enhancements (Post-MVP)

These are NOT part of the initial implementation but should be considered for v2:

1. **Webhook-driven instead of polling:** Set up GitHub webhooks to trigger agent dispatch instantly when issues are labeled
2. **Agent-to-agent review:** Before creating a PR, spawn a second agent to review the first agent's code
3. **Slack/Discord notifications:** Alert on completions, failures, and escalations
4. **Cost tracking dashboard:** Parse token usage from stream-json metadata and display estimated cost per agent
5. **Priority queuing:** Process issues by priority label (P0 before P1, etc.)
6. **Resumable agents:** Use `claude --resume <session-id>` to continue a failed agent's work instead of starting fresh
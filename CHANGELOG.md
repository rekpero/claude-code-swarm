# Changelog

All notable changes to Claude Code Agent Swarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-02-27

Initial release of the Claude Code Agent Swarm — a 24/7 autonomous orchestrator that watches a GitHub repository for open issues, dispatches parallel Claude Code agents, creates PRs, and handles CI review feedback in a loop.

### Added

#### Core Orchestration
- Continuous polling loop that watches GitHub for open issues labeled for automation
- Parallel agent dispatch with configurable concurrency (default: 3 agents)
- Full issue lifecycle management: `pending` -> `in_progress` -> `pr_created` -> `resolved`
- Trigger mention system (`@claude-swarm`) — agents only start when explicitly activated via issue comment, so plans can be drafted without premature dispatch
- Configurable poll intervals for issues (default: 5 min) and PRs (default: 2 min)
- Graceful shutdown on SIGINT/SIGTERM with agent cleanup and worktree removal

#### Agent Management
- Subprocess-based agent spawning via `claude -p` (headless CLI mode) with Max plan billing via `setup-token`
- Two agent types: `implement` (new issues) and `fix_review` (PR comment fixes)
- Per-agent turn limits (30 for implementation, 20 for fixes) and hard timeout (30 min)
- Real-time stream-json output parsing with event classification (tool_use, assistant, error, result)
- Automatic PR number extraction from agent output
- Agent timeout enforcement with graceful termination and force kill fallback

#### Git Worktree Isolation
- Each agent works in an isolated git worktree (sibling of target repo)
- Automatic repo fetch/pull before worktree creation to ensure agents start from latest code
- Stale worktree cleanup on agent completion, failure, or orchestrator restart
- Branch naming convention: `fix/issue-{number}` for new issues

#### PR Review Loop
- Automatic detection of review comments on agent-created PRs
- CI check status monitoring (pending, passed, failed)
- Dispatches fix agents when new comments or CI failures are detected
- Iterative fix cycle with configurable retry limit (default: 5 iterations)
- Automatic issue resolution when PR is clean (0 comments + CI passed)
- Escalation to `needs-human` label after max retries exhausted

#### Agent Prompts
- Structured implementation prompt: reads AGENT.md, fetches issue plan via `gh issue view`, implements, tests, commits, pushes, and creates PR
- Structured fix prompt: reads all review comments via `gh api`, addresses each one, runs tests, commits, and pushes

#### SQLite Database
- Thread-safe SQLite with WAL mode for concurrent access
- Four tables: `issues`, `agents`, `agent_events`, `pr_reviews`
- Full CRUD operations for issue tracking, agent lifecycle, event logging, and PR review iterations
- Aggregate metrics: active agents, resolved/pending/in-progress counts, average turns

#### Dashboard
- FastAPI web server at `http://localhost:8420`
- REST API endpoints: `/api/metrics`, `/api/agents`, `/api/agents/{id}/logs`, `/api/issues`, `/api/prs`
- Single-page dashboard with dark theme (plain HTML + vanilla JS, no build step)
- Real-time metrics bar: resolved, pending, in progress, open PRs, needs human, avg turns
- Active agent cards with live log stream (last 10 events per agent)
- Issue queue table with status badges, retry counts, and timestamps
- PR tracker table with iteration counts and comment totals
- Auto-refresh every 3 seconds via polling

#### Service Management (`run.sh`)
- One-command systemd installation: `sudo ./run.sh install`
- Automatic Python venv creation and dependency installation
- Interactive `.env` setup wizard when no config exists
- Python 3.10+ version validation
- Commands: `start`, `stop`, `restart`, `status`, `logs`, `install`, `uninstall`
- Fallback to nohup + PID file when systemd is not available
- Auto-start on boot and auto-restart on crash (via systemd)

#### Hardening & Recovery
- Stale agent recovery on orchestrator restart (marks orphaned agents as failed, resets issues to pending)
- Consecutive error backoff (exponential, up to 10 min) to avoid hammering on repeated failures
- Environment validation at startup: checks tokens, target repo path, git repo, CLI tools (`claude`, `gh`, `git`)
- Configuration print with secret redaction

#### Configuration
- All settings configurable via `.env` file or environment variables
- Tokens: `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`
- Repository: `GITHUB_REPO`, `TARGET_REPO_PATH`, `BASE_BRANCH`
- Tuning: `MAX_CONCURRENT_AGENTS`, `AGENT_MAX_TURNS_IMPLEMENT`, `AGENT_MAX_TURNS_FIX`, `AGENT_TIMEOUT_SECONDS`
- Polling: `POLL_INTERVAL_SECONDS`, `PR_POLL_INTERVAL_SECONDS`
- Safety: `MAX_ISSUE_RETRIES`, `MAX_PR_FIX_RETRIES`, `TRIGGER_MENTION`
- Paths: `WORKTREE_DIR`, `DB_PATH`, `DASHBOARD_PORT`

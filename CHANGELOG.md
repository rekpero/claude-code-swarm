# Changelog

All notable changes to Claude Code Agent Swarm will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.15] - 2025-03-01

### Added
- **Merge-gated resolution**: PRs now only resolve their issue when the PR is actually merged on GitHub — previously a "clean" PR (0 comments + CI passed) was immediately marked resolved, which was premature when human review or merge approval was still pending
- `is_pr_merged()` helper in `pr_monitor.py` — checks PR state via `gh pr view --json state,mergedAt`
- Dashboard: live turn count for running agents — agents that haven't finished yet now show a real-time turn count computed from their `assistant` events instead of showing 0
- `get_agent_turn_count()` query in `db.py` — counts assistant events per agent from the events table
- Dashboard: `formatToolUse()` helper for concise tool invocation summaries — Bash shows `$ cmd`, Read/Edit/Write show file paths, Skill shows skill name
- Dashboard: `Skill` tool formatting in log stream
- Dashboard: thinking block display — assistant thinking is shown in dimmed italic text
- Dashboard: `rate_limit_event` and `user` event type styling (yellow for rate limits, dimmed for user/tool-result events)
- Stream parser: assistant events now include inline tool_use block summaries (e.g. `[$ git status]`, `[Read file.py]`, `[Skill: frontend-design]`) and thinking block content

### Changed
- PR monitor: "Resolving issue" log messages changed to "Awaiting merge for issue" — reflects the new merge-gated workflow
- PR monitor: clean PRs (0 unresolved threads, CI passed) no longer auto-resolve — they stay in `pr_created` status until the PR is merged
- Issue poller: removed re-check logic that reset `resolved` issues back to `pr_created` when their PR was still open — no longer needed since issues are only resolved on merge
- Stream parser: updated docstring to reflect the actual stream-json message types (`user`, `rate_limit_event`, etc.)
- Dashboard: `system` init events now show session working directory; other system events suppress raw JSON noise
- Dashboard: `user` events (tool results) are filtered out to reduce log noise
- Dashboard: `lastId` tracking moved before skip logic to prevent re-processing of filtered events

---

## [1.0.14] - 2025-02-28

### Added
- **Skills support**: agents can now use [Claude Code skills](https://skills.sh) — reusable capabilities that give agents domain expertise (frontend design, testing, security, API design, etc.)
- Skill discovery at startup: the orchestrator scans `.claude/skills/` in the target repo and `~/.claude/skills/` globally, then injects a skills hint into every agent prompt
- `Skill` tool automatically added to each agent's `--allowedTools` when `SKILLS_ENABLED=true`
- `SKILLS_ENABLED` config flag (default: `true`) to toggle skill support on/off
- `run.sh install-skills` command — installs skills from default repos (`anthropics/skills`, `vercel-labs/agent-skills`) into the target repo's `.claude/skills/` using `--copy` mode (symlinks break in worktrees)
- `run.sh install-skills` flags: `--global`, `--repo owner/repo`, `--skill name`, `--list`
- `run.sh list-skills` — shows currently installed skills (repo-local and global)
- `run.sh uninstall-skills` — removes all installed skills
- Skills hint injected into all prompt types: implement, fix-review, and their rate-limit resume variants

---

## [1.0.13] - 2025-02-27

### Added
- Dashboard: collapsible accordion logs for agent cards — completed/failed/timeout agents have their logs hidden by default with a "Show Logs" / "Hide Logs" toggle, keeping the dashboard clean
- Dashboard: expand/collapse state persists across 3-second polling cycles — opening an agent's logs won't snap closed on the next refresh
- Dashboard: smooth status transitions — when a running agent completes, the toggle is dynamically inserted and logs auto-collapse; when a rate-limited agent resumes, the toggle is removed and logs become visible again
- Dashboard: running and rate-limited agents always show logs with no toggle, so live activity is never hidden

---

## [1.0.12] - 2025-02-28

### Fixed
- Added SQLite WAL (`swarm.db-wal`) and SHM (`swarm.db-shm`) files to `.gitignore` — previously only the main DB file was ignored, causing WAL artifacts to show up in `git status`

---

## [1.0.11] - 2025-02-28

### Added
- Automatic database schema migration on startup — new columns (`pid`, `session_id`, `resume_count`, `rate_limited_at`, `comments_json`) are added to existing databases without data loss
- `_migrate_add_column()` helper that safely checks for column existence before altering the table

### Changed
- `init_db()` now runs migrations after creating the schema, so existing databases upgrade seamlessly on restart

---

## [1.0.10] - 2025-02-28

### Added
- `run.sh install` now auto-installs all system dependencies: Python 3, `python3-venv`, Node.js (v22 via NodeSource), GitHub CLI (`gh`), and Claude CLI (`@anthropic-ai/claude-code`)
- Systemd service file now includes a `PATH` that resolves `claude`, `gh`, and `node` — fixes agents failing in systemd because CLI tools weren't on the service `PATH`

### Changed
- Dependency installation is idempotent — each tool is only installed if missing
- `_ensure_venv()` simplified to always ensure pip deps are up to date on every start

---

## [1.0.9] - 2025-02-28

### Added
- Dashboard: "Rate Limited" metric card in the top metrics bar
- Dashboard: `rate_limited` and `resumed` status badges with distinct colors (yellow / blue)
- Dashboard: PR review thread details — click `[details]` on any PR row to expand and see unresolved review threads inline, with file paths, line numbers, and comment authors
- Dashboard: color-coded log event types — `assistant` (purple), `tool_use` (yellow), `result` (green), `error` (red), `system` (blue)

### Changed
- Dashboard: agent log stream is now incremental — only fetches new events since the last known ID, appends them to the DOM without destroying scroll position
- Dashboard: log container expanded from 150px to 500px max-height for better visibility
- Dashboard: agent cards update metadata (status, turns, etc.) in-place without rebuilding the entire DOM, preserving log scroll state
- Dashboard: `tryParseEventData()` rewritten with type-aware formatting — Bash commands show `$ cmd`, Read/Edit/Write show file paths, Grep shows patterns, tool_results are hidden to reduce noise
- Dashboard: auto-scroll only triggers if the user is already near the bottom of the log stream

---

## [1.0.8] - 2025-02-28

### Fixed
- Issue poller now detects existing open PRs when encountering a new issue — if a PR with branch `fix/issue-{N}` already exists, the issue is seeded as `pr_created` so the PR monitor picks it up instead of dispatching a duplicate agent
- Issues marked as `resolved` are now re-checked: if their PR is still open on GitHub, the issue is reset to `pr_created` for continued monitoring — prevents premature resolution before CI/review bots finish

---

## [1.0.7] - 2025-02-28

### Added
- Multi-step PR verification after implement agent completes:
  1. Extract PR number from agent events (existing behavior)
  2. Query GitHub API for PR matching branch `fix/issue-{N}` (new fallback)
  3. Check if branch was pushed to remote — if yes, auto-create the PR via `gh pr create`
  4. Check for unpushed local commits — if found, push branch and create PR
  5. If none of the above, mark agent as failed with descriptive error
- Helper methods: `_find_pr_for_branch()`, `_is_branch_pushed()`, `_has_unpushed_commits()`, `_push_branch()`, `_create_pr_for_branch()`

### Fixed
- Agents that complete their work but forget to run `gh pr create` no longer result in lost work — the orchestrator recovers by creating the PR automatically

---

## [1.0.6] - 2025-02-28

### Added
- New `RateLimitWatcher` background thread that periodically checks if rate limits have reset
- Lightweight Claude probe (`claude -p "Reply with just the word OK" --max-turns 1`) to test availability before resuming agents
- `resume_rate_limited_agent()` method on `AgentPool` — spawns a new agent subprocess in the preserved worktree with a continuation prompt
- Resume prompts for both `implement` and `fix_review` agent types that instruct the agent to assess current state (`git log`, `git diff`) and continue from where the previous agent stopped
- Session ID extraction from stream-json events — enables `claude --resume <session_id>` for seamless continuation, with `--continue` as fallback
- Configurable `RATE_LIMIT_RETRY_INTERVAL` (default: 5 min) and `MAX_RATE_LIMIT_RESUMES` (default: 5) settings

---

## [1.0.5] - 2025-02-28

### Added
- Rate limit detection: agent pool now recognizes rate/usage limit errors in both stderr output and stream-json error events using pattern matching (`rate limit`, `429`, `too many requests`, `overloaded`, etc.)
- Rate-limited agents are marked with `status = 'rate_limited'` instead of `failed` — their worktrees are preserved for later resumption
- `rate_limited_at` timestamp stored on the agent record for the watcher to use

### Changed
- Rate-limited agents do NOT count as failures — the issue stays `in_progress` and attempt count is not incremented
- `db.get_rate_limited_agents()` query added to retrieve all paused agents

---

## [1.0.4] - 2025-02-28

### Changed
- Agents now spawn with `start_new_session=True` — they survive orchestrator restarts as independent processes
- Agent PID is tracked in the database (`agents.pid` column)
- Stale agent recovery now checks if the agent's PID is still alive before marking it as failed — running agents are left alone to finish their work
- Graceful shutdown no longer kills running agents — they continue independently and are picked up on next startup
- Removed `--max-turns` from the `claude` CLI invocation — the agent timeout (`AGENT_TIMEOUT_SECONDS`) serves as the safety net instead, preventing silent mid-work stops on large features

---

## [1.0.3] - 2025-02-28

### Added
- GraphQL-based unresolved thread detection for PR reviews via `get_unresolved_threads()` — uses GitHub's `reviewThreads` API to get actual resolution status instead of relying on comment counts
- Thread-aware fix prompts: when GraphQL data is available, unresolved threads with file paths, line numbers, and full comment text are embedded directly in the agent prompt
- REST comment-count heuristic retained as automatic fallback when GraphQL fails
- PR review records now store full thread details as JSON (`comments_json` column) for dashboard display

### Fixed
- CI check status parsing updated to use `bucket` field (`"pending"`, `"fail"`) and correct `state` values (`"PENDING"`, `"FAILURE"`, `"ERROR"`) — fixes false positives where CI was incorrectly reported as passed
- PR monitor now waits for CI checks to appear before evaluating — prevents premature resolution when checks haven't started yet

---

## [1.0.2] - 2025-02-28

### Fixed
- Worktree creation now deletes stale branches from previous failed runs before creating a new worktree — prevents `git worktree add` failures when a branch already exists
- PR fix worktrees now reset to `origin/{branch}` after checkout — ensures the agent starts from the latest remote state even if the local branch is stale from a previous run

---

## [1.0.1] - 2025-02-28

### Fixed
- Fix review dispatch callback now accepts and forwards the optional `unresolved_threads` parameter, enabling thread-aware prompts from the PR monitor

### Changed
- PR monitor dispatch callback signature updated: `function(pr_number, branch_name, issue_number, unresolved_threads)` (4th argument added)

---

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

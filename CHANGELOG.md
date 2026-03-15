# Changelog

All notable changes to SwarmOps will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [1.4.2] - 2026-03-15

### Changed
- **Project renamed to SwarmOps** — all references to "Claude Code Agent Swarm" updated across `README.md`, `CHANGELOG.md`, `orchestrator/dashboard.py` (FastAPI title), `run.sh` (service descriptions), and `frontend/index.html` (page title)
- **Trigger mention default updated** to `@swarmops` in `.env.example` (was `@claude-swarm`)
- **README fully rewritten** to reflect the current state of the project: corrected Quick Start (added Node.js prerequisite, `./run.sh build-ui` step, credential setup notes), expanded Configuration table with `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, restored and expanded the Dashboard section covering the Live Progress view, AI Issue Planner, Environment File Manager, and Authentication panels, updated Architecture tree with `frontend/` source layout and `planner.py`

### Added
- **SwarmOps logo** — new brand identity with a three-bar parallel mark (two purple `#8b5cf6` bars + one emerald `#34d399` bar representing parallel agents and the orchestrator) and "SwarmOps" wordmark in InstrumentSans Bold with text converted to SVG paths via fonttools (fully self-contained, no font dependency)
- `frontend/public/logo.svg` — horizontal logo lockup (480×80 auto-fitted viewBox, no dead space)
- `frontend/public/logo-icon.svg` — square icon mark with dark rounded-square background
- `frontend/public/favicon.svg` — vector favicon
- Logo displayed in `Header.jsx` and `LoginPage.jsx`, replacing the previous animated dot + text

---

## [1.4.1] - 2026-03-15

### Added
- **Dashboard authentication**: all `/api/*` routes are now protected by session token auth — unauthenticated requests receive a `401` response ([#6](https://github.com/rekpero/claude-code-swarm/pull/6))
- **`ADMIN_USERNAME` / `ADMIN_PASSWORD` config vars**: credentials for dashboard login; `ADMIN_PASSWORD` is required and validated at startup with a warning if unset; both are displayed redacted in `print_config()`
- **`/api/auth/login`**, **`/api/auth/check`**, **`/api/auth/logout`** endpoints: stateless Bearer token flow — login returns a token stored in `localStorage`, check validates it, logout deletes the session
- **`sessions` table** in SQLite: stores session tokens with 30-day expiry; expired sessions are cleaned up on each new login; `create_session`, `get_session`, `delete_session`, `cleanup_expired_sessions` functions added to `db.py`
- **`AuthContext`** (`frontend/src/context/AuthContext.jsx`): `AuthProvider` + `useAuth` hook manage token state; API client injects `Authorization: Bearer <token>` header on every request and dispatches `swarm:unauthorized` only when a token was present (avoids conflating missing credentials with expired sessions)
- **`LoginPage`** component (`frontend/src/components/auth/LoginPage.jsx`): dark-theme login form matching the dashboard aesthetic; shows "Invalid username or password" on failure
- **Logout button** in `Header.jsx` — clears the session token and returns to the login page

### Fixed
- **Timing-safe credential comparison**: username and password comparisons are now evaluated unconditionally before being combined with `and`, eliminating the short-circuit timing side-channel that would have allowed username enumeration via response time
- **401 cascade on app load**: `useMetrics`, `useAgents`, `useIssues`, and `usePRs` hooks now accept an `enabled` option; `App.jsx` passes `enabled: isAuthenticated && !isChecking` so no API requests fire before authentication is confirmed, preventing a cascade of 401s on page load

---

## [1.4.0] - 2026-03-14

### Added
- **React 18 + Vite 5 frontend**: full SPA in `frontend/` replacing the inline HTML dashboard — uses Tailwind CSS 3, React Query v5, Lucide React icons, and date-fns
- **Complete component tree** preserving the existing dark color palette via CSS custom properties (`tokens.css`):
  - Layout: `Header`, `WorkspaceSwitcher`, `TabNav`
  - Metrics: `MetricsBar`, `MetricCard` (7-card grid)
  - Agents: `ActiveAgents`, `AgentCard`, `AgentLogViewer`, `AgentStatusBadge`
  - Issues: `IssueQueue`, `IssueStatusBadge` with per-row Retry button for `needs_human`
  - PRs: `PRTracker`, `ReviewThreads`
  - Modals: `AddWorkspaceModal`, `WorkspaceSettingsModal`, `EnvEditor`
  - Planner: `PlannerModal` with support for creating GitHub issues from specific assistant messages
  - UI primitives: `Card`, `Badge`, `Button` (polymorphic `as` prop), `Modal`, `Spinner`, `EmptyState`
- **Custom React hooks**: `useAgents`, `useIssues`, `useMetrics`, `usePRs`, `useWorkspaces`, `usePlanning`, `useGitSync` — encapsulate all API polling and mutation logic
- **WorkspaceContext** persists `selectedWorkspaceId` to `localStorage`
- **SPA catch-all route** in `dashboard.py` (registered after all `/api/*` routes) so React client-side navigation works on direct URL loads; guards against serving `index.html` for `api/*` paths (returns 404 instead)
- **`build-ui` command** in `run.sh` (`cd frontend && npm install && npm run build`), integrated into the `install` flow; UI is also rebuilt on orchestrator restart
- **Rich tool-use logging**: `WebSearch`, `WebFetch`, `Grep`, `Glob`, and `Agent` tool uses now display their key parameters (query, URL, pattern, description) in both the backend stream parser and frontend log viewer
- **`buildGitHubUrl` helper** with `owner/repo` validation and `encodeURIComponent` sanitization in `PRTracker` and `IssueQueue` to prevent URL injection

### Changed
- **Dashboard fully migrated from inline HTML + vanilla JS to React SPA** — Vite builds output directly to `orchestrator/static/` via `vite.config.js` `outDir` setting
- **PR statuses enriched from issue state** (merged/needs_human) and PRs sorted by status priority
- **Issues sorted by status priority** in the dashboard
- **Agents sorted with running instances first** in the dashboard
- **Reattached agents** (surviving an orchestrator restart) now compute `turns_used` from the `agent_events` table on completion; dashboard fallback dynamically calculates turns for any agent with `turns_used=0`
- **`/assets` static mount** is conditional — server logs a warning instead of crashing when the frontend hasn't been built yet
- `.gitignore` updated with `frontend/node_modules/` and `frontend/dist/`

### Fixed
- **AgentLogViewer**: accumulate events with ID-based deduplication instead of replacing on each poll; synchronous cursor reset with `cursorAgentIdRef` guard to prevent stale cached data from overwriting cursor on agent switch
- **EnvEditor**: merge-overwrite semantics for paste and file upload (existing keys are updated, not dropped); stable row IDs derived from variable names instead of `Math.random()`; separate `fileReadError` state so file-read errors aren't silently cleared by save actions; cancellation flag in `useEffect` to prevent race conditions on rapid file switches
- **WorkspaceSettingsModal**: error handlers on update and delete mutations; form fields reinitialise when workspace fields change while modal is open; `confirmDelete` resets when modal closes; form resets when workspace becomes null after deletion
- **PRTracker**: composite key `${github_repo}-${pr_number}` to prevent duplicate React keys across repos
- **IssueQueue**: per-row `retryingIssue` state so a single retry doesn't disable all Retry buttons
- **PlannerModal**: optional chaining guard on `streamEvents?.length`; `setTimeout` cleanup on rapid open/close; stable `loadSessions` reference in `useEffect` dependency array
- **API client**: fix header merging by destructuring `headers` from options before spread, preventing `options.headers` from overwriting the merged `Content-Type` header
- **EnvEditor `.env` parsing**: balanced quote matching regex instead of independent quote stripping

---

## [1.3.1] - 2026-03-13

### Changed
- **Expanded agent tool access**: implementation and fix-review agents now have access to `WebFetch`, `WebSearch`, `Agent`, `TodoWrite`, and `NotebookEdit` in addition to the existing core tools — enables agents to fetch web content, search the web, spawn subagents, track progress, and edit Jupyter notebooks
- **Expanded planner tool access**: planning agents now have access to `WebFetch`, `WebSearch`, and `Agent` in addition to `Read`, `Glob`, `Grep` — enables planners to research external documentation and delegate exploration to subagents

---

## [1.3.0] - 2026-03-13

### Added
- **Issue Planner** — AI-powered plan generation from the dashboard: select a workspace, describe a feature or bug, and Claude explores the codebase and produces a structured markdown implementation plan
- **`orchestrator/planner.py`** — new planning module that spawns a read-only `claude -p` agent (tools: `Read`, `Glob`, `Grep` only) in the workspace directory, streams events in real-time, and manages the full subprocess lifecycle (cancellation, timeout enforcement, status tracking)
- **Planning DB tables**: `planning_sessions` (session lifecycle and metadata) and `planning_messages` (multi-turn conversation history) added to `db.py` with full CRUD and cascade delete on workspace removal
- **`build_planning_prompt()`** in `prompts.py` — instructs Claude as a senior architect to explore the codebase and produce a structured plan (Summary, Files to Modify, Files to Create, Implementation Steps, Testing, Edge Cases); supports multi-turn refinement via conversation history
- **5 new REST endpoints** in `dashboard.py`: `POST /api/planning`, `GET /api/planning/{id}`, `POST /api/planning/{id}/messages`, `POST /api/planning/{id}/create-issue`, `POST /api/planning/{id}/cancel`
- **Real-time planning event stream**: `thinking`, `tool_use`, `tool_result`, `draft`, and `info` event types surface Claude's reasoning and codebase exploration live in the chat UI
- **AI-powered issue title generation** (`_generate_title_with_ai()`) — uses Claude to produce a concise GitHub issue title from the plan body, with regex fallback
- **Dashboard: planner UI** — "Plan Issue" button (visible when a workspace is selected), full-screen chat modal with scrollable history, inline markdown renderer (no external dependencies), 2-second polling during generation, cancel button, and "Create GitHub Issue" action that auto-labels with `ISSUE_LABEL` and returns the resulting URL
- **Dashboard: session sidebar** — persisted planner session history with resume support; previous sessions are listed and can be reopened for continued refinement
- **Conversational preamble stripping** — text before the first markdown heading is removed from the plan body before creating a GitHub issue, so the issue body starts cleanly at the structured plan

---

## [1.2.0] - 2026-03-12

### Removed
- **Legacy single-repo env vars**: `GITHUB_REPO`, `TARGET_REPO_PATH`, and `BASE_BRANCH` environment variables have been removed from `config.py`, `.env`, `.env.example`, `run.sh`, and `README.md` — all repository configuration is now managed exclusively through workspaces via the dashboard
- **`WORKTREE_DIR` global config**: worktree directories are now derived from each workspace's `local_path` (e.g. `{local_path}-worktrees`)
- **`ensure_default_workspace()` auto-migration**: the backward-compatibility function that created a default workspace from legacy env vars has been removed from `workspace_manager.py` and `main.py` — all workspaces must now be created via the dashboard

### Changed
- **`_workspace_config()` now requires a workspace dict** — the fallback to global `GITHUB_REPO`/`TARGET_REPO_PATH`/`WORKTREE_DIR` has been removed; all agent dispatch paths must provide a workspace
- **`worktree.py` functions require explicit parameters** — `create_worktree()`, `create_worktree_for_pr()`, `ensure_repo_updated()`, and `cleanup_all_worktrees()` no longer fall back to global config values; `repo_path`, `worktree_dir`, and `base_branch` must be passed by callers
- **Skills install globally by default** — `run.sh install-skills` no longer reads `TARGET_REPO_PATH` to determine a target repo; skills are installed to `~/.claude/skills/` by default
- **`run.sh` setup flow simplified** — interactive setup now only prompts for `CLAUDE_CODE_OAUTH_TOKEN` and `GH_TOKEN`

---

## [1.1.4] - 2026-03-07

### Fixed
- **Env files missing in agent worktrees**: `.env` files (including monorepo subdirectory env files like `marketplace/.env`) were not copied into git worktrees since they are gitignored — agents using dotenv or similar would fail to find any env configuration. Worktrees now receive copies of all `.env*` files from the source repo and any DB-managed env files from the dashboard.

---

## [1.1.3] - 2026-03-06

### Added
- **Git author identity config**: new `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` env vars so agent commits are attributed to a GitHub-recognised identity — avoids Vercel and other deploy platform rejections for unknown commit authors
- **Issue status update API**: `PUT /api/issues/{issue_number}/status` endpoint allows changing an issue's status (e.g. retrying a `needs_human` issue)
- **Dashboard: Retry button**: issues in `needs_human` status now show a "Retry" button that resets them to `pr_created` for another round of PR monitoring
- **Dashboard: agent list pagination** — `/api/agents` now supports server-side `limit` and `offset` parameters (default: 10 per page); the dashboard shows the most recent agents with a "Load More" button to fetch older ones, drastically reducing payload size when hundreds of agents exist

### Fixed
- **CI failure infinite loop**: when CI keeps failing after a `fix_review` agent completes with zero unresolved review threads, the PR monitor now escalates to `needs_human` instead of dispatching another fix agent — prevents endless loops on external failures (e.g. Vercel deploy config)

---

## [1.1.2] - 2026-03-06

### Fixed
- **Dashboard: excessive API polling eliminated** — workspaces, metrics, issues, and PRs were being polled every 3 seconds alongside agent logs; they are now on a separate 30-second slow-poll loop since they change infrequently
- **Dashboard: finished agent logs polled indefinitely** — log fetches for completed/failed/timeout agents continued firing every 3 seconds even after all events were loaded; agents are now marked `done` after a fetch returns no new events (or fewer than the page limit), and are skipped on all subsequent ticks
- **Dashboard: `selectWorkspace` calling deleted `poll()` function** — switching workspaces threw a JS error after the polling refactor; fixed to call `pollAll()`

### Changed
- Dashboard polling split into two independent intervals: **fast (3s)** for agent status and live logs, **slow (30s)** for workspaces, metrics, issues, and PRs

---

## [1.1.1] - 2026-03-04

### Fixed
- **Monorepo detection for non-standard layouts**: repos with top-level sub-project directories (containing `package.json`, `Dockerfile`, `Cargo.toml`, etc.) are now correctly detected as monorepos, not just those using standard `packages/`/`apps/` layouts
- **Env file upload accepts all file types**: removed restrictive `accept` attribute so `.txt`, `.env`, and any other file can be uploaded
- **Env upload + target path workflow**: uploading a `.env` file with a target path specified now correctly saves to that path; previously tab switching wiped the uploaded vars and only the current tab was saved
- **Multi-tab env var persistence**: all env file tabs are now saved on settings save (not just the active tab); introduced `settingsAllEnvVars` multi-tab cache and `_collectCurrentEnvRows()` helper to preserve DOM state across tab switches

### Added
- **Local path display**: workspace settings panel now shows the local clone path for reference

---

## [1.1.0] - 2025-03-04

### Added
- **Multi-workspace support**: manage multiple GitHub repositories from a single orchestrator instance — add workspaces by URL, auto-clone, and switch between them in the dashboard
- **Workspace manager** (`workspace_manager.py`): new module handling workspace lifecycle — create, clone (background thread with GH_TOKEN auth), update, delete, and repo structure detection
- **Monorepo detection**: auto-detects monorepo setups by scanning for `pnpm-workspace.yaml`, `lerna.json`, `turbo.json`, `nx.json`, and `package.json` workspaces field; lists sub-packages from `packages/`, `apps/`, `services/`, `libs/`, `modules/` directories
- **Per-workspace env var management**: set environment variables per workspace and per env file path (supports monorepo sub-paths like `apps/web/.env`); variables are stored in DB and written to disk
- **Dashboard: workspace switcher** (top-left dropdown) with "All Workspaces" aggregate view, per-workspace filtering for agents/issues/PRs/metrics, and status badges (active/cloning/error)
- **Dashboard: add workspace modal** — enter a GitHub repo URL, optional name, and base branch; clone starts automatically in the background
- **Dashboard: workspace settings panel** (gear icon) — edit name/URL/branch, view detected repo structure (monorepo packages, discovered `.env` files), manage env vars with key-value editor, delete workspace with confirmation
- **Dashboard: .env file upload** — upload a local `.env` file from your machine; parsed client-side and merged into the env editor for review before saving
- **Database: `workspaces` table** — stores workspace metadata (id, name, github_repo, repo_url, local_path, base_branch, status, is_monorepo, structure_json)
- **Database: `workspace_env` table** — stores env vars per workspace with composite unique constraint on (workspace_id, env_key, env_file)
- **Database: `workspace_id` column** added to `issues`, `agents`, and `pr_reviews` tables for per-workspace tracking
- **Database: issues table migration** — seamless migration from old schema (`issue_number` as PK) to new schema (`id` autoincrement PK + composite `UNIQUE(issue_number, workspace_id)`)
- **Backward compatibility**: on first startup, auto-creates a "default" workspace from existing `.env` config (`GITHUB_REPO`, `TARGET_REPO_PATH`, `BASE_BRANCH`) and backfills all existing issues/agents/pr_reviews with the default workspace_id
- `WORKSPACES_DIR` config setting (default: `/root/workspaces`) for workspace clone locations
- Dashboard API: `POST/GET/PUT/DELETE /api/workspaces`, `GET /api/workspaces/{id}/structure`, `PUT/GET /api/workspaces/{id}/env`, `GET /api/workspaces/{id}/env-files`, `POST /api/workspaces/{id}/env-load`
- All existing API endpoints (`/api/agents`, `/api/issues`, `/api/prs`, `/api/metrics`) now accept optional `?workspace_id=` query parameter for filtering

### Changed
- **All core modules parameterized for multi-workspace**: `worktree.py`, `prompts.py`, `issue_poller.py`, `agent_pool.py`, `pr_monitor.py`, and `main.py` now accept workspace config instead of relying on global constants
- Main orchestration loop iterates over all active workspaces per poll cycle
- `config.py`: `GITHUB_REPO` and `TARGET_REPO_PATH` validation removed from `validate_environment()` — these are now optional in multi-workspace mode (workspaces can be added via dashboard instead)
- Worktree directory is now per-workspace: `<workspace_local_path>-worktrees/`
- Agent processes receive workspace-specific env vars in addition to global ones

### Fixed
- **FastAPI error responses**: replaced Flask-style tuple returns (`{"error": ...}, 400`) with proper `JSONResponse(content={...}, status_code=...)` across all dashboard error paths
- **SQLite FK validation failure**: removed `PRAGMA foreign_keys=ON` and broken `FOREIGN KEY (issue_number) REFERENCES issues(issue_number)` from agents table — `issue_number` is no longer unique in the new composite schema
- **`cleanup_worktree` missing `repo_path`**: all 11 call sites in `agent_pool.py`, `main.py`, and `worktree.py` now pass the correct workspace `repo_path` so worktree removal runs against the right git repo
- **`_has_unpushed_commits` using global `BASE_BRANCH`**: now accepts a `base_branch` parameter and uses the workspace's configured branch
- **`upsert_issue` NULL workspace_id dedup failure**: SQLite treats NULLs as distinct in UNIQUE constraints, so `ON CONFLICT(issue_number, workspace_id)` wouldn't fire for NULL workspace_id — fixed with explicit SELECT+UPDATE path for the NULL case
- **`save_workspace_env_bulk` not deleting removed keys**: old keys persisted when a user saved a new set via the dashboard — now deletes existing keys for the (workspace_id, env_file) pair before inserting
- **Git clone authentication**: `GH_TOKEN` as env var doesn't help `git clone` over HTTPS — fixed by embedding token in clone URL, then resetting remote URL and configuring credential helper post-clone

---

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

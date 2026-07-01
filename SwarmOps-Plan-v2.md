# SwarmOps — Plan v2: Subscription + BYO Anthropic Key + GitHub App

*Companion to `SwarmOps-Product-Strategy.md` (v1), which stays as-is. v2 refines the cost model and integration mechanics based on two decisions you've made: (1) charge a flat software subscription and **never** resell/meter Anthropic usage — every customer brings their own Anthropic API key; (2) ship a first-class **GitHub App** that handles repo access, commits, PRs, issues, and an **@bot-mention trigger**. Grounded in Anthropic's current docs, June 2026.*

> **What this supersedes in v1:** the §2 "two-rail" cost model (drop Rail B / managed metering entirely), the §5 pricing (now pure subscription), and the integration mechanics in §4. Everything else in v1 — the ICP call, the no-touch GTM, open-core, the self-serve stack, the roadmap shape — still stands.

---

## 0. The model in one line

**You sell a flat monthly subscription for the orchestration software. Each customer connects their own Anthropic Console API key and their own GitHub via your GitHub App. Anthropic bills them directly for tokens; GitHub access is scoped per-install. You touch neither their AI spend nor their code permissions beyond what they grant.**

This is simpler, cheaper, and lower-risk than v1's managed tier — and it's the only ToS-clean way to do it.

---

## 1. The Anthropic access model — what's actually possible (from the docs)

### Kill the wrong mental model first
There is **no "Sign in with Anthropic" / third-party OAuth** to obtain API access on a user's behalf. This is the single most important fact for this plan:

- OAuth subscription tokens (the `sk-ant-oat01-…` you get from `claude setup-token`) were **banned for third-party apps in Feb 2026 and are now rejected by the API.** Your current architecture runs on exactly this token type — it must change.
- Anthropic's docs are explicit: *"Developers building products or services that interact with Claude's capabilities… should use API key authentication through Claude Console."* Apps are **not** permitted to route requests through Free/Pro/Max subscription credentials on behalf of users.
- There is no consumer-style OAuth "grant this app access to my Claude account." Unlike GitHub or Google, Anthropic does not offer that for API usage.

### How "other apps" actually do it (the real pattern)
The user **creates a Console API key in their own Anthropic account and pastes it into your app.** That's the entire flow. It's BYO-key, productized as a clean onboarding step.

### Recommended "connect Anthropic" onboarding (the closest thing to click-to-accept)
1. In onboarding, deep-link the user to the [Claude Console](https://platform.claude.com/) → have them create (or select) a **Workspace** named "SwarmOps" and **set a monthly spend limit** on it. Workspaces exist precisely to *"segment your API keys and control spend by use case."* This protects them (runaway agent can't blow their whole budget) and you (no angry "why did this cost $400" emails).
2. They generate an API key in that workspace and paste `sk-ant-api03-…` into SwarmOps.
3. You **validate immediately** with a cheap call (e.g. `GET /v1/models` or a 1-token message) and show "✓ Connected." Store it **encrypted** (KMS / Fernet), never log it, and offer rotate/revoke.

### The required code change (small but essential)
Today agents spawn `claude -p` with `CLAUDE_CODE_OAUTH_TOKEN`. Swap that env var for the customer's `ANTHROPIC_API_KEY`. The Claude Code CLI accepts a Console API key and bills the API account — so your orchestrator (`agent_pool.py`, `planner.py`, `rate_limit_watcher.py`) stays structurally identical; you're changing *which credential* is injected per run, and injecting the *right customer's* key per job. *(Auth behavior has changed fast this year — verify the exact current Claude Code API-key flag/env against the live Claude Code docs when you build it; if the CLI path ever gets restricted, the fallback is to drive runs through the Claude Agent SDK / Messages API, which is unambiguously API-key native.)*

### Honest caveats to put in your onboarding copy
- **They need a Console account with pay-as-you-go billing**, not just a Pro/Max subscription. Some indie users only have a subscription — document "add a small Console credit" clearly; this is your biggest activation hurdle, so write the doc well and detect/redirect subscription-only users.
- **Their rate limits and spend tier are theirs.** A fresh Console org starts at Tier 1 and auto-tiers-up with spend. Surface rate-limit (429) errors gracefully and tell users how to raise limits.
- **You cannot see their token spend** (that needs *their* admin key). Don't promise a "$ spent" dashboard you can't power. You *can* show your own orchestration metrics — runs, PRs shipped, turns — just not their Anthropic bill. Encourage the workspace spend cap instead.
- **Why this is the win:** billing separation = ToS-clean (Commercial Terms, pay-per-use, no automation restrictions), **zero COGS, zero metering to build.** The June 15 2026 "Agent SDK credit" subscription change is now irrelevant to you — you're on API billing, not subscription.

---

## 2. Pricing under pure subscription (revises v1 §5)

Because you no longer mark up tokens, **every tier is a flat software subscription** and the customer's AI spend goes straight to Anthropic at cost. This *simplifies* the pricing page and strengthens the pitch.

| Tier | Price (flat) | Limits (the paywall levers) | Target |
|---|---|---|---|
| **Hobby** | $0 | 1 repo, 1 concurrent agent, ~30 runs/mo, community support. BYO Anthropic key + GitHub App | Wedge / funnel |
| **Pro** | $39–49/mo | 3 repos, 3 concurrent agents, unlimited Planner, email/Slack notifications | Indie / solo founders |
| **Team** | $299–499/mo | 10+ concurrent agents, unlimited repos, seats + roles, Slack/Linear, priority support | Startup eng teams — revenue core |

- **No managed/metered tier at all** (v1's Rail B is deleted, not deferred-with-effort — you simply don't build it). Less code, less risk.
- **Margin ~90%+ on every tier** — your only COGS is infra.
- **Positioning vs Devin's ACU metering:** *"Flat monthly price. Your AI usage bills straight to your Anthropic account at cost — no middleman markup, no surprise compute units. You set the spend cap."* That's a genuinely strong line for cost-conscious buyers.

---

## 3. The GitHub App (replaces the single PAT + polling)

A GitHub App is the right primitive for everything you described — repo access, commits, PRs, issues, and the @mention trigger — and it doubles as a **distribution channel** (GitHub Marketplace).

### Why an App (not a PAT, not an OAuth App)
Per-installation **scoped tokens**, **granular least-privilege permissions**, its **own bot identity**, **webhooks** (event-driven, no polling), higher rate limits, and a Marketplace listing. The customer installs once and picks exactly which repos to expose.

### Permissions to request (least privilege)
- **Contents:** Read & write (branches, commits)
- **Pull requests:** Read & write (open PRs, comment, push fixes)
- **Issues:** Read & write (read the plan, comment, create issues from the Planner)
- **Metadata:** Read-only (required baseline)
- **Checks / Commit statuses:** Read (see CI results to drive the review-fix loop)
- *(Avoid Actions/Workflows scope unless you truly need it — extra scopes slow Marketplace verification and scare buyers.)*

**Webhook events to subscribe:** `issues`, `issue_comment`, `pull_request`, `pull_request_review`, `pull_request_review_comment`, `check_suite` / `check_run`, `status`, plus `installation` and `installation_repositories`.

### Install + auth flow
1. User clicks **Install SwarmOps** → selects all or specific repos → grants permissions.
2. GitHub sends an `installation` webhook with an `installation_id`. Store the mapping `{ your_org → installation_id → repos }`.
3. To act on a repo, mint a **short-lived (1-hour) installation access token** by signing a JWT with your **App ID + private key**, then exchanging it. Cache tokens, refresh on expiry.

### The @bot-mention trigger (exactly what you want)
1. A repo collaborator comments **`@swarmops-bot start`** on an issue or PR.
2. GitHub fires an `issue_comment.created` webhook to your `/api/github/webhook` endpoint.
3. **Verify the commenter has write/admin permission on that repo** — this is the critical security gate. Without it, anyone could comment and spend the customer's Anthropic key / run agents on their code. Check via the installation token (`GET /repos/{owner}/{repo}/collaborators/{user}/permission`).
4. Parse the command (`start`, `stop`, `plan`, `retry`) and **enqueue a job** for that installation + repo. The bot can reply with a 👍 reaction or a "on it 🛠️" comment for instant feedback.

This mirrors your existing `TRIGGER_MENTION` logic — you're moving it from a polling-and-scan model to an event-driven one.

### Bot identity & commit attribution
The app acts as **`swarmops-bot[bot]`**. Commits made via the API with the installation token are attributed to the bot and show as **Verified** in GitHub — which cleanly **replaces the `GIT_AUTHOR_NAME/EMAIL` hack** currently used to dodge deploy-platform rejections. Agents push branches and open PRs as the bot; the human reviews and merges. Clear, auditable separation between machine work and human approval.

### Webhooks replace polling (big scalability win)
Deprecate the `issue_poller` and `pr_monitor` poll loops in favor of webhook handlers. Keep a **low-frequency reconcile poll** (e.g., every 30–60 min) only as a safety net for missed webhook deliveries. This is what lets you scale to thousands of repos without hammering the GitHub API every few minutes per repo.

### Security specifics (don't skip)
- Verify every webhook's **HMAC signature** (`X-Hub-Signature-256`) against your webhook secret.
- Handle **`installation.deleted`** and **`installation_repositories.removed`** to revoke access and stop jobs immediately.
- **Idempotency** on redelivered webhooks (dedupe by delivery ID).
- **Per-installation rate limiting** and abuse caps (a mention storm shouldn't be able to fan out unbounded paid runs).

---

## 4. How this rewires the codebase (delta vs. what you have)

| Concern | Today | v2 |
|---|---|---|
| GitHub auth | Single `GH_TOKEN` PAT | **GitHub App** + per-install 1h tokens — new `github_app.py` (JWT mint, token cache, webhook HMAC verify) |
| Triggering | `issue_poller` polls + scans comments for mention | **Webhook receiver** `/api/github/webhook` on `issue_comment` / `pull_request`; @mention parse **+ write-access permission check** |
| PR review loop | `pr_monitor` polls PRs for comments/CI | `pull_request_review` / `check_suite` **webhooks**; reconcile poll as fallback |
| Claude auth | Shared `CLAUDE_CODE_OAUTH_TOKEN` (banned for 3rd-party!) | **Per-org `ANTHROPIC_API_KEY`** (customer's Console key), encrypted, injected per run in `agent_pool.py` |
| Commit identity | `GIT_AUTHOR_NAME/EMAIL` env hack | App **bot identity** via installation token (Verified commits) |
| Secrets storage | Plaintext env vars in SQLite | **Encrypted** column / KMS for: customer API keys, App private key, webhook secret |
| Data model | No tenant scoping | Add `github_installations`; scope all tables by org/tenant (v1 Phase 1) |

---

## 5. Roadmap delta (vs. v1 §4)

**Added**
- **GitHub App build** — register app, JWT/token plumbing, webhook receiver, @mention + permission gate, `installation` lifecycle handling, Marketplace listing. **≈ 2–3 focused weeks** (the webhook security + permission checks are the careful part, not the happy path).
- **Anthropic key connect** — deep-link UX, paste → validate → encrypt → inject; swap the agent credential. **≈ 0.5–1 week.**

**Removed (time saved)**
- The **entire managed-metering system** from v1 (usage records, ACU-style billing, markup logic, spend reconciliation). You don't build any of it.

**Net:** v2 is **less total build than v1**, because you delete metering and lean on a GitHub App you wanted anyway. The Phase-1 multi-tenant foundation (GitHub login, Postgres, tenant scoping, MoR subscription billing, encrypted secrets) is unchanged and is where most of the work still is.

---

## 6. Risks & caveats specific to v2

- **Activation friction (the main one):** BYO Anthropic key requires a Console account with billing. Some indie users have only a subscription. Mitigate with excellent onboarding copy, a "why + how to add credit" doc, and detection that redirects subscription-only users. This is the #1 thing that will silently kill conversion — invest in it.
- **You're blind to their token spend** — set expectations explicitly; push the Console **workspace spend cap** during onboarding.
- **GitHub Marketplace review** — publishing and certain permission scopes may require GitHub verification; budget calendar time. The @mention-triggered compute makes the **write-access check non-negotiable** (it guards the customer's paid key).
- **You now hold crown jewels** — your App private key + every customer's API key. KMS, encryption at rest, rotation, audit logging, and a tight blast radius are table stakes the day you go multi-tenant.
- **Platform dependency** stays (v1 risk) — abstract the agent runner so a future non-Claude backend is *possible*, while staying Claude-native as the wedge.

---

## 7. End-to-end onboarding (no-touch, ties to v1 §8)

1. **Land** → "Connect GitHub" (GitHub OAuth login).
2. **Install the SwarmOps GitHub App** → pick repos.
3. **Connect Anthropic** → deep link to Console (create workspace + spend cap + key) → paste → validate ✓.
4. **Subscribe** (Merchant-of-Record checkout) — or start on Free.
5. **Comment `@swarmops-bot start`** on an issue → first PR lands. **Activation.**

All self-serve, all async, zero calls — consistent with v1's no-touch motion.

---

### Sources
- [Anthropic — API overview & authentication (Console API keys, workspaces for spend control)](https://platform.claude.com/docs/en/api/overview)
- [Anthropic — Admin API (org-only; not a third-party key-provisioning mechanism)](https://platform.claude.com/docs/en/manage-claude/admin-api)
- [Anthropic bans subscription/OAuth auth for third-party apps (Feb 2026); API keys required](https://autonomee.ai/blog/claude-code-terms-of-service-explained/) · [OAuth tokens disabled for third-party apps](https://alternativeto.net/news/2026/2/anthropic-officially-bans-using-subscription-authentication-for-third-party-claude-use)
- [GitHub Docs — Authenticating as a GitHub App installation (installation access tokens)](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation)

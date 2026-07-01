# SwarmOps → Product: Founder-Mode Strategy

*Prepared from a full read of the codebase (orchestrator ~6,000 LOC Python, dashboard ~4,000 LOC React) and current-market research, June 2026. Estimates assume you build solo with Claude Code.*

---

## TL;DR — the six decisions

1. **You already have the hard, rare part.** A working autonomous swarm that turns GitHub issues into merged PRs *and closes the CI-review loop* is genuinely differentiated. Most competitors open a PR and stop. Don't rebuild it — wrap it.
2. **The cost/licensing model is the whole ballgame, and it's time-sensitive.** Your current single shared `CLAUDE_CODE_OAUTH_TOKEN` (a Max plan) **cannot legally be resold or shared across customers.** Anthropic explicitly bans routing requests through subscription credentials on behalf of others. Build a **two-rail model**: self-hosted BYO-credentials (their keys, their use) + managed cloud on **API keys under Commercial Terms** with metering. See §2.
3. **Heads-up: June 15, 2026** (6 days out) Anthropic moves `claude -p` / Agent SDK subscription usage to a separate monthly "Agent SDK credit." This changes the economics of the exact mechanism your product runs on. Re-test throughput the day it lands.
4. **Who to sell to:** land with **indie/solo devs** (huge top-of-funnel, self-serve, near-zero COGS on BYO-key), monetize on **small startup eng teams, 5–50 devs** (that's where revenue concentrates). Skip enterprise until you have a team. See §3.
5. **Time to a sellable, scalable v1:** ~**3–4 focused months** with Claude Code for Phases 1–2 — and a **self-serve free tier can take its first paying customer in week 2–3**, with zero sales calls (§4, Phase 0).
6. **Distribution moat = open-core.** The repo is already self-hostable. Open-source the orchestrator, sell the hosted multi-tenant cloud + team features. This is the Sentry/GitLab/PostHog playbook and it's your cheapest growth channel (§6, §7).
7. **No-touch by design.** You don't want to sell on calls — good, this product shouldn't need them. The entire motion is product-led and async: sign up with GitHub, self-onboard to a first merged PR, pay by card via a Merchant of Record, get support over email/Discord. The trade is that build energy moves from *selling* into *onboarding UX + content* — which suits you (§8).

---

## 1. What you've actually built (honest asset assessment)

### The assets (valuable and hard to copy)

- **A real autonomous loop, not a demo.** `issue_poller` → `agent_pool` (spawns `claude -p` in isolated git worktrees) → `pr_monitor` (watches review comments) → dispatches fix agents → loops until 0 comments or retry cap → escalates to `needs-human`. The **review-fix loop** is the differentiator. Devin, Copilot agent, Sweep mostly open a PR and stop; you iterate against bugbot/CI feedback automatically.
- **Parallel swarm semantics.** Concurrency cap, turn limits, hard timeouts, retry limits, rate-limit watcher with resume, crash recovery, graceful shutdown. This is the unglamorous reliability scaffolding that takes months to get right, and you have it.
- **The AI Planner.** Plain-language description → codebase-aware, file-by-file implementation plan → GitHub issue → agent build. This is your **best self-serve hook and your best marketing demo** — it's visual, it's "magic," and it lowers the skill floor.
- **Multi-workspace + env management + skills support + a planning API** with static API keys for external automation. You're already past "script" into "platform."
- **It's self-hostable.** `run.sh` does systemd install, UI build, skill install. That's a distribution asset (open-core, §6).

### The gaps (what "a product people pay for" requires)

Today the system is **single-tenant by construction.** Specifically:

| Gap | Current state | Why it blocks a paid product |
|---|---|---|
| **Identity** | One `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`, 30-day cookie | No way for many customers to sign up, isolate, or pay |
| **Credentials** | One `CLAUDE_CODE_OAUTH_TOKEN` + one `GH_TOKEN`, injected into every agent | Can't legally or safely serve multiple customers from one set of keys |
| **Data model** | SQLite, no `tenant_id` on any table | No row-level isolation between customers |
| **Execution** | Agents run as local subprocesses on one host, sharing the box | Running untrusted customer code + secrets on a shared host is a security non-starter at scale |
| **GitHub access** | Single fine-grained PAT | Doesn't scale to many orgs; "paste a PAT" is friction + a trust killer |
| **Billing** | None | No revenue |
| **Secrets** | Env vars stored plaintext in SQLite | Unacceptable for a multi-tenant SaaS |
| **Trust surface** | No ToS/privacy/DPA, no audit log, no status page | Teams won't buy without these |

None of this is a criticism — it's exactly the right shape for a tool you built for yourself. The work ahead is **productization, not reinvention.**

---

## 2. The decision that determines everything: the Claude cost/licensing model

This is where most people building on Claude Code quietly break the rules and then get cut off. Get it right deliberately.

### The ToS reality (researched, June 2026)

- OAuth tokens (what `claude setup-token` gives you, what your `.env` holds) are **"intended exclusively for ordinary use of Claude Code"** by the subscriber.
- Anthropic **"does not permit third-party developers to offer Claude.ai login or to route requests through Free, Pro, or Max plan credentials on behalf of their users,"** and reserves the right to enforce **without prior notice.**
- For **commercial/automated** use, the sanctioned path is **API keys under the Commercial Terms — "no automation restrictions, no ambiguity."**
- **June 15, 2026:** `claude -p` / Agent SDK usage on subscription plans starts drawing from a **separate monthly Agent SDK credit.** Your product *is* `claude -p`. Re-benchmark throughput-per-dollar the day this lands.

**Translation:** the moment you point your existing single-token architecture at paying customers, you are reselling your Max plan — a ToS violation that can be killed overnight. Don't.

### Recommendation: a two-rail model

**Rail A — Self-Hosted / BYO-credentials (your wedge, ~$0 COGS).**
The customer runs SwarmOps (open-core) or your one-click deploy, and connects **their own** Claude credentials and **their own** GitHub. They're using their own subscription for their own work — "ordinary use." You sell the **orchestration software / a license / a thin hosted control-plane**, not Claude access. Gross margin is software-grade (85–95%). This is also the most honest sales pitch to a developer: *"your code and your keys never leave your infra."*

**Rail B — Managed Cloud (your revenue engine, you carry COGS).**
You host everything. You run agents on **Anthropic API keys under Commercial Terms**, **meter token/compute usage per run**, and **mark it up** (industry norm 30–60%; Devin's whole model is metered "ACUs" at ~$2–2.25 each ≈ 15 min of work). Customers who don't want to manage keys or infra pay a premium for convenience. This is ToS-clean because it's API + Commercial Terms, not subscription resale.

**Never do:** one shared Max token across customers. It's the one move that's both illegal-per-ToS and economically suicidal (rate limits collapse, one ban kills everyone).

> Founder note: Rail A gets you to market and revenue fast with no cost risk. Rail B is where you eventually make real margin and serve teams who value "it just works." Start A, add B once you have demand and the metering plumbing.

---

## 3. Who to sell to — my recommendation (you asked for my view)

The honest scoring is **volume × ACV × conversion-ease × retention:**

| Segment | Volume | ACV | Self-serve? | Retention | Verdict |
|---|---|---|---|---|---|
| Indie / solo devs | Huge | Low ($0–50/mo) | Yes | Churny | **Wedge / funnel** |
| Startup eng teams (5–50) | Medium | Mid ($200–2k/mo) | Mostly | Sticky (in workflow) | **Revenue core** |
| Mid-market / enterprise | Low | High ($20k+/yr) | No | Sticky | **Later, not solo** |
| Agencies / resellers | Low | Mid | No | Medium | **Opportunistic** |

**My call: "Land with indies, monetize on teams."** Same product, one expansion motion.

- **Indie/solo devs are the wedge,** not the business. Every developer with a Claude subscription and a messy backlog is a candidate, conversion is self-serve, and on BYO-key your cost to serve them is ~zero — so a generous free tier is pure growth fuel and word-of-mouth.
- **Small startup eng teams are where money concentrates.** They have a real backlog-velocity problem, a budget, and once SwarmOps is wired into their issue tracker it's *in the workflow* and hard to rip out. 5–20× the ACV of an indie, far stickier.
- **Skip enterprise** as a solo founder. SSO/SOC2/procurement/security review will eat 6 months and you'll lose the plot. Revisit once you have a team and 20+ paying teams as references.

Design pricing so a solo user **naturally pulls in their team** (shared workspaces, "invite a teammate to review the PRs"). That's your expansion loop.

---

## 4. Product roadmap: what to build, in what order, how long

Estimates are in **focused solo-weeks building with Claude Code.** Claude Code roughly **1.5–2.5×'s** your throughput on boilerplate (auth, CRUD, Stripe, migrations, React screens). It helps **less** on the security-critical, judgment-heavy parts (multi-tenant execution isolation, GitHub App, secrets) — those take real care regardless of tooling. Wall-clock will be longer than the focused-week numbers because you're *also selling, supporting, and marketing* solo — budget ~1.5× calendar time.

### Phase 0 — Self-serve paid beta (week 1–3). *No calls. Build almost nothing.*
Validate willingness to pay **without ever talking to anyone.** Stand up the smallest possible no-touch loop on top of today's single-tenant code:

1. A **landing page** with the demo video, transparent pricing, and one button: "Connect your GitHub."
2. A **one-command provisioner** that spins up a dedicated SwarmOps instance per signup, running today's code with *their* keys (per-customer isolation "for free" via infra — same trick as before, just automated instead of hand-held).
3. A **Merchant-of-Record payment link** (Lemon Squeezy / Polar / Paddle) for a flat $99–299/mo. Card on file, they self-cancel, you never invoice.
4. A **Discord invite + support email** in the welcome screen. That's your entire "onboarding."

Feedback comes from **watching, not asking**: drop PostHog on the page and the dashboard and read where people stall. If you want richer signal, send one async email ("hit reply if anything broke") — optional, never a meeting.

**Deliverable: first real revenue + funnel data on where signup→first-PR breaks — with zero sales calls.**
*Effort: landing page + provisioner script + MoR link + PostHog. ~1 week of build.*

### Phase 1 — BYO-key multi-tenant MVP (≈ 4–7 weeks). *Rail A, sellable.*

| Workstream | What | Est. |
|---|---|---|
| **Auth + org model** | "Sign in with GitHub" (perfect fit), `organizations` / `users` / `memberships`, replace admin-password auth | 1.5–2.5 wk |
| **Tenant isolation** | Add `tenant_id` everywhere; scope every query; migrate **SQLite → Postgres** | (incl. above) |
| **Encrypted credentials** | Per-org Claude token + GitHub connection, encrypted at rest (Fernet/libsodium + KMS), injected per run | 0.5–1 wk |
| **Billing** | Merchant-of-Record subscriptions (Lemon Squeezy/Polar/Paddle — they own tax + invoices) + plan limits + self-serve customer portal + webhooks; gate `MAX_CONCURRENT_AGENTS`, repos, runs by plan | 1 wk |
| **Onboarding + polish** | Connect-GitHub → pick repos → first run wizard; empty states; docs | 1 wk |

*Defer the hardest part:* keep execution as **one container per customer** (managed isolation by infra) so you don't block launch on a sandbox runtime. This is enough to **charge teams.**

### Phase 2 — Secure execution + GitHub App + queue (≈ 4–8 weeks). *Scale-ready.*

| Workstream | What | Est. |
|---|---|---|
| **GitHub App** | Replace PAT with a GitHub App: per-install tokens, granular permissions, webhooks (kills "paste a PAT" friction, unlocks GitHub Marketplace distribution) | 1.5–2 wk |
| **Ephemeral sandboxed runner** | Per-run containers (Docker → Firecracker/gVisor), resource + **egress** limits, guaranteed teardown/secret-scrub. *The genuinely hard, security-sensitive piece.* | 2–4 wk |
| **Job queue + workers** | Redis/RQ/Celery or SQS instead of in-process threads; autoscale workers; survive restarts | 1–1.5 wk |
| **Secrets + observability** | KMS-backed secrets, Sentry, per-tenant rate limiting, audit log | 1 wk |

### Phase 3 — Team features + managed tier + trust (≈ 6–10 weeks, ongoing).
Seats/roles/RBAC; Slack + Linear/Jira integrations; email/Slack notifications ("3 PRs ready for review"); **Rail B metered managed tier** + usage dashboards; ToS/privacy/DPA + security page; SSO when you start chasing bigger teams.

**Bottom line:** Phase 0 = revenue in ~2 weeks. Phases 1–2 = a sellable, scalable product in **~3–4 focused months.** Phase 3 is continuous and demand-driven.

---

## 5. Monetization & pricing (based on your current logic)

Your code already exposes the **natural value metrics**: concurrent agents (`MAX_CONCURRENT_AGENTS`), number of workspaces/repos, and agent-runs (issues resolved / PRs shipped). Price on those.

| Tier | Price | Limits (the paywall levers) | Target |
|---|---|---|---|
| **Hobby** | $0 (BYO-key) | 1 repo, 1 concurrent agent, ~30 runs/mo, community support | Wedge / funnel |
| **Pro** | $39–49/mo (BYO-key) | 3 repos, 3 concurrent agents (your current default!), unlimited Planner, email notifications | Indie / solo founders |
| **Team** | $299–499/mo (BYO-key) | 10+ concurrent agents, unlimited repos, seats, roles, Slack/Linear, PR notifications, priority support | **Startup eng teams — your revenue core** |
| **Managed** | Team price **+ metered usage** (Rail B) | We run the keys + infra; usage billed at API-cost × ~1.4–1.6; SSO; SLA | Teams who won't manage keys; later enterprise |

Pricing logic notes:
- **Anchor against the market:** Devin $20 → $500 + ACUs; Copilot agent $39 Pro+; Cursor $60 Pro+. A $39 Pro / $299 Team line sits credibly in that band while your BYO-key COGS is ~$0, so your **gross margin on BYO-key tiers is 85–95%.**
- **Concurrency is your cleanest paywall** — it's already a config variable, it maps directly to value (more parallel agents = more backlog cleared per night), and it's painless to meter.
- **Outcome framing converts better than seat framing** for this product: "PRs shipped while you sleep" > "per developer." Consider a usage-credit option on Rail B that mirrors Devin's ACU model so buyers can compare apples-to-apples.

---

## 6. How to scale — technical and business

### Technical (the architecture you grow into)
Postgres (multi-tenant, row-level scoping) → job queue + autoscaling stateless workers → **ephemeral per-run sandboxes** (the core scaling unit; one customer's code/secrets must never touch another's) → GitHub App for per-install auth + webhooks (replace polling, which won't scale to thousands of repos) → KMS for secrets → Sentry/metrics/audit → multi-region later. The orchestrator logic you have stays largely intact; you're wrapping it in isolation + a control plane.

### Business (your real moat is distribution)
**Open-core.** Your repo is already self-hostable — lean into it. Open-source the orchestrator under a permissive-but-protected license (Apache/MIT core, or BSL if you want to prevent a hyperscaler reselling it). Monetize the **hosted multi-tenant cloud + team features + support.** Why this wins for you specifically:
- GitHub stars are free, compounding distribution for a dev tool.
- Self-hosters become your funnel: they hit the ops pain, then upgrade to managed.
- It's the proven path (Sentry, GitLab, PostHog, n8n, **OpenHands** — your closest competitor is open-source and just raised $18.8M doing exactly this).

The strategic risk: **OpenHands is close** (open-source, self-hosted, issue→PR, GitHub/Slack, Kubernetes, well-funded). Your defensible wedge vs. them: **Claude-Code-native** (you ride Claude's coding quality and brand rather than a generic agent), the **autonomous review-fix loop**, the **AI Planner**, and **radical simplicity** ("label an issue, get a merged PR" with far less setup). Pick that wedge and hammer it.

---

## 7. Go-to-market & marketing

Every channel below is **async and call-free** by design — it's all writing, building, and posting, never meetings. That's deliberate: a no-touch product is *acquired* the same way it's sold. Pricing is public, signup is self-serve, and "talk to sales" never appears.

### Positioning (the one sentence)
**"SwarmOps clears your GitHub backlog while you sleep — a swarm of Claude Code agents that turn labeled issues into reviewed, merged PRs, and fix their own review comments."**

The wedge is **autonomy + the closed review loop**, against IDE-bound tools (Cursor/Copilot live in your editor; SwarmOps works the backlog unattended).

### Channels for a solo dev-tool founder (in priority order)
1. **Build in public.** You're already active on LinkedIn/X (you even have a LinkedIn comment-publisher workflow). Post the money shot weekly: *"Left 12 issues labeled `agent` Friday night. Woke up to 9 merged PRs. Here's the dashboard."* Demo > description for this product.
2. **Open-source launch.** "Show HN: SwarmOps — autonomous Claude Code agents that clear your GitHub backlog." HN + Product Hunt + r/programming + r/ClaudeAI + r/ExperiencedDevs + dev.to. The self-hostable repo *is* the launch asset.
3. **The Planner demo video.** Loom/short-form: plain-English feature → generated plan → issue → swarm → merged PR. This is inherently shareable and is your best top-of-funnel content.
4. **GitHub Marketplace** (once the GitHub App ships, Phase 2). Native distribution to exactly your buyer, at the moment of intent.
5. **SEO/comparison content.** "Automate your GitHub backlog," "Claude Code in CI/CD," "autonomous coding agents compared," and honest comparison pages: *vs Devin, vs Copilot coding agent, vs Cursor background agents, vs OpenHands, vs Sweep.* Buyers in this category search these exact queries.
6. **Ride the Claude Code wave.** Anthropic actively showcases ecosystem tools; being a visible, well-built Claude-Code-native product is a tailwind. Engage their dev community/Discord.
7. **Templates & skills as content.** You already support skills — ship a few great ones and write them up; each is a discovery surface.

### Competitive one-liners (for your battlecard)
- **vs Devin:** "Devin is one autonomous engineer you rent by the ACU. SwarmOps is a *swarm* on *your* Claude keys clearing the whole backlog in parallel — and it fixes its own review comments."
- **vs Copilot/Cursor agents:** "Those live in your editor and wait for you. SwarmOps works your issue tracker unattended and closes the PR review loop."
- **vs OpenHands:** "Claude-Code-native, simpler to run, with a built-in planner and an autonomous review-fix loop. Label an issue — that's the whole setup."

---

## 8. The no-touch self-serve stack (and where it plugs into your code)

The goal: a stranger finds you, signs up, reaches a merged PR, and pays — with you asleep. Here's the concrete stack and exactly where each piece attaches to what you've already built. The good news: your existing `sessions` table, cookie/middleware auth, and workspace flow are the right *shape* — you're swapping the credential check and adding a tenant + billing layer, not starting over.

| Need | Tool (recommended) | Where it plugs into your code | Effort |
|---|---|---|---|
| **Self-serve login** | GitHub OAuth | Replace the `ADMIN_USERNAME`/`ADMIN_PASSWORD` check in `dashboard.py` `/api/auth/login`. **Keep** the existing `sessions` table + cookie middleware — just mint the session after a GitHub OAuth callback instead of a password compare. Add `users` + `organizations` + `memberships` tables alongside `workspaces`. | 1.5–2.5 wk |
| **Payments, tax, invoices — all of it** | **Merchant of Record:** Lemon Squeezy, Polar, or Paddle | Net-new `/api/billing/webhook` route in `dashboard.py`. On `subscription.created/updated/canceled`, write a `plan` + `status` onto the org. MoR handles VAT/sales tax, receipts, dunning, chargebacks — the stuff you'd otherwise email people about. (Plain Stripe also works but then *you* own tax.) | ~1 wk |
| **Enforce plan limits** | Your own entitlement check | Gate at the spawn point: in `agent_pool.py` check the org's plan before launching (cap `MAX_CONCURRENT_AGENTS`), and in `workspace_manager.create_workspace` cap repo count. Count agent-runs per month for the free-tier ceiling. This *is* your paywall. | (incl. above) |
| **Onboarding to first PR** | In-app wizard + great empty states | Extend the existing `AddWorkspaceModal`/workspace flow into a guided "connect GitHub → pick a repo → label an issue → watch it ship" first-run. This is the highest-ROI build for a no-touch motion — every % of activation lift is pure revenue. | ~1 wk |
| **See where users stall (instead of asking on a call)** | **PostHog** (free tier) | Snippet in `frontend/src/main.jsx`; fire backend events from `dashboard.py` on key steps (signup, repo connected, first run, first merged PR, paywall hit). Funnels + session replay tell you what a call would have, asynchronously. | 1–2 days |
| **Docs that answer the questions you'd otherwise field** | Mintlify / Docusaurus (separate repo) | Standalone site. Link from the dashboard empty states and error toasts. | ongoing |
| **Async support + community** | Email + **Discord**; AI support bot later | Invite link + support email on the welcome screen. The community answers itself over time. | hours |
| **Let users ask for features without you interviewing them** | Public roadmap: Canny or GitHub Issues | Link in the dashboard footer. Voting replaces discovery calls. | hours |
| **Demo that does the selling** | Loom / a hosted live demo | The Planner→PR loop video, embedded on the landing page and pinned everywhere. | 1 day |

**The principle:** anywhere you'd normally *talk to a user*, substitute a built artifact — a wizard for onboarding, PostHog for discovery, docs for questions, a roadmap for feature requests, a MoR for billing ops. Each is a one-time build that scales to unlimited customers with zero of your time.

---

## 9. Unit economics (illustrative)

**Rail A (BYO-key), Pro $44/mo:** COGS ≈ infra only (~$1–3/customer/mo on a shared control plane). **Gross margin ~93%.** This tier exists to grow and to feed Team.

**Rail A Team $399/mo:** still ~90% margin. 50 Team customers ≈ **$240k ARR** at near-software margins. This is a very reachable solo-founder target in 12–18 months given the funnel.

**Rail B (managed), metered:** you pay Anthropic API per run, bill at ~1.4–1.6×. Margin 30–40% on the metered portion + the platform fee. Lower margin, higher ACV, serves the "just make it work" buyer — add it once Rail A demand proves the wedge.

The headline: **on BYO-key you can run an aggressive free tier and still have software-grade margins,** because you're selling orchestration, not tokens. That's your structural advantage over Devin-style metered competitors.

---

## 10. Risks & moats

**Risks**
- **Anthropic ToS / June 15 Agent-SDK-credit change** (§2) — the single biggest one. Mitigate by building Rail B on Commercial-Terms API keys and never sharing subscription tokens.
- **Platform dependency** — you're a layer on Claude Code. Mitigate by abstracting the agent runner so you *could* add other models, while staying Claude-native as the wedge.
- **OpenHands / well-funded open-source** — mitigate with the Claude-native + review-loop + simplicity wedge and speed.
- **Trust** — running agents against customer code with customer secrets. Mitigate with ephemeral sandboxes, "we never store your code," self-host option, and eventually SOC2.

**Moats (build deliberately)**
- The **autonomous review-fix loop** + reliability scaffolding (hard to replicate, you already have it).
- **Open-core distribution** + GitHub Marketplace presence.
- **Workflow lock-in** — once it's wired into a team's issue tracker and shipping PRs, switching cost is real.
- **Data flywheel** (later) — aggregate (opt-in, anonymized) signal on which plans/prompts produce merged PRs → better Planner → better outcomes → more merges.

---

## 11. Your next 14 days

1. **Re-benchmark on June 15** when the Agent SDK credit change lands — know your real throughput-per-dollar before you price.
2. **Stand up the no-touch Phase 0 loop:** landing page + the Planner demo video + a one-command per-signup provisioner + a Merchant-of-Record payment link + PostHog. No call, no invoice.
3. **Drive your first traffic async** — post the demo in indie-hacker and Claude communities, on LinkedIn/X, and let the page convert. Your only job is to ship the link, not to pitch.
4. **Decide the license** (Apache vs BSL) and prep the open-source launch — repo polish, README, the Planner demo video.
5. **Write the comparison pages** (vs Devin / Copilot / Cursor / OpenHands) — they're SEO + self-serve conversion assets you'll reuse everywhere.
6. **Start Phase 1** (GitHub login + Postgres + per-org encrypted keys + MoR billing) with Claude Code while Phase 0 runs and collects funnel data.

---

### Sources
- [Devin Plans and Pricing](https://devin.ai/pricing/) · [Devin 2026 pricing breakdown (ACU costs)](https://aitoolpick.org/blog/devin-pricing-2026/)
- [Copilot Coding Agent vs Codex vs Cursor Background Agents — 2026 workflow map](https://ralphable.com/blog/copilot-coding-agent-vs-codex-vs-cursor-background-agents-2026)
- [Anthropic — Claude Code legal & compliance](https://code.claude.com/docs/en/legal-and-compliance) · [Claude Code Terms of Service explained (OAuth vs API, reselling, June 15 2026 Agent SDK credit)](https://autonomee.ai/blog/claude-code-terms-of-service-explained/)
- [OpenHands — open platform for cloud coding agents](https://www.openhands.dev/) · [Open-source coding agents fixing your GitHub issues](https://www.openhands.dev/blog/open-source-coding-agents-in-your-github-fixing-your-issues)

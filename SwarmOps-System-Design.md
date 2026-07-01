# SwarmOps — System Design (v2 refactor)

*The architecture blueprint the code follows. Companion to `SwarmOps-Plan-v2.md`. Scope of the first build slice: **foundational abstractions + Anthropic BYO-key**, on **Postgres**, evolving multi-tenant on a branch. Everything here is written so later slices (GitHub App, billing, full multi-tenant auth) drop in without rework.*

---

## 1. Goals & constraints

**Functional (this slice)**
- Each tenant (organization) supplies its **own Anthropic Console API key**; agents for that org run on *that* key (`ANTHROPIC_API_KEY`), never a shared subscription token.
- Secrets are **encrypted at rest** with a per-tenant data key (envelope encryption); a DB dump leaks only ciphertext.
- The credential mechanism is **pluggable** — API key today; KMS/Vault/WIF later — without touching call sites.

**Non-functional**
- Postgres as system of record (concurrent, multi-tenant, real migrations).
- No business logic in the execution path knows *how* a secret is stored or *which* credential type is used — it asks an interface.
- Keep the orchestrator's proven control loop intact; we change *plumbing*, not the swarm logic.

**Constraints**
- Solo build with Claude Code; incremental, each step compiles.
- Branch `feat/v2-byok-foundations`; temporary breakage of higher layers is acceptable, but new code must be coherent and tested.

---

## 1a. Deployment modes (single-tenant stays first-class)

The OSS self-host / internal-team deployment must keep running exactly as it
does today, so `DEPLOYMENT_MODE` selects the wiring in the composition root:

| Mode | Default | Credentials | Storage | Postgres? |
|---|---|---|---|---|
| `single_tenant` | ✅ yes | `EnvCredentialProvider` — injects `CLAUDE_CODE_OAUTH_TOKEN` (unchanged) or `ANTHROPIC_API_KEY` from env | none | **no** |
| `multi_tenant` | — | `ApiKeyCredentialProvider` — per-org Console key | `FernetSecretStore` (encrypted) | yes |

In single-tenant mode `resolve_org_id()` returns a constant and never imports the
DB layer, so the self-host path needs no Postgres, no master key, and no schema
migration — it behaves byte-for-byte like the original. The same `CredentialProvider`
interface serves both, so the execution path is identical regardless of mode.

## 2. Layered architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Interface layer    dashboard.py (FastAPI)  ·  pollers        │
│                     CLI / webhooks (later)                    │
├─────────────────────────────────────────────────────────────┤
│  Service layer      AgentPool · Planner · PRMonitor           │  ← orchestration logic
│                     (depend on INTERFACES, not globals)       │
├─────────────────────────────────────────────────────────────┤
│  Domain interfaces  CredentialProvider · SecretStore          │  ← the seams
│                     repositories (Org/Credential/Workspace…)  │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure     SQLAlchemy engine/session · Alembic       │
│                     FernetSecretStore · (KMS/Vault TODO)       │
│                     Postgres                                   │
└─────────────────────────────────────────────────────────────┘
```

Dependencies point **downward only**. The service layer receives its collaborators by **dependency injection** from a single composition root (`orchestrator/container.py`), so nothing deep in the stack imports `config.CLAUDE_CODE_OAUTH_TOKEN` anymore.

### Design patterns in play (and why)
- **Repository** — one class per aggregate hides SQL/ORM behind intention-revealing methods. Swaps the 850-line `db.py` god-module for testable units.
- **Strategy** — `SecretStore` and `CredentialProvider` are interfaces with interchangeable implementations (Fernet now, KMS/WIF later). New backend = new class, zero call-site edits.
- **Dependency Injection / Composition Root** — `container.py` wires concrete implementations once; everything else takes them as constructor args. Makes unit testing trivial (inject fakes).
- **Strangler Fig** — the new Postgres/repository stack grows *alongside* legacy `db.py`; call sites migrate one module at a time behind an adapter, never a risky big-bang rewrite. Each migrated module deletes its slice of `db.py`.
- **Adapter** — during transition, legacy `db.py` functions become thin adapters delegating to repositories, so unmigrated callers keep working on Postgres.

---

## 3. Package structure (target)

```
orchestrator/
├── container.py            # composition root — builds & wires singletons
├── settings.py             # typed config (pydantic-settings) — replaces ad-hoc os.environ
├── infra/
│   ├── db.py               # SQLAlchemy engine + session factory (Postgres)
│   └── crypto.py           # envelope encryption primitives (Fernet + per-tenant DEK)
├── models/                 # SQLAlchemy ORM models (one file per aggregate)
│   ├── base.py             # DeclarativeBase, TimestampMixin, UUID pk helper
│   ├── organization.py     # organizations, users, memberships
│   ├── credential.py       # org_credentials (encrypted), tenant_keys
│   ├── workspace.py        # workspaces (+ org_id), workspace_env…
│   └── …                   # issues, agents, pr_reviews, planning… (ported incrementally)
├── repositories/
│   ├── base.py             # Repository[T] generic base
│   ├── organization_repo.py
│   ├── credential_repo.py
│   └── workspace_repo.py
├── secrets/
│   ├── base.py             # SecretStore (ABC)
│   ├── fernet_store.py     # FernetSecretStore (envelope encryption)
│   └── env_store.py        # EnvVarSecretStore (dev/bootstrap fallback)
├── credentials/
│   ├── base.py             # CredentialProvider (ABC) + AgentCredentials value object
│   └── api_key_provider.py # ApiKeyCredentialProvider → ANTHROPIC_API_KEY
├── alembic/                # migrations
└── (existing modules: agent_pool, planner, pr_monitor, … refactored to use the above)
```

---

## 4. Data model (Postgres)

New/changed tables for this slice. IDs are UUID (text) to stay merge-friendly and avoid cross-tenant enumeration.

```
organizations
  id (uuid pk) · name · slug (unique) · created_at · updated_at
  -- TODO(auth-slice): plan, stripe_customer_id, status

users                         -- minimal now; full auth is a later slice
  id (uuid pk) · github_id (unique, nullable) · email · name · created_at
  -- TODO(auth-slice): avatar_url, last_login_at

memberships
  id (uuid pk) · org_id (fk) · user_id (fk) · role (owner|admin|member)
  UNIQUE(org_id, user_id)

tenant_keys                   -- per-tenant data-encryption-key (DEK), wrapped by the master key
  org_id (uuid pk, fk) · wrapped_dek (bytea) · key_version (int) · created_at
  -- the master key (KEK) lives in env now; TODO(kms): move KEK to AWS KMS / Vault

org_credentials               -- the encrypted Anthropic key (and future provider creds)
  id (uuid pk) · org_id (fk) · provider (text: 'anthropic')
  ciphertext (bytea) · key_version (int)
  status (active|invalid|revoked) · last_validated_at · created_at · updated_at
  UNIQUE(org_id, provider)

workspaces                    -- existing + org scoping
  id · org_id (fk, NEW) · name · github_repo · repo_url · local_path
  base_branch · status · is_monorepo · structure_json · created_at · updated_at
```

Existing tables (`issues`, `agents`, `agent_events`, `pr_reviews`, `pr_conflict_fixes`, `planning_*`, `workspace_env*`, `sessions`) are ported to ORM models and gain `org_id` where they represent tenant data. Tenant scoping on those is wired as each module migrates (TODO markers per module).

**Migrations:** Alembic. One initial migration creates the full schema on Postgres. Schema changes from here are versioned migrations — no more `CREATE TABLE IF NOT EXISTS` drift.

---

## 5. The two seams (interfaces)

### SecretStore — *how* a secret is stored
```python
class SecretStore(ABC):
    @abstractmethod
    def put(self, org_id: str, name: str, plaintext: str) -> None: ...
    @abstractmethod
    def get(self, org_id: str, name: str) -> str | None: ...
    @abstractmethod
    def delete(self, org_id: str, name: str) -> None: ...
```
- `FernetSecretStore` — envelope encryption: a per-tenant **DEK** (in `tenant_keys`) encrypts the secret; the DEK is itself wrapped by a master **KEK**. Ciphertext lives in `org_credentials`. No plaintext ever hits disk or logs. *(TODO(kms): swap the KEK source from env to AWS KMS / Vault; the interface does not change.)*
- `EnvVarSecretStore` — reads from process env; dev/bootstrap only.

### CredentialProvider — *which* credential an agent run gets
```python
@dataclass(frozen=True)
class AgentCredentials:
    env: dict[str, str]          # injected into the agent subprocess

class CredentialProvider(ABC):
    @abstractmethod
    def for_org(self, org_id: str) -> AgentCredentials: ...
    @abstractmethod
    def validate(self, org_id: str) -> bool: ...   # cheap live check
```
- `ApiKeyCredentialProvider` — pulls the org's Anthropic key from the `SecretStore`, returns `env={"ANTHROPIC_API_KEY": key}`. `validate()` hits a cheap endpoint (e.g. `GET /v1/models`) and updates `org_credentials.status`/`last_validated_at`.
- *(TODO(wif): `WifCredentialProvider` mints short-lived OIDC tokens — no stored secret. Same interface.)*
- *(TODO(legacy): `OAuthTokenCredentialProvider` only if a self-host single-tenant mode is ever needed; not built now.)*

**Why two interfaces, not one:** storage and credential-semantics change independently. You might keep Fernet storage but switch from API-key to WIF; or keep API-key but move storage to KMS. Splitting the seams keeps each change isolated.

---

## 6. Execution path — before vs after

The injection sites today (all hardcode the shared, now-banned token):
- `agent_pool._spawn_agent` (~L536) and the resume path (~L1029)
- `planner.py` (~L198)
- `rate_limit_watcher.py` (~L25)

**Before**
```python
env = {**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": CLAUDE_CODE_OAUTH_TOKEN, "GH_TOKEN": GH_TOKEN}
```

**After** — the pool holds an injected `CredentialProvider`; the workspace resolves to an org:
```python
creds = self._credentials.for_org(org_id)          # AgentCredentials
env = {**os.environ, **creds.env, "GH_TOKEN": gh_token}
```
`org_id` comes from the workspace (`WorkspaceRepository.get(workspace_id).org_id`). `AgentPool`, `Planner`, and `RateLimitWatcher` each receive the `CredentialProvider` via the container — they no longer import `config` token globals. `rate_limit_watcher` probes per-org (TODO: it currently assumes one global account; under BYO-key, rate limits are per-org, so the watcher becomes per-org-aware — tracked as a TODO in that module).

---

## 7. Configuration

Replace scattered `os.environ.get` with one typed `settings.py` (pydantic-settings):
- `DATABASE_URL` (Postgres DSN)
- `SECRETS_MASTER_KEY` (the KEK; TODO(kms): source from KMS)
- `SECRET_BACKEND` = `fernet` | `env`
- `CREDENTIAL_PROVIDER` = `api_key`
- legacy `CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`, etc. retained but marked deprecated.

`container.py` reads `settings`, constructs the chosen `SecretStore` + `CredentialProvider`, the SQLAlchemy session factory, and the repositories, and hands them to the services. One place to see the whole wiring.

---

## 8. Trade-offs & what we'd revisit

| Decision | Why | Revisit when |
|---|---|---|
| SQLAlchemy 2.0 ORM + Alembic | Real migrations, relationships, testability; idiomatic for evolving multi-tenant schema | If raw-SQL perf becomes critical in a hot path (unlikely here) |
| Strangler-fig over big-bang DB rewrite | Keeps every commit coherent; lowers risk; matches "don't make messy code" | Once all modules are ported, delete `db.py` adapter |
| Envelope encryption with env-sourced KEK | Per-tenant blast radius now, no cloud dependency to start | Move KEK to KMS/Vault before serving real customers (TODO(kms)) |
| Two interfaces (SecretStore + CredentialProvider) | Storage and credential-type evolve independently | Stable — this is the long-term seam |
| Minimal `users`/`memberships` now | Org is needed as tenant anchor for credentials; full auth is a separate slice | GitHub-OAuth login slice |
| Per-org `rate_limit_watcher` deferred | Out of first-slice scope; single-account assumption tolerated on branch | Before multi-tenant load testing |

---

## 9. First-slice build order (each step compiles & is tested)

1. **Branch + deps** — `feat/v2-byok-foundations`; add `sqlalchemy`, `alembic`, `psycopg[binary]`, `cryptography`, `pydantic-settings`.
2. **`settings.py`** — typed config.
3. **`infra/db.py`** — engine + session factory.
4. **`models/`** — base + organization + credential + workspace (others ported incrementally).
5. **Alembic** — initial migration for the schema above.
6. **`infra/crypto.py` + `secrets/`** — Fernet envelope encryption + `SecretStore` impls.
7. **`credentials/`** — `CredentialProvider` + `ApiKeyCredentialProvider`.
8. **`repositories/`** — Organization, Credential, Workspace.
9. **`container.py`** — wire it all.
10. **Refactor execution path** — `agent_pool`, `planner` to inject per-org `ANTHROPIC_API_KEY` via the provider; `rate_limit_watcher` marked per-org TODO.
11. **Tests** — unit tests for crypto round-trip, FernetSecretStore, ApiKeyCredentialProvider (with a faked SecretStore), and a repository smoke test against a throwaway Postgres/SQLite-in-memory.

Deferred work is captured in-code as `# TODO(<slice>): …` so it's greppable: `TODO(auth-slice)`, `TODO(github-app)`, `TODO(billing)`, `TODO(kms)`, `TODO(wif)`, `TODO(port)`.

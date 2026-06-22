"""Tenant resolution helpers (transition shim).

The execution path needs an ``org_id`` to resolve per-tenant credentials, but
workspaces are not yet created through the org-scoped data layer. Until the auth
slice wires real organizations and the GitHub-App slice maps installations to
orgs, every run resolves to the bootstrap "default" org.

    TODO(auth-slice): map a workspace_id to its real owning org via
    WorkspaceRepository once workspaces are created with an org_id, then delete
    the default-org fallback.
"""

from __future__ import annotations

from orchestrator.settings import get_settings

# Constant tenant id used in single-tenant mode (no DB, no real orgs).
SINGLE_TENANT_ORG_ID = "single-tenant"


def resolve_org_id(workspace_id: str | None = None) -> str:
    """Return the org that owns this run.

    Single-tenant mode returns a constant without touching the database, so the
    OSS self-host path needs no Postgres. Multi-tenant mode resolves the owning
    org from the data layer.
    """
    settings = get_settings()
    if not settings.is_multi_tenant:
        return SINGLE_TENANT_ORG_ID

    # Multi-tenant: resolve from the data layer.
    # Imported lazily so single-tenant deployments never import the DB layer.
    from orchestrator.infra.db import session_scope
    from orchestrator.repositories.organization_repo import OrganizationRepository

    # TODO(auth-slice): if workspace_id maps to an org-scoped workspace, return
    # that workspace's org_id instead of the default bootstrap org.
    with session_scope() as s:
        return OrganizationRepository(s).get_or_create_default().id

"""SQLAlchemy ORM models (v2).

Importing this package registers every model on the shared ``Base.metadata`` so
Alembic autogenerate and ``create_all`` (in tests) see the full schema.

    TODO(port): the existing tables (issues, agents, agent_events, pr_reviews,
    pr_conflict_fixes, planning_*, workspace_env*, sessions) are ported to ORM
    models incrementally as each owning module migrates off legacy db.py. Add
    them here as they land.
"""

from orchestrator.models.base import Base
from orchestrator.models.credential import OrgCredential, TenantKey
from orchestrator.models.organization import Membership, Organization, User
from orchestrator.models.workspace import Workspace

__all__ = [
    "Base",
    "Organization",
    "User",
    "Membership",
    "TenantKey",
    "OrgCredential",
    "Workspace",
]

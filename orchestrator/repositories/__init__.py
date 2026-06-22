"""Repository layer — intention-revealing data access over the ORM.

Each repository wraps a SQLAlchemy ``Session`` and exposes methods for one
aggregate. Services depend on these instead of raw SQL, which keeps data access
testable and hides the storage details.
"""

from orchestrator.repositories.credential_repo import CredentialRepository
from orchestrator.repositories.organization_repo import OrganizationRepository
from orchestrator.repositories.workspace_repo import WorkspaceRepository

__all__ = [
    "OrganizationRepository",
    "CredentialRepository",
    "WorkspaceRepository",
]

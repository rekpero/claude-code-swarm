"""Workspace repository."""

from __future__ import annotations

from sqlalchemy import select

from orchestrator.models.workspace import Workspace
from orchestrator.repositories.base import Repository


class WorkspaceRepository(Repository[Workspace]):
    model = Workspace

    def get_org_id(self, workspace_id: str) -> str | None:
        """Resolve the owning org for a workspace (used by the exec path)."""
        ws = self.get(workspace_id)
        return ws.org_id if ws else None

    def list_for_org(self, org_id: str) -> list[Workspace]:
        stmt = select(Workspace).where(Workspace.org_id == org_id)
        return list(self.session.scalars(stmt).all())

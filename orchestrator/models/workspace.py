"""Workspace model (ported from legacy db.py, now org-scoped).

This is the first existing table ported to the ORM. It gains an ``org_id`` FK so
a workspace belongs to a tenant. The legacy sqlite ``workspaces`` table and its
``db.py`` accessors remain until ``workspace_manager`` is fully migrated
(strangler-fig).

    TODO(port): migrate workspace_env / workspace_env_sync to ORM models and move
    workspace_manager off legacy db.py.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.models.base import Base, TimestampMixin, uuid_pk


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = uuid_pk()
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    github_repo: Mapped[str] = mapped_column(String(300), nullable=False)
    repo_url: Mapped[str] = mapped_column(String(500), nullable=False)
    local_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(200), default="main")
    status: Mapped[str] = mapped_column(String(40), default="active")
    is_monorepo: Mapped[int] = mapped_column(Integer, default=0)
    structure_json: Mapped[str] = mapped_column(Text, default="{}")

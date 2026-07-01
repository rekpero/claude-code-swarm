"""Tenant model: organizations, users, memberships.

The ``Organization`` is the tenant anchor — every piece of tenant data
(credentials, workspaces, issues, …) hangs off an org. ``User`` and
``Membership`` are intentionally minimal in this slice; full authentication is a
later slice.

    TODO(auth-slice): flesh out User (GitHub OAuth fields, last_login_at) and
    Organization (plan, stripe_customer_id, status) when the login + billing
    slices land.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from orchestrator.models.base import Base, TimestampMixin, uuid_pk


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[str] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    # TODO(billing): plan, stripe_customer_id, subscription_status
    # TODO(auth-slice): owner_user_id

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = uuid_pk()
    github_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # TODO(auth-slice): avatar_url, last_login_at, github OAuth token storage

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_membership"),)

    id: Mapped[str] = uuid_pk()
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # owner | admin | member
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")

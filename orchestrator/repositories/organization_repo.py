"""Organization repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from orchestrator.models.organization import Organization
from orchestrator.repositories.base import Repository

# Slug of the bootstrap org used during the single-tenant→multi-tenant
# transition, before GitHub-OAuth login exists.
#   TODO(auth-slice): remove the default org once real orgs are created at login.
DEFAULT_ORG_SLUG = "default"


class OrganizationRepository(Repository[Organization]):
    model = Organization

    def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(Organization.slug == slug)
        return self.session.scalars(stmt).first()

    def create(self, name: str, slug: str) -> Organization:
        return self.add(Organization(name=name, slug=slug))

    def get_or_create_default(self) -> Organization:
        """Return the bootstrap org, creating it on first use.

        Lets the refactored execution path resolve an ``org_id`` before the auth
        slice introduces real organizations.

        Uses catch-and-retry to handle the race where concurrent callers all
        observe a missing slug and attempt to INSERT simultaneously — the loser
        catches IntegrityError and re-reads the row the winner committed.
        """
        org = self.get_by_slug(DEFAULT_ORG_SLUG)
        if org is not None:
            return org
        try:
            org = self.create(name="Default", slug=DEFAULT_ORG_SLUG)
            # Flush so the INSERT reaches the DB and any constraint violation
            # surfaces here rather than at commit time.
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            org = self.get_by_slug(DEFAULT_ORG_SLUG)
            if org is None:
                raise
        return org

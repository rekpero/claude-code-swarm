"""Organization repository."""

from __future__ import annotations

from sqlalchemy import select

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
        """
        org = self.get_by_slug(DEFAULT_ORG_SLUG)
        if org is None:
            org = self.create(name="Default", slug=DEFAULT_ORG_SLUG)
        return org

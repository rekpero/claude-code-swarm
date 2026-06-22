"""Encrypted credential storage: tenant_keys + org_credentials.

``TenantKey`` holds each org's wrapped data-encryption-key (DEK). ``OrgCredential``
holds the ciphertext of a provider credential (the Anthropic API key today),
encrypted under that org's DEK. Plaintext secrets are never stored.

See ``orchestrator/infra/crypto.py`` for the key hierarchy and
``orchestrator/secrets/fernet_store.py`` for how these tables are used.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from orchestrator.models.base import Base, TimestampMixin, uuid_pk

# Credential providers (extensible). Only Anthropic is used in this slice.
PROVIDER_ANTHROPIC = "anthropic"

# Credential status values.
STATUS_ACTIVE = "active"
STATUS_INVALID = "invalid"
STATUS_REVOKED = "revoked"


class TenantKey(Base, TimestampMixin):
    """Per-tenant wrapped data-encryption-key (DEK)."""

    __tablename__ = "tenant_keys"

    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    # DEK encrypted ("wrapped") by the master KEK. Never store the raw DEK.
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OrgCredential(Base, TimestampMixin):
    """An encrypted provider credential belonging to an organization."""

    __tablename__ = "org_credentials"
    __table_args__ = (
        UniqueConstraint("org_id", "provider", name="uq_org_provider_credential"),
    )

    id: Mapped[str] = uuid_pk()
    org_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(
        String(40), nullable=False, default=PROVIDER_ANTHROPIC
    )
    # The secret (e.g. ANTHROPIC_API_KEY) encrypted under the org's DEK.
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_ACTIVE
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

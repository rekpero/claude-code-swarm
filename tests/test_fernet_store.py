"""Integration tests for FernetSecretStore (with the DB)."""

from __future__ import annotations

import pytest

from orchestrator.infra.db import session_scope
from orchestrator.repositories.credential_repo import (
    CredentialRepository,
    TenantKeyRepository,
)
from orchestrator.repositories.organization_repo import OrganizationRepository
from orchestrator.secrets.fernet_store import FernetSecretStore


def _make_org(slug: str) -> str:
    with session_scope() as s:
        return OrganizationRepository(s).create(slug.title(), slug).id


def test_put_get_round_trip(db, master_key):
    org_id = _make_org("acme")
    store = FernetSecretStore(master_key=master_key, session_scope=session_scope)
    store.put(org_id, "anthropic", "sk-ant-api03-AAA")
    assert store.get(org_id, "anthropic") == "sk-ant-api03-AAA"


def test_tenants_are_isolated(db, master_key):
    a, b = _make_org("acme"), _make_org("beta")
    store = FernetSecretStore(master_key=master_key, session_scope=session_scope)
    store.put(a, "anthropic", "sk-ant-api03-AAA")
    store.put(b, "anthropic", "sk-ant-api03-BBB")
    assert store.get(a, "anthropic") == "sk-ant-api03-AAA"
    assert store.get(b, "anthropic") == "sk-ant-api03-BBB"

    with session_scope() as s:
        # distinct per-tenant DEKs — no single key dumps everyone
        ka = TenantKeyRepository(s).get_for_org(a).wrapped_dek
        kb = TenantKeyRepository(s).get_for_org(b).wrapped_dek
        assert ka != kb
        # ciphertext at rest never contains the plaintext
        ct = CredentialRepository(s).get(a, "anthropic").ciphertext
        assert b"sk-ant" not in ct


def test_get_missing_returns_none(db, master_key):
    org_id = _make_org("acme")
    store = FernetSecretStore(master_key=master_key, session_scope=session_scope)
    assert store.get(org_id, "anthropic") is None


def test_put_replaces_existing(db, master_key):
    org_id = _make_org("acme")
    store = FernetSecretStore(master_key=master_key, session_scope=session_scope)
    store.put(org_id, "anthropic", "old")
    store.put(org_id, "anthropic", "new")
    assert store.get(org_id, "anthropic") == "new"


def test_delete(db, master_key):
    org_id = _make_org("acme")
    store = FernetSecretStore(master_key=master_key, session_scope=session_scope)
    store.put(org_id, "anthropic", "x")
    store.delete(org_id, "anthropic")
    assert store.get(org_id, "anthropic") is None


def test_requires_master_key():
    with pytest.raises(ValueError):
        FernetSecretStore(master_key="", session_scope=session_scope)


def test_concurrent_dek_creation_race(db, master_key):
    """Race loser catches IntegrityError, re-reads the winner's committed DEK."""
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    from orchestrator.infra import crypto as cr
    from orchestrator.repositories.credential_repo import TenantKeyRepository

    org_id = _make_org("acme")

    # Pre-commit a DEK row simulating the "race winner" having already inserted.
    real_dek = cr.generate_dek()
    real_wrapped = cr.wrap_dek(real_dek, master_key)
    with session_scope() as s:
        TenantKeyRepository(s).create(org_id, real_wrapped, cr.KEY_VERSION)

    store = FernetSecretStore(master_key=master_key, session_scope=session_scope)

    # Simulate the race loser:
    #   1. get_for_org returns None on the first call — the winner's INSERT isn't
    #      visible yet at the moment the loser checks.
    #   2. create() raises IntegrityError — the winner committed just before us.
    #   3. get_for_org delegates to the real implementation on subsequent calls so
    #      the re-read after rollback finds the committed winner row.
    real_get_for_org = TenantKeyRepository.get_for_org
    _call_count = 0

    def _first_call_returns_none(self, org_id):
        nonlocal _call_count
        _call_count += 1
        if _call_count == 1:
            return None
        return real_get_for_org(self, org_id)

    def _raise_integrity(*args, **kwargs):
        raise SAIntegrityError("UNIQUE constraint failed", None, None)

    with patch.object(TenantKeyRepository, "get_for_org", _first_call_returns_none):
        with patch.object(TenantKeyRepository, "create", _raise_integrity):
            # put() must catch the IntegrityError, re-read the winner's key, and succeed.
            store.put(org_id, "anthropic", "sk-ant-race-test")

    assert store.get(org_id, "anthropic") == "sk-ant-race-test"


def test_dek_creation_race_does_not_lose_sibling_writes_in_same_transaction(db, master_key):
    """The DEK INSERT race is recovered via a SAVEPOINT, not a full rollback.

    A bare ``session.rollback()`` on the IntegrityError would undo the *entire*
    transaction on that session — including any other work already flushed on
    it before the race was hit — not just the failed INSERT.
    """
    from unittest.mock import patch

    from sqlalchemy.exc import IntegrityError as SAIntegrityError

    from orchestrator.infra import crypto as cr
    from orchestrator.repositories.credential_repo import TenantKeyRepository
    from orchestrator.repositories.organization_repo import OrganizationRepository

    org_id = _make_org("acme")

    real_dek = cr.generate_dek()
    real_wrapped = cr.wrap_dek(real_dek, master_key)
    with session_scope() as s:
        TenantKeyRepository(s).create(org_id, real_wrapped, cr.KEY_VERSION)

    store = FernetSecretStore(master_key=master_key, session_scope=session_scope)

    real_get_for_org = TenantKeyRepository.get_for_org
    _call_count = 0

    def _first_call_returns_none(self, org_id):
        nonlocal _call_count
        _call_count += 1
        if _call_count == 1:
            return None
        return real_get_for_org(self, org_id)

    def _raise_integrity(*args, **kwargs):
        raise SAIntegrityError("UNIQUE constraint failed", None, None)

    with session_scope() as s:
        # A sibling write earlier in the SAME transaction as the DEK race
        # below — it must survive the race's internal rollback.
        OrganizationRepository(s).create("Sibling Co", "sibling-co")
        with patch.object(TenantKeyRepository, "get_for_org", _first_call_returns_none):
            with patch.object(TenantKeyRepository, "create", _raise_integrity):
                store._get_or_create_dek(TenantKeyRepository(s), org_id)

    with session_scope() as s:
        assert OrganizationRepository(s).get_by_slug("sibling-co") is not None

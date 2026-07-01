"""Tests for ApiKeyCredentialProvider, using a fake in-memory SecretStore."""

from __future__ import annotations

import pytest

from orchestrator.credentials.api_key_provider import ApiKeyCredentialProvider
from orchestrator.credentials.base import MissingCredentialError
from orchestrator.infra.db import session_scope
from orchestrator.models.credential import STATUS_ACTIVE, STATUS_INVALID
from orchestrator.repositories.credential_repo import CredentialRepository
from orchestrator.repositories.organization_repo import OrganizationRepository
from orchestrator.secrets.base import SecretStore


class FakeSecretStore(SecretStore):
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], str] = {}

    def put(self, org_id, name, plaintext):
        self._data[(org_id, name)] = plaintext

    def get(self, org_id, name):
        return self._data.get((org_id, name))

    def delete(self, org_id, name):
        self._data.pop((org_id, name), None)


def test_for_org_returns_anthropic_env():
    store = FakeSecretStore()
    store.put("org1", "anthropic", "sk-ant-api03-AAA")
    provider = ApiKeyCredentialProvider(store, session_scope)
    creds = provider.for_org("org1")
    assert creds.env == {"ANTHROPIC_API_KEY": "sk-ant-api03-AAA"}


def test_for_org_missing_raises():
    provider = ApiKeyCredentialProvider(FakeSecretStore(), session_scope)
    with pytest.raises(MissingCredentialError):
        provider.for_org("org-without-key")


def test_validate_updates_status(db, monkeypatch):
    # seed an org + credential row so set_status has something to update
    store = FakeSecretStore()
    with session_scope() as s:
        org = OrganizationRepository(s).create("Acme", "acme")
        CredentialRepository(s).upsert(org.id, b"ciphertext", 1)
        org_id = org.id
    store.put(org_id, "anthropic", "sk-ant-api03-AAA")

    provider = ApiKeyCredentialProvider(store, session_scope)

    class _Resp:
        status_code = 200

    monkeypatch.setattr(
        "orchestrator.credentials.api_key_provider.httpx.get",
        lambda *a, **k: _Resp(),
    )
    assert provider.validate(org_id) is True
    with session_scope() as s:
        assert CredentialRepository(s).get(org_id).status == STATUS_ACTIVE

    class _Bad:
        status_code = 401

    monkeypatch.setattr(
        "orchestrator.credentials.api_key_provider.httpx.get",
        lambda *a, **k: _Bad(),
    )
    assert provider.validate(org_id) is False
    with session_scope() as s:
        assert CredentialRepository(s).get(org_id).status == STATUS_INVALID

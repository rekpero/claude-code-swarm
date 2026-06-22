"""Single-tenant (OSS self-host) must behave exactly like before — no DB,
env credentials, and the legacy CLAUDE_CODE_OAUTH_TOKEN still injected as-is.
"""

from __future__ import annotations

from orchestrator.agent_pool import AgentPool
from orchestrator.container import build_container
from orchestrator.credentials.env_provider import EnvCredentialProvider
from orchestrator.settings import Settings, get_settings
from orchestrator.tenancy import SINGLE_TENANT_ORG_ID, resolve_org_id


def test_default_mode_is_single_tenant():
    assert get_settings().deployment_mode == "single_tenant"
    assert get_settings().is_multi_tenant is False


def test_single_tenant_container_has_no_secret_store(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-TEAM")
    c = build_container(Settings())
    assert c.secret_store is None
    assert isinstance(c.credential_provider, EnvCredentialProvider)


def test_resolve_org_id_is_constant_without_db():
    # No `db` fixture here on purpose: single-tenant must not touch Postgres.
    assert resolve_org_id() == SINGLE_TENANT_ORG_ID
    assert resolve_org_id("any-workspace") == SINGLE_TENANT_ORG_ID


def test_legacy_oauth_token_injected_exactly_like_before(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-TEAM")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pool = AgentPool(credential_provider=EnvCredentialProvider(Settings()))
    env = pool._agent_credential_env(workspace_id=None)
    assert env == {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-TEAM"}


def test_api_key_also_works_for_selfhost(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SELF")
    pool = AgentPool(credential_provider=EnvCredentialProvider(Settings()))
    env = pool._agent_credential_env(workspace_id=None)
    assert env == {"ANTHROPIC_API_KEY": "sk-ant-api03-SELF"}

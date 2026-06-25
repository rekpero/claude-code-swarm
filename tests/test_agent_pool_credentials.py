"""Tests that AgentPool surfaces MissingCredentialError cleanly instead of
spawning a subprocess that would immediately fail."""

from __future__ import annotations

import pytest

from orchestrator.agent_pool import AgentPool
from orchestrator.credentials.base import CredentialProvider, MissingCredentialError


class RaisingProvider(CredentialProvider):
    """Simulates an org that has not connected an Anthropic credential."""

    def for_org(self, org_id):
        raise MissingCredentialError(org_id, "anthropic_api_key")

    def validate(self, org_id):
        return False


def test_spawn_agent_missing_credential_raises_without_popen(monkeypatch):
    pool = AgentPool(credential_provider=RaisingProvider())

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.Popen must not run without a credential")

    monkeypatch.setattr("orchestrator.agent_pool.subprocess.Popen", _fail_if_called)

    with pytest.raises(MissingCredentialError):
        pool._spawn_agent(
            agent_id="agent-test-1",
            prompt="do work",
            worktree_path="/tmp/does-not-matter",
            max_turns=5,
            issue_number=1,
            agent_type="implement",
        )

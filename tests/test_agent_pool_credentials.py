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


def test_resume_rate_limited_agent_missing_credential_fails_cleanly(monkeypatch, tmp_path):
    """resume_rate_limited_agent must not let MissingCredentialError escape: it
    should mark the agent failed, reset the issue, and never call Popen."""
    pool = AgentPool(credential_provider=RaisingProvider())

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.Popen must not run without a credential")

    monkeypatch.setattr("orchestrator.agent_pool.subprocess.Popen", _fail_if_called)

    finished = {}
    updated_issues = {}
    monkeypatch.setattr(
        "orchestrator.agent_pool.db.get_workspace",
        lambda workspace_id: {"id": workspace_id, "local_path": str(tmp_path), "github_repo": "org/repo"},
    )
    monkeypatch.setattr(
        "orchestrator.agent_pool.db.finish_agent",
        lambda agent_id, status, error_message=None: finished.update(agent_id=agent_id, status=status),
    )
    monkeypatch.setattr(
        "orchestrator.agent_pool.db.update_issue",
        lambda issue_number, **kwargs: updated_issues.update(issue_number=issue_number, **kwargs),
    )
    monkeypatch.setattr("orchestrator.agent_pool.cleanup_worktree", lambda *args, **kwargs: None)

    agent_record = {
        "agent_id": "agent-test-2",
        "issue_number": 1,
        "agent_type": "implement",
        "worktree_path": str(tmp_path),
        "branch_name": "fix/issue-1",
        "pr_number": None,
        "session_id": "session-1",
        "resume_count": 0,
        "workspace_id": "ws-1",
    }

    result = pool.resume_rate_limited_agent(agent_record)

    assert result is None
    assert finished == {"agent_id": "agent-test-2", "status": "failed"}
    assert updated_issues == {"issue_number": 1, "workspace_id": "ws-1", "status": "pending"}

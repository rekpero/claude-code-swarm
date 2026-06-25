"""Tests that the planning agent surfaces MissingCredentialError cleanly
instead of spawning a subprocess that would immediately fail, or leaving the
planning session stuck on 'generating'."""

from __future__ import annotations

from orchestrator import planner
from orchestrator.credentials.base import MissingCredentialError


def test_run_planning_agent_impl_missing_credential_fails_cleanly(monkeypatch, tmp_path):
    def _raise(workspace_id=None):
        raise MissingCredentialError(workspace_id, "anthropic_api_key")

    monkeypatch.setattr(planner, "_planning_credential_env", _raise)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.Popen must not run without a credential")

    monkeypatch.setattr(planner.subprocess, "Popen", _fail_if_called)

    updated_sessions = {}
    monkeypatch.setattr(
        planner.db,
        "update_planning_session",
        lambda session_id, **kwargs: updated_sessions.update(session_id=session_id, **kwargs),
    )

    session_id = "session-test-1"
    workspace = {"id": "ws-1", "local_path": str(tmp_path)}

    planner._run_planning_agent_impl(session_id, workspace, "plan this")

    assert updated_sessions == {"session_id": session_id, "status": "error"}
    assert session_id not in planner._starting
    assert session_id not in planner._cancelled

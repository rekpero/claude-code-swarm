"""Shared test fixtures.

Each test gets a fresh in-memory SQLite database wired into the same
``session_scope`` the production code uses, so repositories and stores are
exercised end-to-end without a real Postgres. (SQLite is fine for these unit
tests; schema parity with Postgres is guaranteed by the Alembic migration.)
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from orchestrator.infra import crypto
from orchestrator.infra.db import reset_engine_for_tests, session_scope
from orchestrator.models import Base


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure each test reads fresh settings (env overrides take effect)."""
    from orchestrator.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def multi_tenant(monkeypatch):
    """Switch to multi-tenant mode for a test."""
    monkeypatch.setenv("DEPLOYMENT_MODE", "multi_tenant")
    from orchestrator.settings import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared in-memory connection
    )
    reset_engine_for_tests(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def master_key() -> str:
    return crypto.generate_master_key()


@pytest.fixture()
def scope():
    return session_scope

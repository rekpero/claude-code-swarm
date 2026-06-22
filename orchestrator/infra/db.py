"""SQLAlchemy engine and session factory (Postgres, v2).

This is the new system of record. It coexists with the legacy sqlite-backed
``orchestrator/db.py`` during the strangler-fig migration; modules are ported
onto repositories (which use these sessions) one at a time.

    TODO(port): once every module uses repositories, delete legacy
    ``orchestrator/db.py`` and its sqlite schema.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from orchestrator.settings import get_settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine (lazily created)."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,  # recover from dropped connections
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory (lazily created)."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), expire_on_commit=False, future=True
        )
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope around a series of operations.

    Commits on success, rolls back on exception, always closes. Repositories
    accept a ``Session`` so callers control transaction boundaries::

        with session_scope() as s:
            repo = CredentialRepository(s)
            repo.upsert(...)
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests(engine: Engine) -> None:
    """Replace the global engine/session factory (used by the test suite)."""
    global _engine, _SessionFactory
    _engine = engine
    _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

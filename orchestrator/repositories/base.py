"""Generic repository base."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from orchestrator.models.base import Base

T = TypeVar("T", bound=Base)


class Repository(Generic[T]):
    """Base repository holding a session and the mapped model type."""

    model: type[T]

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, id_: str) -> T | None:
        return self.session.get(self.model, id_)

    def add(self, entity: T) -> T:
        self.session.add(entity)
        self.session.flush()  # assign defaults/ids without committing
        return entity

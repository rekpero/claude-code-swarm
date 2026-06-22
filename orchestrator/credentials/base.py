"""CredentialProvider interface + value object.

A CredentialProvider answers one question for the execution path: "given this
org, what credential environment should the agent subprocess run with?" The
execution path injects ``AgentCredentials.env`` and never learns whether the
credential is a stored API key, a federated token, or anything else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class MissingCredentialError(Exception):
    """Raised when an org has not connected a required credential."""

    def __init__(self, org_id: str, provider: str) -> None:
        super().__init__(
            f"Organization {org_id} has no '{provider}' credential connected"
        )
        self.org_id = org_id
        self.provider = provider


@dataclass(frozen=True)
class AgentCredentials:
    """Environment variables to inject into an agent subprocess."""

    env: dict[str, str]


class CredentialProvider(ABC):
    @abstractmethod
    def for_org(self, org_id: str) -> AgentCredentials:
        """Return the credential env for an org's agent run.

        Raises MissingCredentialError if the org has no usable credential.
        """

    @abstractmethod
    def validate(self, org_id: str) -> bool:
        """Cheaply verify the org's credential works; update its status."""

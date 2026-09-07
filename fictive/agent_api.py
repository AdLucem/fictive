"""Provider-neutral contracts used at Fictive's agent integration boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentRequest:
    """One bounded agent invocation assembled from an actor instruction."""

    history: Sequence[Mapping[str, Any]]
    task: str | None
    workspace: Path
    profile: str
    requested_tools: tuple[str, ...] = ()
    request_limit: int = 20
    tool_call_limit: int = 50
    run_id: str | None = None


class AgentResult(Protocol):
    """Structural result contract returned by a standalone executor."""

    output: str
    status: str
    messages: list[dict[str, Any]]
    events: list[dict[str, Any]]
    usage: dict[str, Any]
    changed_paths: tuple[str, ...]
    run_id: str


class AgentExecutor(Protocol):
    """Executor injected by trusted host application code."""

    @property
    def workspace_root(self) -> Path:
        ...

    def run(self, request: AgentRequest) -> AgentResult:
        ...


class AgentRunFailed(RuntimeError):
    """Raised when an executor returns a non-completed result."""

    def __init__(self, result: AgentResult):
        self.result = result
        super().__init__(f"Agent run {result.run_id} finished with status {result.status!r}")

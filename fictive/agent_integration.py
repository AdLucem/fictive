"""Actor/interpreter bridge for the standalone agent harness."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .agent_api import AgentRequest, AgentResult


def resolve_agent_workspace(host_root: Path, requested_workspace: str | Path) -> Path:
    """Return a canonical relative workspace proven to be beneath host_root."""

    if not isinstance(requested_workspace, (str, Path)):
        raise ValueError("Agent workspace must be a string or path")
    requested = Path(requested_workspace)
    if requested.is_absolute():
        raise ValueError("Agent workspace must be relative to the configured agent root")

    try:
        resolved = (host_root / requested).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Agent workspace does not exist or cannot be resolved") from exc
    if not resolved.is_dir():
        raise ValueError("Agent workspace must resolve to an existing directory")
    if not resolved.is_relative_to(host_root):
        raise ValueError("Agent workspace resolves outside the configured agent root")
    return resolved.relative_to(host_root)


def build_agent_request(
    *,
    history: list[dict[str, Any]],
    task: str | None,
    workspace: Path,
    profile: str,
    tools: list[str] | tuple[str, ...] | None,
    request_limit: int,
    tool_call_limit: int,
) -> AgentRequest:
    """Snapshot mutable actor inputs into the stable harness request shape."""

    return AgentRequest(
        history=deepcopy(history),
        task=task,
        workspace=workspace,
        profile=profile,
        requested_tools=tuple(tools or ()),
        request_limit=request_limit,
        tool_call_limit=tool_call_limit,
    )


def agent_result_trace(result: AgentResult) -> dict[str, Any]:
    """Copy the structured transcript into Fictive's ordinary-value store."""

    return {
        "run_id": result.run_id,
        "status": result.status,
        "messages": deepcopy(result.messages),
        "events": deepcopy(result.events),
        "usage": deepcopy(result.usage),
        "changed_paths": list(result.changed_paths),
    }

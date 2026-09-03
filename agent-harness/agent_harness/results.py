"""Provider-neutral request/result contracts and transcript normalization."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


@dataclass(frozen=True)
class AgentRequest:
    history: Sequence[Mapping[str, Any]]
    task: str | None
    workspace: Path
    profile: str
    requested_tools: tuple[str, ...] = ()
    request_limit: int = 20
    tool_call_limit: int = 50
    run_id: str | None = None


@dataclass(frozen=True)
class AgentResult:
    output: str
    status: str
    messages: list[dict[str, Any]]
    events: list[dict[str, Any]]
    usage: dict[str, Any]
    changed_paths: tuple[str, ...]
    run_id: str


class AgentExecutor(Protocol):
    @property
    def workspace_root(self) -> Path:
        """Return the canonical maximum filesystem root granted by the host."""

        ...

    def run(self, request: AgentRequest) -> AgentResult:
        """Execute one bounded agent run."""

        ...


_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret)(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER_SECRET = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


@dataclass(frozen=True)
class Redactor:
    secrets: tuple[str, ...] = field(default_factory=tuple)

    def text(self, value: str) -> str:
        redacted = value
        for secret in self.secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        redacted = _ASSIGNMENT_SECRET.sub(
            lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
            redacted,
        )
        return _BEARER_SECRET.sub("Bearer [REDACTED]", redacted)

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {str(key): self.value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.value(item) for item in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self.text(str(value))


def _part_data(part: Any, redactor: Redactor) -> dict[str, Any]:
    if isinstance(part, SystemPromptPart):
        return {"type": "system", "content": redactor.text(part.content)}
    if isinstance(part, UserPromptPart):
        return {"type": "user", "content": redactor.value(part.content)}
    if isinstance(part, TextPart):
        return {"type": "text", "content": redactor.text(part.content)}
    if isinstance(part, ToolCallPart):
        return {
            "type": "tool_call",
            "tool_name": part.tool_name,
            "tool_call_id": part.tool_call_id,
            "args": redactor.value(part.args),
        }
    if isinstance(part, ToolReturnPart):
        return {
            "type": "tool_result",
            "tool_name": part.tool_name,
            "tool_call_id": part.tool_call_id,
            "content": redactor.value(part.content),
        }
    if isinstance(part, RetryPromptPart):
        return {
            "type": "retry",
            "tool_name": part.tool_name,
            "tool_call_id": part.tool_call_id,
            "content": redactor.value(part.content),
        }
    return {"type": getattr(part, "part_kind", type(part).__name__)}


def normalize_messages(messages: Sequence[ModelMessage], redactor: Redactor) -> list[dict[str, Any]]:
    """Remove SDK objects while preserving conversational and tool structure."""

    normalized: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            kind = "request"
        elif isinstance(message, ModelResponse):
            kind = "response"
        else:
            kind = "message"
        normalized.append(
            {
                "kind": kind,
                "parts": [_part_data(part, redactor) for part in message.parts],
            }
        )
    return normalized


def events_from_messages(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten tool activity into a compact event stream."""

    events: list[dict[str, Any]] = []
    for message in messages:
        for part in message["parts"]:
            if part["type"] in {"tool_call", "tool_result", "retry"}:
                events.append(dict(part))
    return events


def normalize_usage(usage: Any, redactor: Redactor) -> dict[str, Any]:
    """Normalize the public RunUsage fields without retaining SDK types."""

    fields = ("requests", "input_tokens", "output_tokens", "tool_calls")
    normalized = {name: getattr(usage, name) for name in fields if hasattr(usage, name)}
    details = getattr(usage, "details", None)
    if details:
        normalized["details"] = redactor.value(details)
    # Assert JSON compatibility while still returning ordinary dictionaries.
    json.dumps(normalized)
    return normalized

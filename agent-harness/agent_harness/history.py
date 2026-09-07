"""Convert provider-neutral chat history into Pydantic AI messages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)

from .errors import ConfigurationError


def history_to_messages(history: Sequence[Mapping[str, Any]]) -> list[ModelMessage]:
    """Validate and convert simple role/content messages without duplication."""

    converted: list[ModelMessage] = []
    for index, message in enumerate(history):
        if not isinstance(message, Mapping):
            raise ConfigurationError(f"History entry at index {index} must be a mapping")
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ConfigurationError(f"Unsupported history role at index {index}: {role!r}")
        if not isinstance(content, str):
            raise ConfigurationError(f"History content at index {index} must be a string")

        if role == "system":
            converted.append(ModelRequest(parts=[SystemPromptPart(content)]))
        elif role == "user":
            converted.append(ModelRequest(parts=[UserPromptPart(content)]))
        else:
            converted.append(ModelResponse(parts=[TextPart(content)]))
    return converted

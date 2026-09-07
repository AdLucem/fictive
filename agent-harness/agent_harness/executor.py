"""Bounded Pydantic AI execution behind the standalone harness contract."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Mapping
from pathlib import Path

from pydantic_ai import Agent, UsageLimits, capture_run_messages
from pydantic_ai.usage import RunUsage

from .config import AgentProfile, load_profiles
from .errors import ConfigurationError
from .history import history_to_messages
from .providers import ModelBuilder, build_model
from .results import (
    AgentRequest,
    AgentResult,
    Redactor,
    events_from_messages,
    normalize_messages,
    normalize_usage,
)
from .workspace import (
    build_filesystem_toolset,
    changed_paths,
    resolve_workspace,
    select_tools,
    snapshot_workspace,
)


class PydanticAgentExecutor:
    """Execute provider-neutral requests inside a trusted host workspace."""

    def __init__(
        self,
        *,
        profiles: Mapping[str, AgentProfile | Mapping[str, object]],
        workspace_root: Path,
        model_builders: Mapping[str, ModelBuilder] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._profiles = load_profiles(profiles)
        self._workspace_root = resolve_workspace(Path(workspace_root), Path("."))
        self._model_builders = dict(model_builders or {})
        self._environ = os.environ if environ is None else environ

    @property
    def workspace_root(self) -> Path:
        """Return the canonical maximum filesystem root for integration checks."""

        return self._workspace_root

    def run(self, request: AgentRequest) -> AgentResult:
        """Execute one run, returning normalized success or provider failure."""

        limits = (request.request_limit, request.tool_call_limit)
        if any(not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0 for limit in limits):
            raise ConfigurationError("Request and tool-call limits must be positive")
        if request.task is not None and not isinstance(request.task, str):
            raise ConfigurationError("Agent task must be a string or None")

        try:
            profile = self._profiles[request.profile]
        except KeyError as exc:
            raise ConfigurationError(f"Unknown agent profile: {request.profile!r}") from exc

        workspace = resolve_workspace(self._workspace_root, Path(request.workspace))
        enabled_tools = select_tools(profile, request.requested_tools)
        built_model = build_model(profile, self._environ, self._model_builders)
        redactor = Redactor(built_model.secrets)
        message_history = history_to_messages(request.history)
        toolset = build_filesystem_toolset(profile, workspace, enabled_tools)
        run_id = request.run_id or str(uuid.uuid4())
        before = snapshot_workspace(workspace, denied_patterns=profile.denied_patterns)

        agent = Agent(
            built_model.model,
            instructions=profile.instructions,
            model_settings=dict(profile.model_settings),
            toolsets=[toolset] if toolset is not None else (),
        )

        run_usage = RunUsage()
        with capture_run_messages() as captured_messages:
            try:
                result = asyncio.run(
                    agent.run(
                        request.task,
                        message_history=message_history,
                        run_id=run_id,
                        usage=run_usage,
                        usage_limits=UsageLimits(
                            request_limit=request.request_limit,
                            tool_calls_limit=request.tool_call_limit,
                        ),
                    )
                )
            except Exception as exc:
                after = snapshot_workspace(workspace, denied_patterns=profile.denied_patterns)
                messages = normalize_messages(captured_messages, redactor)
                events = events_from_messages(messages)
                events.append(
                    {
                        "type": "error",
                        "error_type": type(exc).__name__,
                        "message": redactor.text(str(exc)),
                    }
                )
                return AgentResult(
                    output="",
                    status="failed",
                    messages=messages,
                    events=events,
                    usage=normalize_usage(run_usage, redactor),
                    changed_paths=changed_paths(before, after),
                    run_id=run_id,
                )

        after = snapshot_workspace(workspace, denied_patterns=profile.denied_patterns)
        messages = normalize_messages(result.all_messages(), redactor)
        return AgentResult(
            output=redactor.text(str(result.output)),
            status="completed",
            messages=messages,
            events=events_from_messages(messages),
            usage=normalize_usage(result.usage, redactor),
            changed_paths=changed_paths(before, after),
            run_id=run_id,
        )

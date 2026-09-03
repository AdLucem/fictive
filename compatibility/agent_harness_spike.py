"""Verify the agent-harness dependency stack without importing llm-utils.

The default check is offline and deterministic. It verifies the installed
versions, constructs an Anthropic-compatible MiniMax model without making a
request, and runs a complete filesystem tool-call cycle through Pydantic AI's
local FunctionModel.

Use ``--live`` to make an opt-in MiniMax request. The live check requires
MINIMAX_API_KEY and MINIMAX_MODEL. MINIMAX_BASE_URL defaults to MiniMax's
international Anthropic-compatible endpoint.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai_harness import FileSystem


EXPECTED_VERSIONS = {
    "anthropic": "1.3.0",
    "pydantic-ai-harness": "0.28.1",
    "pydantic-ai-slim": "2.37.0",
}
DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"
OFFLINE_MODEL_NAME = "MiniMax-M3"
PROBE_CONTENT = "fictive-agent-harness-compatibility-ok"


def verify_versions() -> None:
    """Fail when the environment differs from the compatibility-spike pins."""

    mismatches: list[str] = []
    for distribution, expected in EXPECTED_VERSIONS.items():
        actual = importlib.metadata.version(distribution)
        if actual != expected:
            mismatches.append(f"{distribution}: expected {expected}, found {actual}")

    if mismatches:
        raise RuntimeError("Dependency version mismatch:\n- " + "\n- ".join(mismatches))


def build_minimax_model(*, api_key: str, base_url: str, model_name: str) -> AnthropicModel:
    """Build a Pydantic AI model for an Anthropic-compatible MiniMax API."""

    provider = AnthropicProvider(api_key=api_key, base_url=base_url)
    if str(provider.base_url).rstrip("/") != base_url.rstrip("/"):
        raise AssertionError("The Anthropic provider changed the configured base URL")
    return AnthropicModel(model_name, provider=provider)


@contextmanager
def workspace_path(path: Path | None) -> Iterator[Path]:
    """Yield an explicit workspace or a temporary one for the spike."""

    if path is not None:
        resolved = path.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"Workspace is not a directory: {resolved}")
        yield resolved
        return

    with tempfile.TemporaryDirectory(prefix="fictive-agent-harness-") as temp_dir:
        yield Path(temp_dir)


def has_part(messages: list[ModelMessage], part_type: type[object]) -> bool:
    return any(isinstance(part, part_type) for message in messages for part in message.parts)


def run_offline_tool_check(workspace: Path) -> None:
    """Run a deterministic read_file tool call without network access."""

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=workspace,
        prefix="agent-harness-probe-",
        suffix=".txt",
        delete=False,
    ) as probe_file:
        probe_file.write(PROBE_CONTENT + "\n")
        probe_path = Path(probe_file.name)

    probe_filename = probe_path.name

    async def model_function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returned_parts = [
            part
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        ]

        if not returned_parts:
            available_tools = {tool.name for tool in info.function_tools}
            if "read_file" not in available_tools:
                raise AssertionError(f"read_file not registered; found {sorted(available_tools)}")

            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_file",
                        args={"path": probe_filename},
                        tool_call_id="offline-read-probe",
                    )
                ]
            )

        if PROBE_CONTENT not in str(returned_parts[-1].content):
            raise AssertionError("read_file tool result did not contain the probe content")

        return ModelResponse(parts=[TextPart(content=PROBE_CONTENT)])

    try:
        agent = Agent(
            FunctionModel(model_function, model_name="fictive-offline-compatibility-model"),
            capabilities=[FileSystem(root_dir=workspace, read_only=True)],
        )
        result = agent.run_sync(
            f"Read {probe_filename} and return its contents.",
            usage_limits=UsageLimits(request_limit=3, tool_calls_limit=1),
        )

        messages = result.all_messages()
        if result.output != PROBE_CONTENT:
            raise AssertionError(f"Unexpected offline result: {result.output!r}")
        if not has_part(messages, ToolCallPart):
            raise AssertionError("Offline run did not record a tool call")
        if not has_part(messages, ToolReturnPart):
            raise AssertionError("Offline run did not record a tool result")
    finally:
        probe_path.unlink(missing_ok=True)


def run_live_minimax_check(
    *,
    workspace: Path,
    api_key: str,
    base_url: str,
    model_name: str,
) -> None:
    """Confirm a real MiniMax model can call a client-side filesystem tool."""

    model = build_minimax_model(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
    )
    agent = Agent(
        model,
        instructions=(
            "This is a compatibility check. You must call list_directory exactly once "
            "with path '.' before answering. Keep the final answer to one short sentence."
        ),
        capabilities=[FileSystem(root_dir=workspace, read_only=True)],
    )
    result = agent.run_sync(
        "List the workspace and confirm that the filesystem tool worked.",
        usage_limits=UsageLimits(request_limit=3, tool_calls_limit=1),
    )

    messages = result.all_messages()
    if not has_part(messages, ToolCallPart):
        raise AssertionError("MiniMax returned text without making the required tool call")
    if not has_part(messages, ToolReturnPart):
        raise AssertionError("The MiniMax tool call did not produce a tool result")
    if not str(result.output).strip():
        raise AssertionError("MiniMax returned an empty final response")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Make a real MiniMax Anthropic-compatible tool-call request.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="Existing workspace for the check; a temporary directory is used by default.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("MINIMAX_MODEL"),
        help="MiniMax model ID (default: MINIMAX_MODEL).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MINIMAX_BASE_URL", DEFAULT_MINIMAX_BASE_URL),
        help="Anthropic-compatible API base URL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verify_versions()

    offline_model = build_minimax_model(
        api_key="compatibility-check-placeholder",
        base_url=args.base_url,
        model_name=args.model or OFFLINE_MODEL_NAME,
    )
    if offline_model.model_name != (args.model or OFFLINE_MODEL_NAME):
        raise AssertionError("The Anthropic adapter changed the configured MiniMax model ID")

    with workspace_path(args.workspace) as workspace:
        run_offline_tool_check(workspace)
        print("PASS: pinned imports, custom Anthropic endpoint, and offline tool loop")

        if not args.live:
            print("SKIP: live MiniMax check (pass --live and configure credentials)")
            return 0

        api_key = os.environ.get("MINIMAX_API_KEY")
        if not api_key:
            raise RuntimeError("--live requires MINIMAX_API_KEY")
        if not args.model:
            raise RuntimeError("--live requires --model or MINIMAX_MODEL")

        run_live_minimax_check(
            workspace=workspace,
            api_key=api_key,
            base_url=args.base_url,
            model_name=args.model,
        )
        print(f"PASS: live MiniMax text and tool calling with {args.model}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise

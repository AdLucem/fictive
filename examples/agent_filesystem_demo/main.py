"""Run Fictive's agent command against a workspace-scoped filesystem.

The flow is driven from Python with `fictive.Runtime` (the library
runtime) rather than from the JSON instruction list in
`scenario/filesystem_worker.json`, which the JSON runtime would load.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_harness import AgentPermissions, AgentProfile, PydanticAgentExecutor
from fictive import Actor, ActorConfig, Interpreter, Runtime, Store


DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"
SEED_NOTES = "Ada owns the release checklist. The next review is Friday.\n"


def message_parts(messages: list[ModelMessage], part_type: type[object]) -> list[object]:
    return [
        part
        for message in messages
        for part in message.parts
        if isinstance(part, part_type)
    ]


async def fake_filesystem_model(
    messages: list[ModelMessage],
    _info: AgentInfo,
) -> ModelResponse:
    """Deterministically read notes.txt, write summary.txt, then finish."""

    tool_returns = message_parts(messages, ToolReturnPart)
    if not tool_returns:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "read_file",
                    {"path": "notes.txt"},
                    "read-notes",
                )
            ]
        )
    if len(tool_returns) == 1:
        read_result = str(tool_returns[0].content)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "write_file",
                    {
                        "path": "summary.txt",
                        "content": (
                            "Offline agent summary\n"
                            "=====================\n"
                            f"{read_result}\n"
                        ),
                    },
                    "write-summary",
                )
            ]
        )
    return ModelResponse(
        parts=[TextPart("Read notes.txt and wrote the result to summary.txt.")]
    )


def build_executor(workspace_root: Path, provider: str) -> PydanticAgentExecutor:
    permissions = AgentPermissions(filesystem="workspace-write", shell=False)
    allowed_tools = ("read_file", "write_file")

    if provider == "fake":
        profile = AgentProfile(
            provider="fake",
            model="deterministic-filesystem-demo",
            permissions=permissions,
            allowed_tools=allowed_tools,
        )
        return PydanticAgentExecutor(
            profiles={"filesystem-demo": profile},
            workspace_root=workspace_root,
            model_builders={
                "fake": lambda _profile, _environ: FunctionModel(
                    fake_filesystem_model,
                    model_name="deterministic-filesystem-demo",
                )
            },
            environ={},
        )

    api_key = os.environ.get("MINIMAX_API_KEY")
    model = os.environ.get("MINIMAX_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            "MiniMax mode requires MINIMAX_API_KEY and MINIMAX_MODEL; "
            "see MINIMAX_AGENT_SETUP.md"
        )
    profile = AgentProfile(
        provider="anthropic",
        model=model,
        api_key_env="MINIMAX_API_KEY",
        base_url=os.environ.get("MINIMAX_BASE_URL", DEFAULT_MINIMAX_BASE_URL),
        permissions=permissions,
        allowed_tools=allowed_tools,
    )
    return PydanticAgentExecutor(
        profiles={"filesystem-demo": profile},
        workspace_root=workspace_root,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider",
        choices=("fake", "minimax"),
        default="fake",
        help="Model provider to use; fake is deterministic and offline.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help=(
            "Existing workspace containing notes.txt. By default, the demo uses "
            "a temporary workspace and seeds notes.txt automatically."
        ),
    )
    return parser.parse_args()


def workspace_context(requested: Path | None):
    if requested is None:
        return tempfile.TemporaryDirectory(prefix="fictive-agent-demo-")

    try:
        resolved = requested.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"Workspace does not exist: {requested}") from exc
    if not resolved.is_dir():
        raise ValueError(f"Workspace must be a directory: {resolved}")
    if not (resolved / "notes.txt").is_file():
        raise ValueError(f"Workspace must contain notes.txt: {resolved}")
    return nullcontext(resolved)


def run_demo(provider: str, requested_workspace: Path | None) -> None:
    scenario_dir = Path(__file__).resolve().parent / "scenario"

    with workspace_context(requested_workspace) as context_value:
        workspace_root = Path(context_value).resolve()
        if requested_workspace is None:
            (workspace_root / "notes.txt").write_text(SEED_NOTES, encoding="utf-8")

        # The worker carries no instruction list: the commands below are issued
        # from here through the library runtime.
        worker = Actor(
            ActorConfig(
                name="filesystem_worker",
                storage_dir=str(scenario_dir),
            )
        )
        store = Store()
        executor = build_executor(workspace_root, provider)
        interpreter = Interpreter(
            [worker],
            main_actor_name=worker.name,
            store=store,
            agent_executor=executor,
            agent_root=workspace_root,
        )
        runtime = Runtime(interpreter, start_actor_name=worker.name)

        # A `system` prompt is read exactly as given, so pass a full path.
        runtime.cmd_exec(
            "system",
            prompt=str(scenario_dir / "filesystem_worker_system.txt"),
        )
        runtime.cmd_exec(
            "agent",
            profile="filesystem-demo",
            prompt="Read notes.txt and write a concise summary to summary.txt.",
            workspace=".",
            tools=["read_file", "write_file"],
            request_limit=3,
            tool_call_limit=2,
            store="filesystem-answer",
            trace_store="filesystem-trace",
        )

        trace = store.get("filesystem-trace")
        summary_path = workspace_root / "summary.txt"
        print(f"Provider: {provider}")
        print(f"Workspace: {workspace_root}")
        print(f"Actor result: {store.get('filesystem-answer')}")
        print(f"Changed paths: {trace['changed_paths']}")
        print("summary.txt:")
        print(summary_path.read_text(encoding="utf-8").rstrip())


def main() -> int:
    args = parse_args()
    run_demo(args.provider, args.workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

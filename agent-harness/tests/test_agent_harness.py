from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
from pydantic_ai.models.function import AgentInfo, FunctionModel

from agent_harness import (
    AgentPermissions,
    AgentProfile,
    AgentRequest,
    ConfigurationError,
    PydanticAgentExecutor,
    WorkspaceViolation,
    history_to_messages,
    load_profiles,
    resolve_workspace,
)
from agent_harness.providers import build_model


def parts(messages: list[ModelMessage], part_type: type[object]) -> list[object]:
    return [part for message in messages for part in message.parts if isinstance(part, part_type)]


def make_executor(
    root: Path,
    model_function,
    *,
    permissions: str = "workspace-write",
    allowed_tools: tuple[str, ...] = (),
    environ: dict[str, str] | None = None,
    api_key_env: str | None = None,
) -> PydanticAgentExecutor:
    profile = AgentProfile(
        provider="fake",
        model="deterministic",
        api_key_env=api_key_env,
        permissions=AgentPermissions(filesystem=permissions),
        allowed_tools=allowed_tools,
    )
    return PydanticAgentExecutor(
        profiles={"test": profile},
        workspace_root=root,
        model_builders={
            "fake": lambda _profile, _environ: FunctionModel(
                model_function,
                model_name="deterministic",
            )
        },
        environ=environ or {},
    )


class ConfigAndHistoryTests(unittest.TestCase):
    def test_load_profiles_and_permission_defaults(self) -> None:
        profiles = load_profiles(
            {
                "read": {
                    "provider": "fake",
                    "model": "model-id",
                    "permissions": {"filesystem": "workspace-read"},
                }
            }
        )
        self.assertEqual(
            set(profiles["read"].allowed_tools),
            {"read_file", "list_directory", "search_files", "find_files", "file_info"},
        )

    def test_profile_rejects_permission_broadening_and_shell(self) -> None:
        with self.assertRaises(ConfigurationError):
            AgentProfile(
                provider="fake",
                model="model-id",
                permissions=AgentPermissions(filesystem="workspace-read"),
                allowed_tools=("write_file",),
            )
        with self.assertRaises(ConfigurationError):
            AgentPermissions(shell=True)

    def test_history_conversion_preserves_each_role_once(self) -> None:
        converted = history_to_messages(
            [
                {"role": "system", "content": "system text"},
                {"role": "user", "content": "user text"},
                {"role": "assistant", "content": "assistant text"},
            ]
        )
        self.assertIsInstance(converted[0], ModelRequest)
        self.assertIsInstance(converted[0].parts[0], SystemPromptPart)
        self.assertIsInstance(converted[1].parts[0], UserPromptPart)
        self.assertIsInstance(converted[2], ModelResponse)
        self.assertIsInstance(converted[2].parts[0], TextPart)

    def test_history_conversion_rejects_unknown_roles_and_non_text(self) -> None:
        with self.assertRaises(ConfigurationError):
            history_to_messages([{"role": "tool", "content": "no"}])
        with self.assertRaises(ConfigurationError):
            history_to_messages([{"role": "user", "content": {"not": "text"}}])

    def test_anthropic_provider_requires_env_key_and_preserves_custom_endpoint(self) -> None:
        profile = AgentProfile(
            provider="anthropic",
            model="MiniMax-M3-custom-id",
            api_key_env="MINIMAX_API_KEY",
            base_url="https://api.minimax.io/anthropic",
            permissions=AgentPermissions(filesystem="none"),
        )
        with self.assertRaises(ConfigurationError):
            build_model(profile, {})

        built = build_model(profile, {"MINIMAX_API_KEY": "test-only-key"})
        self.assertEqual(built.model.model_name, "MiniMax-M3-custom-id")
        self.assertEqual(
            str(built.model._provider.base_url).rstrip("/"),  # type: ignore[attr-defined]
            "https://api.minimax.io/anthropic",
        )


class WorkspaceTests(unittest.TestCase):
    def test_workspace_resolution_rejects_absolute_traversal_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(root_dir)
            (root / "inside").mkdir()
            (root / "escape").symlink_to(outside_dir, target_is_directory=True)

            self.assertEqual(resolve_workspace(root, Path("inside")), (root / "inside").resolve())
            for candidate in (Path(outside_dir), Path("../outside"), Path("escape")):
                with self.subTest(candidate=candidate), self.assertRaises(WorkspaceViolation):
                    resolve_workspace(root, candidate)

    def test_unknown_profile_and_tools_fail_before_model_execution(self) -> None:
        called = False

        async def model_function(_messages, _info):
            nonlocal called
            called = True
            return ModelResponse(parts=[TextPart("unexpected")])

        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            executor = make_executor(root, model_function, permissions="workspace-read")
            with self.assertRaises(ConfigurationError):
                executor.run(AgentRequest(history=[], task=None, workspace=Path("."), profile="missing"))
            with self.assertRaises(ConfigurationError):
                executor.run(
                    AgentRequest(
                        history=[],
                        task=None,
                        workspace=Path("."),
                        profile="test",
                        requested_tools=("write_file",),
                    )
                )
        self.assertFalse(called)


class ExecutionTests(unittest.TestCase):
    def test_no_tool_response_receives_history_task_and_safety_context_once(self) -> None:
        async def model_function(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            system_parts = parts(messages, SystemPromptPart)
            user_parts = parts(messages, UserPromptPart)
            self.assertEqual([part.content for part in system_parts], ["actor system"])
            self.assertEqual([part.content for part in user_parts], ["prior", "current task"])
            instructions = [
                message.instructions
                for message in messages
                if isinstance(message, ModelRequest) and message.instructions
            ]
            self.assertEqual(len(instructions), 1)
            return ModelResponse(parts=[TextPart("finished")])

        with tempfile.TemporaryDirectory() as root_dir:
            executor = make_executor(Path(root_dir), model_function, permissions="none")
            result = executor.run(
                AgentRequest(
                    history=[
                        {"role": "system", "content": "actor system"},
                        {"role": "user", "content": "prior"},
                    ],
                    task="current task",
                    workspace=Path("."),
                    profile="test",
                )
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "finished")
        self.assertEqual(result.changed_paths, ())
        self.assertEqual(result.usage["requests"], 1)

    def test_write_and_edit_report_normalized_trace_and_changed_path(self) -> None:
        async def model_function(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            returns = parts(messages, ToolReturnPart)
            self.assertEqual(
                {tool.name for tool in info.function_tools},
                {"write_file", "edit_file"},
            )
            if not returns:
                return ModelResponse(
                    parts=[ToolCallPart("write_file", {"path": "note.txt", "content": "first"}, "w1")]
                )
            if len(returns) == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "edit_file",
                            {"path": "note.txt", "old_text": "first", "new_text": "second"},
                            "e1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart("updated")])

        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            executor = make_executor(
                root,
                model_function,
                allowed_tools=("write_file", "edit_file"),
            )
            result = executor.run(
                AgentRequest(history=[], task="update", workspace=Path("."), profile="test")
            )
            content = (root / "note.txt").read_text()

        self.assertEqual(result.status, "completed")
        self.assertEqual(content, "second")
        self.assertEqual(result.changed_paths, ("note.txt",))
        self.assertEqual([event["type"] for event in result.events], [
            "tool_call", "tool_result", "tool_call", "tool_result"
        ])
        json.dumps(result.messages)

    def test_malformed_tool_args_are_returned_to_model_as_retry(self) -> None:
        async def model_function(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            if parts(messages, RetryPromptPart):
                return ModelResponse(parts=[TextPart("recovered")])
            return ModelResponse(parts=[ToolCallPart("read_file", {}, "bad")])

        with tempfile.TemporaryDirectory() as root_dir:
            executor = make_executor(Path(root_dir), model_function, permissions="workspace-read")
            result = executor.run(
                AgentRequest(history=[], task="read", workspace=Path("."), profile="test")
            )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.output, "recovered")
        self.assertIn("retry", [event["type"] for event in result.events])

    def test_absolute_tool_path_and_denied_env_file_are_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir, tempfile.NamedTemporaryFile(
            mode="w", delete=True
        ) as outside:
            outside.write("outside-secret")
            outside.flush()
            outside_file = outside.name
            root = Path(root_dir)
            (root / ".env").write_text("API_KEY=inside-secret")

            for requested_path, forbidden_content in (
                (outside_file, "outside-secret"),
                (".env", "inside-secret"),
            ):
                async def model_function(
                    messages: list[ModelMessage],
                    _info: AgentInfo,
                    path: str = requested_path,
                ) -> ModelResponse:
                    if parts(messages, RetryPromptPart):
                        return ModelResponse(parts=[TextPart("blocked")])
                    return ModelResponse(parts=[ToolCallPart("read_file", {"path": path}, "read")])

                executor = make_executor(root, model_function, permissions="workspace-read")
                result = executor.run(
                    AgentRequest(history=[], task="read secret", workspace=Path("."), profile="test")
                )
                transcript = json.dumps(result.messages)
                self.assertEqual(result.output, "blocked")
                self.assertNotIn(forbidden_content, transcript)
                self.assertEqual(
                    len([event for event in result.events if event["type"] == "retry"]),
                    1,
                )

    def test_symlinked_file_cannot_escape_workspace(self) -> None:
        async def model_function(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            if parts(messages, RetryPromptPart):
                return ModelResponse(parts=[TextPart("blocked")])
            return ModelResponse(parts=[ToolCallPart("read_file", {"path": "escape.txt"}, "read")])

        with tempfile.TemporaryDirectory() as root_dir, tempfile.NamedTemporaryFile(
            mode="w", delete=True
        ) as outside:
            outside.write("symlink-secret")
            outside.flush()
            root = Path(root_dir)
            (root / "escape.txt").symlink_to(outside.name)
            executor = make_executor(root, model_function, permissions="workspace-read")
            result = executor.run(
                AgentRequest(history=[], task="read link", workspace=Path("."), profile="test")
            )

        self.assertEqual(result.output, "blocked")
        self.assertNotIn("symlink-secret", json.dumps(result.messages))

    def test_tool_call_limit_returns_failed_result(self) -> None:
        counter = 0

        async def model_function(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            nonlocal counter
            counter += 1
            return ModelResponse(
                parts=[ToolCallPart("list_directory", {"path": "."}, f"call-{counter}")]
            )

        with tempfile.TemporaryDirectory() as root_dir:
            executor = make_executor(Path(root_dir), model_function, permissions="workspace-read")
            result = executor.run(
                AgentRequest(
                    history=[],
                    task="loop",
                    workspace=Path("."),
                    profile="test",
                    request_limit=3,
                    tool_call_limit=1,
                )
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.events[-1]["type"], "error")

    def test_provider_failure_and_output_are_redacted(self) -> None:
        secret = "super-secret-provider-token"

        async def failing_model(_messages, _info):
            raise RuntimeError(f"provider rejected API_KEY={secret}")

        with tempfile.TemporaryDirectory() as root_dir:
            executor = make_executor(
                Path(root_dir),
                failing_model,
                permissions="none",
                api_key_env="TEST_API_KEY",
                environ={"TEST_API_KEY": secret},
            )
            result = executor.run(
                AgentRequest(history=[], task="fail", workspace=Path("."), profile="test")
            )

        serialized = json.dumps(result.events)
        self.assertEqual(result.status, "failed")
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertTrue(result.messages)

    def test_failure_after_write_still_reports_changed_path(self) -> None:
        async def model_function(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            if parts(messages, ToolReturnPart):
                raise RuntimeError("provider disconnected after write")
            return ModelResponse(
                parts=[ToolCallPart("write_file", {"path": "partial.txt", "content": "saved"}, "write")]
            )

        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            executor = make_executor(root, model_function, allowed_tools=("write_file",))
            result = executor.run(
                AgentRequest(
                    history=[],
                    task="write then fail",
                    workspace=Path("."),
                    profile="test",
                )
            )
            self.assertEqual((root / "partial.txt").read_text(), "saved")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.changed_paths, ("partial.txt",))
        self.assertIn("tool_result", [event["type"] for event in result.events])

    def test_two_executors_keep_workspaces_isolated(self) -> None:
        def make_model(marker: str):
            async def model_function(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
                if not parts(messages, ToolReturnPart):
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                "write_file",
                                {"path": "marker.txt", "content": marker},
                                f"write-{marker}",
                            )
                        ]
                    )
                return ModelResponse(parts=[TextPart(marker)])

            return model_function

        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir)
            second = Path(second_dir)
            executors = (
                make_executor(first, make_model("first"), allowed_tools=("write_file",)),
                make_executor(second, make_model("second"), allowed_tools=("write_file",)),
            )
            request = AgentRequest(history=[], task="write", workspace=Path("."), profile="test")
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda executor: executor.run(request), executors))

            self.assertEqual((first / "marker.txt").read_text(), "first")
            self.assertEqual((second / "marker.txt").read_text(), "second")
            self.assertEqual([result.status for result in results], ["completed", "completed"])


if __name__ == "__main__":
    unittest.main()

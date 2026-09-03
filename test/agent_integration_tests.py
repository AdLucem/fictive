import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from agent_harness import AgentPermissions, AgentProfile, PydanticAgentExecutor
from fictive import (
    Actor,
    ActorConfig,
    AgentRunFailed,
    Interpreter,
    Store,
    load_scenario_config,
)
from fictive.parser.commands import AGENT, COND, parse_command_dict
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel


@dataclass(frozen=True)
class FakeAgentResult:
    output: str
    status: str = "completed"
    messages: list | None = None
    events: list | None = None
    usage: dict | None = None
    changed_paths: tuple[str, ...] = ()
    run_id: str = "test-run"

    def __post_init__(self):
        object.__setattr__(self, "messages", list(self.messages or []))
        object.__setattr__(self, "events", list(self.events or []))
        object.__setattr__(self, "usage", dict(self.usage or {}))


class RecordingExecutor:
    def __init__(self, workspace_root: Path, result: FakeAgentResult):
        self.workspace_root = workspace_root.resolve()
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


class RaisingExecutor(RecordingExecutor):
    def run(self, request):
        self.requests.append(request)
        raise ValueError(f"Unknown agent profile: {request.profile!r}")


def make_actor(storage_dir: Path, instructions, name="worker"):
    return Actor(
        ActorConfig(
            name=name,
            storage_dir=str(storage_dir),
            instructions=instructions,
        )
    )


class AgentCommandParsingTests(unittest.TestCase):
    def test_scenario_loader_keeps_agent_workspace_runtime_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenario = Path(tmp)
            (scenario / "workspace").mkdir()
            (scenario / "schema.json").write_text(
                json.dumps({"actors": ["worker"]}),
                encoding="utf-8",
            )
            (scenario / "worker.json").write_text(
                json.dumps(
                    [
                        {
                            "cmd": "agent",
                            "profile": "local",
                            "workspace": "workspace",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            _, actor_definitions, _ = load_scenario_config(str(scenario))

            self.assertEqual(
                actor_definitions["worker"][0]["workspace"],
                "workspace",
            )

    def test_agent_command_parses_all_fields_and_hyphenated_limits(self):
        command = parse_command_dict(
            {
                "cmd": "agent",
                "profile": "minimax-m3",
                "prompt": "Inspect this workspace",
                "workspace": ".chatlogs",
                "tools": ["read_file", "write_file"],
                "request-limit": 4,
                "tool-call-limit": 9,
                "store": "answer",
                "trace-store": "trace",
            }
        )

        self.assertIsInstance(command, AGENT)
        self.assertEqual(command.profile, "minimax-m3")
        self.assertEqual(command.workspace, ".chatlogs")
        self.assertEqual(command.request_limit, 4)
        self.assertEqual(command.tool_call_limit, 9)
        self.assertEqual(command.trace_store, "trace")

    def test_agent_command_parses_inside_cond_block(self):
        command = parse_command_dict(
            {
                "cmd": "cond",
                "conditions": [
                    {
                        "condition": "True",
                        "commands": [{"cmd": "agent", "profile": "local"}],
                    }
                ],
            }
        )

        self.assertIsInstance(command, COND)
        self.assertIsInstance(command.conditions[0]["commands"][0], AGENT)


class AgentInterpreterTests(unittest.TestCase):
    def test_fictive_request_runs_through_standalone_executor(self):
        async def model_function(_messages, _info):
            return ModelResponse(parts=[TextPart("Standalone harness completed.")])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actor = make_actor(
                root,
                [{"cmd": "agent", "profile": "test", "store": "answer"}],
            )
            executor = PydanticAgentExecutor(
                profiles={
                    "test": AgentProfile(
                        provider="fake",
                        model="deterministic",
                        permissions=AgentPermissions(filesystem="none"),
                    )
                },
                workspace_root=root,
                model_builders={
                    "fake": lambda _profile, _environ: FunctionModel(
                        model_function,
                        model_name="deterministic",
                    )
                },
                environ={},
            )
            store = Store()
            interpreter = Interpreter(
                [actor],
                store=store,
                agent_executor=executor,
                agent_root=root,
            )

            self.assertEqual(interpreter.exec_current(), -1)
            self.assertEqual(store.get("answer"), "Standalone harness completed.")
            self.assertEqual(
                actor.history.read(merged=False),
                [{"role": "assistant", "content": "Standalone harness completed."}],
            )

    def test_agent_only_actor_does_not_require_generation_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            actor = make_actor(
                Path(tmp),
                [{"cmd": "agent", "profile": "local"}],
            )

            self.assertIsNone(actor.pipeline)
            with self.assertRaisesRegex(RuntimeError, "no pipeline is configured"):
                actor.generate()

    def test_success_passes_history_and_stores_output_and_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / ".chatlogs"
            workspace.mkdir()
            actor = make_actor(
                root,
                [
                    {
                        "cmd": "agent",
                        "profile": "minimax-m3",
                        "prompt": "var:task",
                        "workspace": ".chatlogs",
                        "tools": ["read_file", "write_file"],
                        "request-limit": 3,
                        "tool-call-limit": 7,
                        "store": "answer",
                        "trace-store": "trace",
                    }
                ],
            )
            original_history = [
                {"role": "system", "content": "Work carefully."},
                {"role": "user", "content": "Review the notes."},
            ]
            actor.history.add(original_history)
            store = Store()
            store.set("task", "Summarize what you find.")
            result = FakeAgentResult(
                output="The notes are consistent.",
                messages=[
                    {"kind": "request", "parts": [{"type": "tool_call"}]},
                    {"kind": "response", "parts": [{"type": "text"}]},
                ],
                events=[{"type": "tool_call", "tool_name": "read_file"}],
                usage={"requests": 2, "tool_calls": 1},
                changed_paths=("summary.txt",),
            )
            executor = RecordingExecutor(root, result)
            interpreter = Interpreter(
                [actor],
                store=store,
                agent_executor=executor,
                agent_root=root,
            )

            self.assertEqual(interpreter.exec_current(), -1)

            self.assertEqual(len(executor.requests), 1)
            request = executor.requests[0]
            self.assertEqual(request.history, original_history)
            self.assertEqual(request.task, "Summarize what you find.")
            self.assertEqual(request.workspace, Path(".chatlogs"))
            self.assertEqual(request.profile, "minimax-m3")
            self.assertEqual(request.requested_tools, ("read_file", "write_file"))
            self.assertEqual(request.request_limit, 3)
            self.assertEqual(request.tool_call_limit, 7)

            final_history = actor.history.read(merged=False)
            self.assertEqual(
                final_history,
                original_history
                + [{"role": "assistant", "content": "The notes are consistent."}],
            )
            self.assertEqual(request.history, original_history)
            self.assertNotIn("tool_call", str(final_history))
            self.assertEqual(store.get("answer"), "The notes are consistent.")
            self.assertEqual(
                store.get("trace"),
                {
                    "run_id": "test-run",
                    "status": "completed",
                    "messages": result.messages,
                    "events": result.events,
                    "usage": result.usage,
                    "changed_paths": ["summary.txt"],
                },
            )
            self.assertEqual(actor.cur_step, 0)
            self.assertEqual(interpreter.callstack, [])

    def test_missing_executor_preserves_step_callstack_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            actor = make_actor(
                Path(tmp),
                [{"cmd": "agent", "profile": "local"}],
            )
            actor.history.add({"role": "user", "content": "Do the work."})
            interpreter = Interpreter([actor])

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, "configure both agent_executor"):
                    interpreter.exec_current()

            self.assertEqual(actor.cur_step, 0)
            self.assertEqual(interpreter.callstack, ["worker"])
            self.assertEqual(
                actor.history.read(merged=False),
                [{"role": "user", "content": "Do the work."}],
            )

    def test_failed_result_preserves_trace_without_advancing_or_appending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actor = make_actor(
                root,
                [
                    {
                        "cmd": "agent",
                        "profile": "local",
                        "store": "answer",
                        "trace-store": "trace",
                    }
                ],
            )
            actor.history.add({"role": "user", "content": "Edit the file."})
            result = FakeAgentResult(
                output="",
                status="failed",
                events=[{"type": "error", "message": "provider unavailable"}],
                usage={"requests": 1},
                changed_paths=("partially-written.txt",),
                run_id="failed-run",
            )
            executor = RecordingExecutor(root, result)
            store = Store()
            interpreter = Interpreter(
                [actor],
                store=store,
                agent_executor=executor,
                agent_root=root,
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(AgentRunFailed) as raised:
                    interpreter.exec_current()

            self.assertIs(raised.exception.result, result)
            self.assertEqual(store.get("trace")["status"], "failed")
            self.assertEqual(
                store.get("trace")["changed_paths"], ["partially-written.txt"]
            )
            self.assertIsNone(store.get("answer"))
            self.assertEqual(
                actor.history.read(merged=False),
                [{"role": "user", "content": "Edit the file."}],
            )
            self.assertEqual(actor.cur_step, 0)
            self.assertEqual(interpreter.callstack, ["worker"])

    def test_executor_exception_for_invalid_profile_preserves_interpreter_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actor = make_actor(
                root,
                [{"cmd": "agent", "profile": "missing"}],
            )
            executor = RaisingExecutor(root, FakeAgentResult(output="unused"))
            interpreter = Interpreter(
                [actor],
                agent_executor=executor,
                agent_root=root,
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "Unknown agent profile"):
                    interpreter.exec_current()

            self.assertEqual(len(executor.requests), 1)
            self.assertEqual(actor.cur_step, 0)
            self.assertEqual(interpreter.callstack, ["worker"])

    def test_workspace_escape_is_rejected_before_executor_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actor = make_actor(
                root,
                [{"cmd": "agent", "profile": "local", "workspace": ".."}],
            )
            executor = RecordingExecutor(root, FakeAgentResult(output="unused"))
            interpreter = Interpreter(
                [actor],
                agent_executor=executor,
                agent_root=root,
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "outside"):
                    interpreter.exec_current()

            self.assertEqual(executor.requests, [])
            self.assertEqual(actor.cur_step, 0)
            self.assertEqual(interpreter.callstack, ["worker"])

    def test_absolute_workspace_is_rejected_before_executor_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            actor = make_actor(
                root,
                [{"cmd": "agent", "profile": "local", "workspace": str(root)}],
            )
            executor = RecordingExecutor(root, FakeAgentResult(output="unused"))
            interpreter = Interpreter(
                [actor],
                agent_executor=executor,
                agent_root=root,
            )

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "must be relative"):
                    interpreter.exec_current()

            self.assertEqual(executor.requests, [])

    def test_interpreter_rejects_executor_with_different_workspace_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            configured_root = parent / "configured"
            executor_root = parent / "executor"
            configured_root.mkdir()
            executor_root.mkdir()
            actor = make_actor(
                configured_root,
                [{"cmd": "agent", "profile": "local"}],
            )
            executor = RecordingExecutor(executor_root, FakeAgentResult(output="unused"))

            with self.assertRaisesRegex(ValueError, "must match"):
                Interpreter(
                    [actor],
                    agent_executor=executor,
                    agent_root=configured_root,
                )

    def test_run_actor_unwinds_after_agent_success_and_fills_waiting_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caller = make_actor(
                root,
                [{"cmd": "run-actor", "actor-name": "worker", "store": "delegated"}],
                name="caller",
            )
            worker = make_actor(
                root,
                [{"cmd": "agent", "profile": "local"}],
            )
            executor = RecordingExecutor(
                root, FakeAgentResult(output="Agent task finished.")
            )
            store = Store()
            interpreter = Interpreter(
                [caller, worker],
                main_actor_name="caller",
                store=store,
                agent_executor=executor,
                agent_root=root,
            )

            next_actor = interpreter.exec_current()
            self.assertEqual(next_actor.name, "worker")
            self.assertEqual(interpreter.callstack, ["caller", "worker"])

            returned_actor = interpreter.exec_current()
            self.assertEqual(returned_actor.name, "caller")
            self.assertEqual(interpreter.callstack, ["caller"])
            self.assertEqual(store.get("delegated"), "Agent task finished.")
            self.assertNotIn("delegated", interpreter.waiting_store)

    def test_run_actor_keeps_callee_on_stack_after_agent_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            caller = make_actor(
                root,
                [{"cmd": "run-actor", "actor-name": "worker", "store": "delegated"}],
                name="caller",
            )
            worker = make_actor(
                root,
                [
                    {
                        "cmd": "agent",
                        "profile": "local",
                        "trace-store": "failed-trace",
                    }
                ],
            )
            executor = RecordingExecutor(
                root,
                FakeAgentResult(output="", status="failed", run_id="nested-failure"),
            )
            store = Store()
            interpreter = Interpreter(
                [caller, worker],
                main_actor_name="caller",
                store=store,
                agent_executor=executor,
                agent_root=root,
            )

            interpreter.exec_current()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(AgentRunFailed):
                    interpreter.exec_current()

            self.assertEqual(interpreter.callstack, ["caller", "worker"])
            self.assertEqual(worker.cur_step, 0)
            self.assertEqual(interpreter.waiting_store, {"delegated": "worker"})
            self.assertIsNone(store.get("delegated"))
            self.assertEqual(store.get("failed-trace")["run_id"], "nested-failure")


if __name__ == "__main__":
    unittest.main()

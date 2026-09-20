import tempfile
import unittest
from pathlib import Path

from fictive import Actor, ActorConfig, Interpreter, Runtime, Store


class EchoPipeline:
    """Deterministic pipeline that reports the last message it was given."""

    def __init__(self, reply="pipeline reply"):
        self.reply = reply
        self.calls = []

    def generate(self, messages):
        self.calls.append(list(messages))
        return {"role": "assistant", "content": self.reply}


def build_actor(name, storage_dir, pipeline=None, **extra):
    return Actor(
        ActorConfig(
            name=name,
            storage_dir=str(storage_dir),
            pipeline=pipeline,
            **extra,
        )
    )


class LibraryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_actor_without_instructions_starts_empty(self):
        """A library-runtime actor is declared with no instruction list."""

        actor = build_actor("solo", self.storage_dir)
        self.assertEqual(actor.instructions, [])

    def test_cmd_exec_runs_commands_in_python_order(self):
        pipeline = EchoPipeline("generated line")
        actor = build_actor("writer", self.storage_dir, pipeline=pipeline)
        interpreter = Interpreter([actor], main_actor_name="writer")
        runtime = Runtime(interpreter, start_actor_name="writer")

        runtime.cmd_exec("system", prompt="You are the writer.")
        runtime.cmd_exec("generate", prompt="Write one line.")
        runtime.cmd_exec("assign", var_name="greeting", value="hello")
        runtime.cmd_exec("write", path="out.txt", overwrite=True)

        self.assertEqual(interpreter.store_fetch("greeting"), "hello")
        self.assertEqual(
            (self.storage_dir / "out.txt").read_text(encoding="utf-8"),
            "generated line",
        )
        self.assertEqual(
            [message["role"] for message in actor.history.read()],
            ["system", "user", "assistant"],
        )

    def test_cmd_exec_returns_interpreter_and_working_actor(self):
        actor = build_actor("solo", self.storage_dir)
        interpreter = Interpreter([actor], main_actor_name="solo")
        runtime = Runtime(interpreter, start_actor_name="solo")

        returned_interpreter, acting_actor_name = runtime.cmd_exec(
            "assign", var_name="x", value="1"
        )

        self.assertIs(returned_interpreter, interpreter)
        self.assertEqual(acting_actor_name, "solo")

    def test_run_actor_then_exit_fills_store_and_unwinds(self):
        """`run-actor`/`exit` move control between actors in a library flow."""

        caller = build_actor("caller", self.storage_dir, pipeline=EchoPipeline("caller"))
        callee = build_actor("callee", self.storage_dir, pipeline=EchoPipeline("callee answer"))
        interpreter = Interpreter([caller, callee], main_actor_name="caller")
        runtime = Runtime(interpreter, start_actor_name="caller")

        runtime.cmd_exec("run-actor", actor_name="callee", store="answer")
        self.assertEqual(runtime.working_actor.name, "callee")
        self.assertEqual(interpreter.callstack, ["caller", "callee"])

        runtime.cmd_exec("generate", prompt="Answer the question.")
        runtime.cmd_exec("exit")

        self.assertEqual(runtime.working_actor.name, "caller")
        self.assertEqual(interpreter.callstack, ["caller"])
        self.assertEqual(interpreter.store_fetch("answer"), "callee answer")
        self.assertFalse(runtime.exit_requested)

    def test_exit_from_the_starting_actor_requests_exit(self):
        actor = build_actor("solo", self.storage_dir)
        interpreter = Interpreter([actor], main_actor_name="solo")
        runtime = Runtime(interpreter, start_actor_name="solo")

        runtime.cmd_exec("exit")

        self.assertEqual(interpreter.callstack, [])
        self.assertTrue(runtime.exit_requested)

    def test_input_from_store_is_shared_between_actors(self):
        reader = build_actor("reader", self.storage_dir, pipeline=EchoPipeline())
        interpreter = Interpreter([reader], main_actor_name="reader", store=Store())
        runtime = Runtime(interpreter, start_actor_name="reader")

        runtime.cmd_exec("assign", var_name="intent", value="be curious")
        runtime.cmd_exec(
            "input-from",
            input_from_store="intent",
            enclosing_prompt="(INSTRUCTIONS: {INPUT_FROM})",
            store="full-instr",
        )

        self.assertEqual(
            interpreter.store_fetch("full-instr"),
            "(INSTRUCTIONS: be curious)",
        )

    def test_debug_helpers_tolerate_actors_without_instructions(self):
        actor = build_actor("solo", self.storage_dir)
        interpreter = Interpreter([actor], main_actor_name="solo")
        runtime = Runtime(interpreter, start_actor_name="solo")

        self.assertIs(runtime.main_actor, actor)
        self.assertIn("solo", runtime.format_actor_summary())
        self.assertEqual(
            runtime.handle_command("instr"),
            ["<driven by the library runtime>"],
        )

    def test_instructions_still_load_for_the_json_runtime(self):
        """The empty-instruction default must not shadow a JSON definition."""

        actor = build_actor(
            "scripted",
            self.storage_dir,
            instructions=[{"cmd": "assign", "name": "x", "value": "1"}],
        )

        self.assertEqual(len(actor.instructions), 1)
        self.assertEqual(actor.instructions[0].name, "assign")


if __name__ == "__main__":
    unittest.main()

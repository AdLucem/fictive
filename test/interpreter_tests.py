import contextlib
import io
import json
import os
import tempfile
import unittest

from fictive import ActorConfig, Interpreter
from fictive.actors import Actor


class DummyPipeline:
    def generate(self, messages):
        raise AssertionError("This test should not hit the LLM pipeline.")


def make_actor(name, instructions):
    return Actor(
        ActorConfig(
            name=name,
            storage_dir=None,
            instructions=instructions,
            pipeline=DummyPipeline(),
        )
    )


class CondCommandTests(unittest.TestCase):
    def test_cond_parses_nested_commands(self):
        actor = make_actor(
            "tester",
            [
                {
                    "cmd": "cond",
                    "conditions": [
                        {
                            "condition": "True",
                            "commands": [
                                {"cmd": "assign", "name": "answer", "value": "yes"}
                            ],
                        }
                    ],
                }
            ],
        )

        cond_cmd = actor.instructions[0]
        self.assertEqual(cond_cmd.name, "cond")
        self.assertEqual(cond_cmd.conditions[0]["commands"][0].name, "assign")

    def test_cond_executes_matching_branch_commands(self):
        actor = make_actor(
            "tester",
            [
                {"cmd": "assign", "name": "fear", "value": 4},
                {
                    "cmd": "cond",
                    "conditions": [
                        {
                            "condition": "fear > 2",
                            "commands": [
                                {"cmd": "assign", "name": "mood", "value": "high"},
                                {"cmd": "print", "prompt": "var:mood"},
                            ],
                        },
                        {
                            "condition": "else",
                            "commands": [
                                {"cmd": "assign", "name": "mood", "value": "low"}
                            ],
                        },
                    ],
                },
            ],
        )
        interpreter = Interpreter([actor], main_actor_name="tester")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(interpreter.exec_current().name, "tester")
            self.assertEqual(interpreter.exec_current().name, "tester")
            self.assertEqual(interpreter.exec_current().name, "tester")
            self.assertEqual(interpreter.exec_current(), -1)

        self.assertEqual(interpreter.store.get("mood"), "high")
        self.assertIn("high", stdout.getvalue())

    def test_cond_falls_back_to_else_branch(self):
        actor = make_actor(
            "tester",
            [
                {"cmd": "assign", "name": "fear", "value": 1},
                {
                    "cmd": "cond",
                    "conditions": [
                        {
                            "condition": "fear > 2",
                            "commands": [
                                {"cmd": "assign", "name": "mood", "value": "high"}
                            ],
                        },
                        {
                            "condition": "else",
                            "commands": [
                                {"cmd": "assign", "name": "mood", "value": "low"}
                            ],
                        },
                    ],
                },
            ],
        )
        interpreter = Interpreter([actor], main_actor_name="tester")

        self.assertEqual(interpreter.exec_current().name, "tester")
        self.assertEqual(interpreter.exec_current().name, "tester")
        self.assertEqual(interpreter.exec_current(), -1)

        self.assertEqual(interpreter.store.get("mood"), "low")


class WriteCommandTests(unittest.TestCase):
    def test_write_command_writes_latest_output_relative_to_storage_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            actor = make_actor(
                "writer",
                [{"cmd": "write", "path": "outputs/latest.txt"}],
            )
            actor.storage_dir = tmpdir
            actor.history.add({"role": "assistant", "content": "final answer"})

            interpreter = Interpreter([actor], main_actor_name="writer")
            self.assertEqual(interpreter.exec_current(), -1)

            with open(os.path.join(tmpdir, "outputs", "latest.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "final answer")

    def test_write_command_appends_by_default_and_overwrites_when_requested(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "outputs", "latest.txt")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("existing")

            append_actor = make_actor(
                "append-writer",
                [{"cmd": "write", "path": "outputs/latest.txt"}],
            )
            append_actor.storage_dir = tmpdir
            append_actor.history.add({"role": "assistant", "content": " plus more"})

            append_interpreter = Interpreter([append_actor], main_actor_name="append-writer")
            self.assertEqual(append_interpreter.exec_current(), -1)

            with open(output_path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "existing plus more")

            overwrite_actor = make_actor(
                "overwrite-writer",
                [{"cmd": "write", "path": "outputs/latest.txt", "overwrite": True}],
            )
            overwrite_actor.storage_dir = tmpdir
            overwrite_actor.history.add({"role": "assistant", "content": "replacement"})

            overwrite_interpreter = Interpreter([overwrite_actor], main_actor_name="overwrite-writer")
            self.assertEqual(overwrite_interpreter.exec_current(), -1)

            with open(output_path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "replacement")

    def test_write_command_supports_read_from_and_write_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "source.txt")
            with open(source_path, "w", encoding="utf-8") as f:
                f.write("file contents")

            writer = make_actor(
                "writer",
                [
                    {"cmd": "write", "path": "copied.txt", "read_from": "source.txt"},
                    {"cmd": "write", "path": "history.json", "write_history": "writer"},
                ],
            )
            writer.storage_dir = tmpdir
            writer.history.add({"role": "assistant", "content": "history entry"})

            interpreter = Interpreter([writer], main_actor_name="writer")
            self.assertEqual(interpreter.exec_current().name, "writer")
            self.assertEqual(interpreter.exec_current(), -1)

            with open(os.path.join(tmpdir, "copied.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read(), "file contents")
            with open(os.path.join(tmpdir, "history.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f), [{"role": "assistant", "content": "history entry"}])


class InputFromCommandTests(unittest.TestCase):
    def test_input_from_file_reads_relative_to_storage_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "teacher_input.txt")
            with open(input_path, "w", encoding="utf-8") as f:
                f.write("lesson notes")

            actor = make_actor(
                "reader",
                [{"cmd": "input-from", "input_from_file": "teacher_input.txt", "store": "notes"}],
            )
            actor.storage_dir = tmpdir

            interpreter = Interpreter([actor], main_actor_name="reader")
            self.assertEqual(interpreter.exec_current(), -1)
            self.assertEqual(interpreter.store.get("notes"), "lesson notes")


class ExitCommandTests(unittest.TestCase):
    def test_exit_returns_control_to_previous_actor(self):
        caller = make_actor(
            "caller",
            [
                {"cmd": "run-actor", "actor_name": "callee", "store": "callee_output"},
                {"cmd": "assign", "name": "caller_state", "value": "resumed"},
            ],
        )
        callee = make_actor(
            "callee",
            [
                {"cmd": "exit"},
                {"cmd": "assign", "name": "should_not_run", "value": "no"},
            ],
        )
        callee.history.add({"role": "assistant", "content": "done"})

        interpreter = Interpreter([caller, callee], main_actor_name="caller")

        self.assertEqual(interpreter.exec_current().name, "callee")
        self.assertEqual(interpreter.exec_current().name, "caller")
        self.assertEqual(interpreter.exec_current(), -1)

        self.assertEqual(interpreter.store.get("callee_output"), "done")
        self.assertEqual(interpreter.store.get("caller_state"), "resumed")
        self.assertIsNone(interpreter.store.get("should_not_run"))

    def test_exit_from_cond_pending_block_discards_remaining_callee_work(self):
        caller = make_actor(
            "caller",
            [
                {"cmd": "run-actor", "actor_name": "callee"},
                {"cmd": "assign", "name": "caller_state", "value": "resumed"},
            ],
        )
        callee = make_actor(
            "callee",
            [
                {
                    "cmd": "cond",
                    "conditions": [
                        {
                            "condition": "True",
                            "commands": [
                                {"cmd": "assign", "name": "before_exit", "value": "yes"},
                                {"cmd": "exit"},
                                {"cmd": "assign", "name": "after_exit", "value": "no"},
                            ],
                        }
                    ],
                },
                {"cmd": "assign", "name": "post_cond", "value": "no"},
            ],
        )

        interpreter = Interpreter([caller, callee], main_actor_name="caller")

        self.assertEqual(interpreter.exec_current().name, "callee")
        self.assertEqual(interpreter.exec_current().name, "callee")
        self.assertEqual(interpreter.exec_current().name, "callee")
        self.assertEqual(interpreter.exec_current().name, "caller")
        self.assertEqual(interpreter.exec_current(), -1)

        self.assertEqual(interpreter.store.get("before_exit"), "yes")
        self.assertEqual(interpreter.store.get("caller_state"), "resumed")
        self.assertIsNone(interpreter.store.get("after_exit"))
        self.assertIsNone(interpreter.store.get("post_cond"))

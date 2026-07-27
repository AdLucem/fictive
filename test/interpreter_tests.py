import contextlib
import io
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

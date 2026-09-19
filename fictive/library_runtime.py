"""Provide a separate `runtime` environment and methods for people who want to import `fictive` in a python script and use the interpreter commands directly."""

import argparse
from copy import deepcopy
import json 
try:
    import transformers
except ImportError:  # optional: only used to quiet its own logger
    transformers = None
import traceback
from typing import Literal, Callable

from llm_utils import pipeline_config_from_args, pipeline_from_config
from .parser.commands import Cmd, CommandObj
from .parse_scenario_config import load_scenario_config
from .actors import ActorConfig, Actor
from .debugger import DebuggerSession
from .interpreter import Interpreter
from .data_structures import Store

try:  # transformers is optional; imported only to quiet its logger
    import transformers

    transformers.logging.set_verbosity_error()
except ImportError:  # pragma: no cover - depends on optional dependency
    pass


HELP_TEXT = "\n".join(
        [
            "Debugger commands:",
            "  n / next            Execute the current interpreter step",
            "  h / help            Show this help message",
            "  q / quit            Exit the debugger",
            "  s / state           Show the full interpreter state",
            "  store               Show the full store",
            "  store <key>         Show one store value",
            "  actors              List actor names and current steps",
            "  a / actor           Show the main actor state",
            "  actor <name>        Show another actor state",
            "  hist [name]         Show unmerged history for an actor",
            "  latest [name] [n]   Show the nth latest assistant output (default n=0)",
            "  instr [name]        Show the current instruction for an actor",
        ]
    )

class Runtime:

    def __init__(self, interpreter: Interpreter, start_actor_name: str, mode: Literal["debug", "chat", "single-actor"] = "chat"):

        self.HELP_TEXT = HELP_TEXT
        
        self.interpreter = interpreter
        self.start_actor_name = start_actor_name
        # The debug commands below talk about a "main" actor; for a library
        # flow that is the actor the runtime started on.
        self.main_actor_name = start_actor_name
        self.working_actor = interpreter.actor_fetch(start_actor_name)
        self.mode = mode

        self.exit_requested = False

    @property
    def main_actor(self) -> Actor:
        return self.interpreter.actor_fetch(self.main_actor_name)

    def cmd_exec(self, command: str, **kwargs):

        cmd = Cmd(command).map_to_dataclass()(**kwargs)

        if self.mode == "debug":
            exit_message = self.get_exit_message()
            if exit_message is not None:
                print(exit_message)

            print(self.format_step(cmd))
            raw_command = input("debug> ")
            outputs = self.handle_command(raw_command)

            for output in outputs:
                print(output)

        self.working_actor = self.interpreter.exec(
                cmd=cmd,
                actor_name=self.working_actor.name
        )

        if cmd.name == "exit":
            # `Interpreter.exec_current` unwinds the callstack after an `exit`
            # rather than leaving it to `exec`. A library flow never goes
            # through `exec_current`, so do the same unwinding here: it pops
            # the actor a previous `run-actor` pushed and fills that command's
            # `store` variable with the finished actor's last output.
            self.unwind_working_actor()

        acting_actor_name = self.working_actor.name
        return self.interpreter, acting_actor_name

    def unwind_working_actor(self) -> Actor:
        """Return control from the working actor to the one that called it.

        Mirrors the unwinding half of `Interpreter.exec_current`. When the
        callstack empties, the finished actor stays as the working actor and
        `exit_requested` is set, so a driving loop can tell that the flow is
        over.
        """
        finished_actor = self.working_actor
        finished_actor.clear_pending_instructions()
        finished_actor.return_after_pending = False
        self.interpreter.unwind_actor(finished_actor.name)

        if self.interpreter.callstack:
            self.working_actor = self.interpreter.actor_fetch(
                self.interpreter.callstack[-1]
            )
        else:
            self.exit_requested = True

        return self.working_actor

    def handle_command(self, raw_command: str) -> list[str]:
        raw_command = raw_command.strip()
        if raw_command == "":
            return []

        parts = raw_command.split()
        command = parts[0].lower()

        try:
            if command in {"n", "next"}:
                return []
            if command in {"h", "help"}:
                return [self.HELP_TEXT]
            if command in {"q", "quit"}:
                self.exit_requested = True
                return []
            if command in {"s", "state"}:
                return [str(self.interpreter)]
            if command == "store":
                if len(parts) == 1:
                    return [str(self.interpreter.store)]
                key = " ".join(parts[1:])
                return [str(self.interpreter.store_fetch(key))]
            if command == "actors":
                return [self.format_actor_summary()]
            if command in {"a", "actor"} and len(parts) == 1:
                return [str(self.actor_or_main(None))]
            if command == "actor" and len(parts) >= 2:
                return [str(self.interpreter.actor_fetch(" ".join(parts[1:])))]
            if command == "hist":
                actor_name = parts[1] if len(parts) >= 2 else self.main_actor_name
                return [self.format_history(actor_name)]
            if command == "latest":
                actor_name = self.working_actor.name
                n = 0
                if len(parts) >= 2:
                    try:
                        n = int(parts[1])
                    except ValueError:
                        actor_name = parts[1]
                if len(parts) >= 3:
                    n = int(parts[2])
                return [self.format_latest(actor_name, n)]
            if command == "instr":
                actor = self.actor_or_main(parts[1] if len(parts) >= 2 else None)
                return [self.describe_current_instr(actor)]

            return [f"Unknown command: {raw_command}", self.HELP_TEXT]
        except Exception:
            return [traceback.format_exc().rstrip()]

    def run_debug(self,
                  
                  input_fn: Callable[[str], str] = input,
                  output_fn: Callable[[str], None] = print,
    ) -> None:
        output_fn(self.HELP_TEXT)

        while True:
            exit_message = self.get_exit_message()
            if exit_message is not None:
                output_fn(exit_message)
                break

            output_fn(self.format_current_step())
            raw_command = input_fn("debug> ")
            outputs = self.handle_command(raw_command)

            for output in outputs:
                output_fn(output)

            if self.exit_requested:
                break

    def actor_or_main(self, actor_name: str | None) -> Actor:
        return self.interpreter.actor_fetch(actor_name or self.main_actor_name)

    def get_exit_message(self) -> str | None:
        if not isinstance(self.working_actor, int):
            return None

        if self.working_actor == 0:
            return (
                f"{self.main_actor_name} is at its last instruction step "
                f"({self.main_actor.cur_step}). Stopping debug run."
            )

        if self.working_actor < 0:
            return (
                f"{self.main_actor_name} exited abnormally at "
                f"({self.main_actor.cur_step}) with exit code "
                f"{self.working_actor}. Stopping debug run."
            )

        return None

    def format_step(self, cmd: type[CommandObj]) -> str:
        return (
            f"\n[{self.working_actor.name} next instruction {cmd} \n Callstack: {self.interpreter.callstack}"
        )

    def format_actor_summary(self) -> str:
        lines = []
        for name, actor in self.interpreter.actors.items():
            current_instr = self.describe_current_instr(actor)
            lines.append(f"{name}: step={actor.cur_step} current_instr={current_instr}")
        return "\n".join(lines)

    @staticmethod
    def describe_current_instr(actor: Actor) -> str:
        """Describe an actor's current instruction, tolerating library actors.

        An actor driven by `cmd_exec` has no instruction list of its own, so
        asking it for a current instruction is not an error -- there simply
        isn't one.
        """
        if (not actor.instructions) and (not actor.has_pending_instruction()):
            return "<driven by the library runtime>"
        return str(actor.get_current_instr())

    def format_history(self, actor_name: str) -> str:
        actor = self.interpreter.actor_fetch(actor_name)
        history = actor.history.read()
        if not history:
            return f"{actor_name} history is empty."
        return json.dumps(history, indent=2)

    def format_latest(self, actor_name: str, n: int) -> str:
        latest_output = self.interpreter.actor_fetch(actor_name).get_latest_output(n)
        if isinstance(latest_output, dict):
            return json.dumps(latest_output, indent=2)
        return str(latest_output)

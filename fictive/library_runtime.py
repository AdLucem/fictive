"""Library mode: drive the interpreter from Python instead of a JSON scenario.

The scenario format (`<scenario>/<actor>.json`) describes an actor's behaviour
as a list of instruction dicts that `Interpreter.exec_current` walks one step at
a time, using `cond`/`loop` instructions for control flow.

This module supports the other style `fictive` offers: import the library and
call interpreter commands directly from Python, letting Python's own `if`,
`while`, function calls and local variables provide the control flow. `Runtime`
is the entry point -- a typed facade where every method is one interpreter
command executed against whichever actor currently holds control.

Scenarios written this way are *generators*. Every point where the scenario
needs a human answer is an explicit `yield` of an `InputRequest`, and the answer
arrives back through `generator.send(...)`. That keeps a flow suspendable at
exactly the boundaries the instruction pointer used to mark, so the same flow
can be driven by a blocking terminal loop (`drive_flow`) or by a host that
resumes it once per HTTP request, without `input()` ever being monkey-patched.

    def greet(rt):
        rt.system("You are a helpful tutor.")
        name = yield from ask(rt, "Your name?", store="student")
        rt.generate(f"Greet {name}.", visible=True)

    drive_flow(greet(Runtime(interpreter, "tutor")))

`Runtime` also carries the debugger for this mode: construct it with
`mode="debug"` and every command stops at a `debug> ` prompt before it runs.
"""

from __future__ import annotations

import inspect
import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Generator, Literal, Optional

from .parser.commands import Cmd, CommandObj
from .actors import Actor
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
        "  n / next / <enter>  Execute the step shown above",
        "  h / help            Show this help message",
        "  q / quit            Stop the debug run",
        "  s / state           Show the store, callstack, and actor summary",
        "  store               Show the full store",
        "  store <key>         Show one store value",
        "  actors              List actors with position and message counts",
        "  a / actor           Show the main actor state",
        "  actor <name>        Show another actor state",
        "  hist [name]         Show unmerged history for an actor",
        "  latest [name] [n]   Show the nth latest assistant output (default n=0)",
        "  instr [name]        Show the step about to execute",
        "  trace [n]           Show the last n commands executed (default 20)",
        "",
        "Inspection commands do not advance execution; only `n` does.",
    ]
)


class DebugQuit(Exception):
    """Raised when a debug run is asked to quit.

    Commands are issued by ordinary Python code, so there is no instruction
    pointer to stop advancing. Raising unwinds the scenario -- generator
    `finally` blocks included -- and returns control to whoever called it.
    """


class CommandRestart(Exception):
    """Raised by a command handler to restart the current flow.
    
    The flow driver should catch this and restart the scenario generator
    with the newly loaded runtime state.
    """


class CommandExit(Exception):
    """Raised by a command handler to exit the current flow.
    
    The flow driver should catch this and exit the scenario.
    """


@dataclass
class InputRequest:
    """One suspension point: the scenario needs a human answer before it continues.

    Mirrors the fields an `input-from` instruction with a `human-prompt` carries,
    so `Runtime.deliver` can apply the answer exactly the way
    `Interpreter.exec_INPUT_FROM` does.
    """

    actor_name: str
    prompt: str
    store: Optional[str] = None
    history: bool = True
    enclosing_prompt: Optional[str] = None

    # Whether `prompt` is real conversational content -- a question or
    # instruction the human needs to see -- as opposed to a bare "type your next
    # message" cue that exists only because a CLI has to print something before
    # calling `input()`. A console-style UI supplies its own prompting
    # affordance (an input box, a placeholder, a Run button) and must not render
    # a `content=False` prompt as though the AI said it; a terminal driver
    # (`drive_flow`) shows it regardless, since for a CLI that text *is* the
    # prompt.
    content: bool = True


# A flow is a generator that yields InputRequests and receives answers.
Flow = Generator[InputRequest, str, Any]


# A session file holds actor histories, the store and the callstack -- not a
# flow's position, which lives in a Python generator. So a host that resumes a
# saved session has to start a flow again, and sets this store variable first so
# a flow can tell a resume from a fresh start and skip its own prologue.
RESUMED_STORE_KEY = "_fictive_resumed"


class Runtime:
    """Execute interpreter commands from Python, one call at a time.

    Holds the working actor -- the one commands are executed against -- and
    moves it across the interpreter's callstack as `enter_actor`/`return_from`
    are called. Beyond that the only state it adds is bookkeeping a host needs:
    `visible_generate` and `last_visible` mark the one generation a user is
    meant to be shown, and `trace` records every command for debugging and for
    offline tests that assert on a scenario's command sequence without running a
    model.
    """

    HELP_TEXT = HELP_TEXT

    def __init__(
        self,
        interpreter: Interpreter,
        start_actor_name: str,
        mode: Literal["debug", "chat", "single-actor"] = "chat",
    ):
        self.interpreter = interpreter
        self.start_actor_name = start_actor_name
        # `main_actor_name` is the name the debugger falls back to when a
        # command names no actor; it never moves, unlike `working_actor`.
        self.main_actor_name = start_actor_name
        self.working_actor = interpreter.actor_fetch(start_actor_name)
        self.mode = mode

        self.exit_requested = False
        # Set by `handle_command` when the user asks to let the shown step run.
        self.advance_requested = False
        # The command `cmd_exec` is about to execute, while a debug prompt is
        # holding it. `None` at every other moment.
        self.pending_cmd: Optional[CommandObj] = None

        # True only while a `generate` marked `visible=True` is running. A host
        # that installs `interpreter.on_generate_delta` reads this to decide
        # whether tokens belong to the answer being shown or to an internal
        # routing/scratch turn. In the JSON format this had to be guessed by
        # scanning the upcoming instruction list; here the scenario just says so.
        self.visible_generate = False

        # `(actor_name, text)` of the most recent generation marked visible, or
        # None. A host reads this to find the one answer an exchange should
        # show, instead of capturing stdout or scanning ahead for a
        # `print-latest`.
        self.last_visible: Optional[tuple[str, str]] = None

        # Set by `show_latest`: the actor whose output was last displayed.
        self.last_displayed_actor: Optional[str] = None

        # Every command executed, as `(command, kwargs)`.
        self.trace: list[tuple[str, dict[str, Any]]] = []
        self.trace_hook: Optional[Callable[[str, str, dict[str, Any]], None]] = None

        # Command registry for special commands like /save, /load
        self.commands: dict[str, Callable[[Runtime, str], None]] = {}

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------

    @property
    def working_actor_name(self) -> str:
        # `working_actor` is an exit code rather than an actor once an
        # instruction-list run has fully unwound; the main actor is then the
        # only sensible referent.
        return getattr(self.working_actor, "name", self.main_actor_name)

    def actor(self, name: Optional[str] = None) -> Actor:
        return self.interpreter.actor_fetch(name or self.working_actor_name)

    def actor_or_main(self, actor_name: str | None) -> Actor:
        return self.interpreter.actor_fetch(actor_name or self.main_actor_name)

    def store_get(self, key: str, default: Any = None) -> Any:
        value = self.interpreter.store.get(key)
        return default if value is None else value

    def store_set(self, key: str, value: Any) -> None:
        """Assign a store variable.

        Replaces the `assign` command and its `python:` mini-language, whose
        expressions had to survive `Interpreter.evaluate_safe_expression`'s AST
        allowlist. Here the value is just a Python value.
        """
        self.interpreter.store.set(key, value)

    def latest(self, actor_name: Optional[str] = None, n: int = 0):
        return self.actor(actor_name).get_latest_output(n)

    def latest_text(self, actor_name: Optional[str] = None, n: int = 0) -> str:
        output = self.latest(actor_name, n)
        if isinstance(output, dict) and ("content" in output):
            output = output["content"]
        return output if isinstance(output, str) else str(output)

    def raw_latest_text(self, actor_name: Optional[str] = None) -> str:
        """Newest assistant message straight out of unmerged history.

        Unlike `latest_text`, this bypasses any `get_latest_output` override, so
        a custom actor yields the message the model actually produced rather
        than whatever composite view it presents.
        """
        history = self.actor(actor_name).history.read(merged=False)
        for message in reversed(history):
            if message.get("role") != "assistant":
                continue
            content = message.get("content", "")
            return content if isinstance(content, str) else json.dumps(content, default=str)
        return ""

    def clear_visible(self) -> None:
        self.last_visible = None

    # Wait mode reads through to the interpreter rather than keeping a copy of
    # it, so there is one source of truth and every `Runtime` subclass --
    # `WebRuntime`, `BedrockRuntime` -- gets the behaviour with no edit.
    @property
    def waiting(self) -> bool:
        """True while a `wait` is still running down; it expires on its own."""
        return self.interpreter.wait_active

    @property
    def wait_remaining(self) -> float:
        """Seconds left on the current wait, 0.0 when none is running."""
        return self.interpreter.wait_remaining

    @property
    def wait_seconds(self) -> float:
        """The duration the last `wait` asked for, 0.0 when none is running."""
        return self.interpreter.wait_seconds

    def register_command(self, name: str, handler: Callable[[Runtime, str], None]) -> None:
        """Register a special command handler.
        
        Args:
            name: Command name (without leading /)
            handler: Function taking (runtime, args) where args is the string
                     after the command name, or empty string.
        """
        self.commands[name] = handler

    # ------------------------------------------------------------------
    # commands
    # ------------------------------------------------------------------

    @property
    def main_actor(self) -> Actor:
        return self.interpreter.actor_fetch(self.main_actor_name)

    def cmd_exec(self, command: str, **kwargs):
        """Build one command dataclass and execute it against the working actor."""

        cmd = Cmd.from_name(command).map_to_dataclass()(**kwargs)

        if self.mode == "debug":
            self.debug_pause(cmd)

        self.working_actor = self.interpreter.exec(
            cmd=cmd,
            actor_name=self.working_actor_name,
        )

        return self.interpreter, self.working_actor.name

    def cmd(self, command: str, **kwargs) -> Actor:
        """`cmd_exec` plus trace bookkeeping; returns the acting actor.

        Command parameters use the dataclass field names in
        `parser/commands.py`, so they are spelled with underscores
        (`actor_name`, `input_from_store`) rather than the hyphenated keys the
        JSON format uses.
        """
        self.trace.append((command, kwargs))
        if self.trace_hook is not None:
            self.trace_hook(self.working_actor_name, command, kwargs)
        self.cmd_exec(command, **kwargs)
        return self.working_actor

    def system(self, prompt: str | Path):
        return self.cmd("system", prompt=_as_prompt(prompt))

    def refresh(self):
        return self.cmd("refresh")

    def generate(self, prompt: str | Path | None = None, visible: bool = False):
        actor_name = self.working_actor_name
        self.visible_generate = visible
        try:
            if prompt is None:
                actor = self.cmd("generate")
            else:
                actor = self.cmd("generate", prompt=_as_prompt(prompt))
        finally:
            self.visible_generate = False

        if visible:
            self.last_visible = (actor_name, self.raw_latest_text(actor_name))
        return actor

    def agent(self, profile: str, prompt: str | Path | None = None, **kwargs):
        """Run the injected agent executor against the working actor's history."""
        if prompt is not None:
            kwargs["prompt"] = _as_prompt(prompt)
        return self.cmd("agent", profile=profile, **kwargs)

    def input_from_file(self, path: str | Path, enclosing_prompt: str | None = None):
        return self.cmd(
            "input-from",
            input_from_file=_as_prompt(path),
            enclosing_prompt=enclosing_prompt,
        )

    def input_from_store(self, key: str, enclosing_prompt: str | None = None):
        return self.cmd(
            "input-from",
            input_from_store=key,
            enclosing_prompt=enclosing_prompt,
        )

    def input_from_actor(self, actor_name: str, enclosing_prompt: str | None = None):
        return self.cmd(
            "input-from",
            input_from_actor=actor_name,
            enclosing_prompt=enclosing_prompt,
        )

    def append(self, text: str):
        """Append text directly to the working actor's history as a user turn."""
        self.trace.append(("append", {"text": text}))
        self.actor().append_to_history(text)
        return self.working_actor

    def write(self, path: str | Path, overwrite: bool = False, read_from=None, write_history=None):
        kwargs: dict[str, Any] = {"path": _as_prompt(path), "overwrite": overwrite}
        if read_from is not None:
            kwargs["read_from"] = read_from
        if write_history is not None:
            kwargs["write_history"] = write_history
        return self.cmd("write", **kwargs)

    def echo(self, text: str | Path):
        return self.cmd("print", prompt=_as_prompt(text))

    def wait(self, seconds: float):
        """Enter wait mode for `seconds`. Non-blocking: the flow runs straight on.

        Nothing sleeps. The interpreter records a deadline and the next command
        executes immediately; read `waiting` / `wait_remaining` to branch on
        whether the clock is still running. `seconds=0` cancels an active wait.
        """
        return self.cmd("wait", seconds=seconds)

    def show_latest(self, actor_name: Optional[str] = None, n: int = 0):
        """Print an actor's latest output and record it as the shown answer."""
        self.last_displayed_actor = actor_name or self.working_actor_name
        kwargs: dict[str, Any] = {"n": n}
        if actor_name is not None:
            kwargs["actor_name"] = actor_name
        return self.cmd("print-latest", **kwargs)

    # ------------------------------------------------------------------
    # actor entry / exit
    # ------------------------------------------------------------------

    def enter_actor(self, actor_name: str, store: Optional[str] = None):
        """Push `actor_name` onto the callstack and give it control.

        `run-actor` only transfers control; it never runs the target's steps. In
        the JSON format the interpreter then found those steps in the target's
        own instruction list. Here the caller runs the target's function
        instead, and `return_from` performs the unwind that `exec_current` does
        when a callee runs out of instructions.
        """
        return self.cmd("run-actor", actor_name=actor_name, store=store)

    def return_from(self, actor_name: str):
        """Pop `actor_name` and fill any store variable that was waiting on it."""
        self.interpreter.unwind_actor(actor_name)
        if self.interpreter.callstack:
            self.working_actor = self.interpreter.actor_fetch(self.interpreter.callstack[-1])
        return self.working_actor

    # ------------------------------------------------------------------
    # human input
    # ------------------------------------------------------------------

    def deliver(self, request: InputRequest, answer: str) -> str:
        """Apply a human answer, exactly as `exec_INPUT_FROM` would.

        The prompt text itself is never added to history (the JSON path calls
        `prompt_user(..., store_to_history=False)`), and a request that names a
        `store` writes there, only also appending to history when `history` is
        true.
        """
        actor = self.interpreter.actor_fetch(request.actor_name)

        complete_input = answer
        if request.enclosing_prompt:
            enclosing = self.interpreter.parse_prompt_object(request.enclosing_prompt)
            if "{INPUT_FROM}" in enclosing:
                complete_input = enclosing.format(INPUT_FROM=answer)
            else:
                complete_input = enclosing + "\n" + answer

        if request.store:
            self.interpreter.store.set(request.store, complete_input)
            if request.history:
                actor.append_to_history(complete_input)
        else:
            actor.append_to_history(complete_input)

        self.trace.append(("human-input", {"prompt": request.prompt, "store": request.store}))
        return complete_input

    # ------------------------------------------------------------------
    # debugging
    # ------------------------------------------------------------------

    def debug_pause(
        self,
        cmd: type[CommandObj],
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        """Hold at a `debug> ` prompt until the user lets `cmd` run.

        Called before every command in `mode="debug"`, so a runtime in that mode
        must only ever be driven from a terminal.
        """
        exit_message = self.get_exit_message()
        if exit_message is not None:
            output_fn(exit_message)

        output_fn(self.format_step(cmd))

        self.pending_cmd = cmd
        self.advance_requested = False
        try:
            while not self.advance_requested:
                for output in self.handle_command(input_fn("debug> ")):
                    output_fn(output)
                if self.exit_requested:
                    raise DebugQuit(f"Debug run stopped before {cmd}.")
        finally:
            self.pending_cmd = None

    def run_debug(
        self,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        """Step through an actor's *instruction list* at a `debug> ` prompt.

        This is the JSON-scenario debugger: each `n` advances the interpreter by
        one instruction. Scenarios written as Python are stepped by
        `debug_pause` instead, once per command, and never reach this loop.
        """
        output_fn(self.HELP_TEXT)

        while True:
            exit_message = self.get_exit_message()
            if exit_message is not None:
                output_fn(exit_message)
                break

            output_fn(self.format_current_step())

            self.advance_requested = False
            for output in self.handle_command(input_fn("debug> ")):
                output_fn(output)

            if self.exit_requested:
                break
            if self.advance_requested:
                self.working_actor = self.interpreter.exec_current()

    def save_session(self, path=None, session_id=None):
        """Save the whole interpreter session; see `Interpreter.save_session`."""
        return self.interpreter.save_session(path=path, session_id=session_id)

    def load_session(self, path=None, session_id=None) -> str:
        """Load a saved session and hand control to the top of its callstack."""
        loaded_id = self.interpreter.load_session(path=path, session_id=session_id)
        if self.interpreter.callstack:
            self.working_actor = self.interpreter.actor_fetch(self.interpreter.callstack[-1])
        return loaded_id

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
        """Run one debugger command and return the lines it wants printed.

        Sets `advance_requested` for the commands that let execution continue;
        every other command only inspects state.
        """
        parts = raw_command.strip().split()
        if not parts:
            self.advance_requested = True
            return []

        command = parts[0].lower()

        try:
            if command in {"n", "next"}:
                self.advance_requested = True
                return []
            if command in {"h", "help"}:
                return [self.HELP_TEXT]
            if command in {"q", "quit"}:
                self.exit_requested = True
                return []
            if command in {"s", "state"}:
                return [self.format_state()]
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
                actor_name = self.working_actor_name
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
                return [self.format_instr(parts[1] if len(parts) >= 2 else None)]
            if command == "trace":
                try:
                    limit = int(parts[1]) if len(parts) >= 2 else 20
                except ValueError:
                    return ["Usage: trace [n]"]
                return [self.format_trace(limit)]

            return [f"Unknown command: {raw_command}", self.HELP_TEXT]
        except Exception:
            return [traceback.format_exc().rstrip()]

    def get_exit_message(self) -> str | None:
        """Describe a finished instruction-list run, or None if still running."""
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
            f"\n[{self.working_actor_name}] next command: {cmd}"
            f"\n Callstack: {self.interpreter.callstack}"
        )

    def format_current_step(self) -> str:
        return (
            f"\n[{self.working_actor.name} step {self.working_actor.cur_step}] "
            f"Next instruction: {self.working_actor.get_current_instr()}"
            f"\n Callstack: {self.interpreter.callstack}"
        )

    def format_instr(self, actor_name: Optional[str] = None) -> str:
        """The step an actor is about to run.

        An actor driven from Python has no instruction list to point into, so
        the pending step is whatever command `cmd_exec` is currently holding.
        """
        actor = self.actor_or_main(actor_name)
        instructions = getattr(actor, "instructions", None)
        if instructions:
            return str(actor.get_current_instr())
        if self.pending_cmd is not None:
            return str(self.pending_cmd)
        return f"{actor.name} has no instruction list; its commands come from calling code."

    def format_state(self) -> str:
        """Summarize interpreter state.

        `Interpreter.__repr__` is unusable here: it iterates `self.actors`, which
        yields actor *names*, and calls `__repr__` on those strings.
        """
        return "\n".join(
            [
                f"Working actor: {self.working_actor_name}",
                f"Callstack: {self.interpreter.callstack}",
                str(self.interpreter.store),
                self.format_actor_summary(),
            ]
        )

    def format_actor_summary(self) -> str:
        lines = []
        for name, actor in self.interpreter.actors.items():
            messages = len(actor.history.read(merged=False))
            position = f"messages={messages}"
            if getattr(actor, "instructions", None):
                try:
                    position = (
                        f"step={actor.cur_step} messages={messages} "
                        f"current_instr={actor.get_current_instr()}"
                    )
                except Exception:
                    position = f"step={actor.cur_step} messages={messages}"

            on_stack = " (on callstack)" if name in self.interpreter.callstack else ""
            marker = " <- working" if name == self.working_actor_name else ""
            lines.append(f"{name}: {position}{on_stack}{marker}")
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
        history = self.interpreter.actor_fetch(actor_name).history.read()
        if not history:
            return f"{actor_name} history is empty."
        return json.dumps(history, indent=2)

    def format_latest(self, actor_name: str, n: int) -> str:
        latest_output = self.interpreter.actor_fetch(actor_name).get_latest_output(n)
        if isinstance(latest_output, dict):
            return json.dumps(latest_output, indent=2)
        return str(latest_output)

    def format_trace(self, limit: int) -> str:
        recent = self.trace[-limit:]
        if not recent:
            return "No commands executed yet."
        return "\n".join(
            f"{command} {({k: v for k, v in kwargs.items() if v is not None})}"
            for command, kwargs in recent
        )


def _as_prompt(value: str | Path) -> str:
    return str(value) if isinstance(value, Path) else value


# ----------------------------------------------------------------------
# flow primitives
# ----------------------------------------------------------------------


def ask(
    rt: Runtime,
    prompt: str,
    store: Optional[str] = None,
    history: bool = True,
    enclosing_prompt: Optional[str] = None,
    content: bool = True,
) -> Flow:
    """Suspend the scenario until a human answers, then record the answer.

    Usage inside a flow:

        reply = yield from ask(rt, "Teacher>", store="teacher_prompt")

    Pass `content=False` for a prompt that carries no information beyond "say
    something" -- the generic turn-taking cue at the top of a chat loop, say. A
    console UI already has its own way to ask for the next message and should
    not display that cue as an AI-authored message; a genuine clarifying
    question (the default, `content=True`) still needs to reach the human, so it
    is shown.
    """
    while True:
        request = InputRequest(
            actor_name=rt.working_actor_name,
            prompt=prompt,
            store=store,
            history=history,
            enclosing_prompt=enclosing_prompt,
            content=content,
        )
        answer = yield request
        
        # Check for command prefix
        if answer.startswith('/'):
            # Parse command: /command args
            parts = answer[1:].split(maxsplit=1)
            cmd = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            
            if cmd in rt.commands:
                try:
                    rt.commands[cmd](rt, args)
                except (CommandRestart, CommandExit):
                    raise
                except Exception as e:
                    print(f"Command error: {e}")
                continue  # Command executed, re-prompt
            elif rt.commands:  # Commands registered but this one not found
                print(f"Unknown command: /{cmd}. Type /help for list.")
                continue
            # No commands registered, treat /input as normal input
        
        # Not a command or command handled
        rt.deliver(request, answer)
        return answer


def call_actor(
    rt: Runtime,
    actor_name: str,
    flow: Callable[[Runtime], Flow | None],
    store: Optional[str] = None,
) -> Flow:
    """Run one cycle of another actor and return what it produced.

    This is `run-actor`, plus the callee's own steps, plus the unwind, as a
    single Python call. A sub-flow returns control by returning; there is no
    `exit` command and no callstack bookkeeping in the scenario itself.

    What comes back is the sub-flow's own return value when it has one -- a
    parsed decision, say, rather than the text it was parsed out of. Otherwise
    it is the store variable named by `store`, or the actor's latest output.
    """
    rt.enter_actor(actor_name, store=store)
    try:
        # A flow that never needs human input is an ordinary function; only
        # interactive ones have to be generators.
        result = flow(rt)
        if inspect.isgenerator(result):
            result = yield from result
    finally:
        rt.return_from(actor_name)

    if result is not None:
        return result
    if store:
        return rt.store_get(store)
    return rt.latest_text(actor_name)


# ----------------------------------------------------------------------
# drivers
# ----------------------------------------------------------------------


def drive_flow(
    flow: Flow,
    input_fn: Optional[Callable[[InputRequest], str]] = None,
    output_fn: Callable[[str], None] = print,
) -> None:
    """Run a flow to completion in a terminal, blocking for each answer.

    A host that must not block (an HTTP handler, say) skips this and drives the
    flow itself: `next(flow)` runs up to the first `InputRequest`, and
    `flow.send(answer)` resumes it up to the next one, so the flow can stay
    parked between requests.
    """

    if input_fn is None:
        def input_fn(request: InputRequest) -> str:
            return input(f"{request.actor_name}: {request.prompt} ")

    try:
        request = next(flow)
        while True:
            request = flow.send(input_fn(request))
    except StopIteration:
        output_fn("Flow finished.")
    except DebugQuit as quit_signal:
        output_fn(str(quit_signal) or "Debug run stopped.")

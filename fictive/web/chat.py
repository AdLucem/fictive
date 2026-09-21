"""One chat-mode scenario run, recorded as the nested flow tree a UI can draw.

This is `fictive.run.run_chat` with two changes, and nothing else:

- `run_chat` loops `Interpreter.exec_current()` until `DebuggerSession`
  reports an exit. So does `ChatSession.advance`, against the same
  `DebuggerSession`, so the interpreter and callstack move through exactly the
  states chat mode moves through.
- `run_chat` blocks in `Actor.prompt_user`, which calls `input()`. A web
  request cannot block on stdin, so `advance` stops *before* an `input-from`
  that wants a human answer and returns; the answer arrives later through
  `send_input`, and `prompt_user` reads it from this session instead of stdin.

While stepping, `ChatSession` records what each step did. A `run-actor`
pushes a frame onto the interpreter's callstack, so it opens a node in the
tree; the callstack shrinking again closes it and reads the callee's return
value out of the store. That tree is the transcript: the main actor's
generations are the chat, and every other actor appears as a frame nested at
its callstack depth.
"""

from __future__ import annotations

import itertools
import pathlib
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from ..actors import Actor, ActorConfig
from ..custom_actors import actor_from_config
from ..debugger import DebuggerSession
from ..interpreter import Interpreter
from ..parse_scenario_config import load_scenario_config

# Commands whose text output belongs in the transcript as prose.
GENERATING_COMMANDS = {"generate", "rag-generate", "web-search-and-generate"}

# A step that needs no detail line of its own in the UI.
QUIET_COMMANDS = {"refresh", "print", "print-latest"}


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(value.get("content", value))
    return str(value)


@dataclass
class FlowNode:
    """One `run-actor` frame: an expandable bar in the UI."""

    actor: str
    command: str
    depth: int
    seq: int
    store: Optional[str] = None
    status: str = "running"
    returned: Optional[str] = None
    error: Optional[str] = None
    children: list = field(default_factory=list)

    def to_json(self) -> dict:
        children = [child.to_json() for child in self.children]
        return {
            "kind": "flow",
            "seq": self.seq,
            "actor": self.actor,
            "command": self.command,
            "depth": self.depth,
            "store": self.store,
            "status": self.status,
            "returned": self.returned,
            "error": self.error,
            "command_count": sum(1 for c in self.children if c.to_json()["kind"] != "flow"),
            "nested_count": sum(1 for c in self.children if c.to_json()["kind"] == "flow"),
            "children": children,
        }


@dataclass
class StepNode:
    """One executed command that did not open a frame."""

    actor: str
    command: str
    depth: int
    seq: int
    detail: str = ""
    text: Optional[str] = None
    step: Optional[int] = None
    error: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "kind": "step",
            "seq": self.seq,
            "actor": self.actor,
            "command": self.command,
            "depth": self.depth,
            "detail": self.detail,
            "text": self.text,
            "step": self.step,
            "error": self.error,
        }


@dataclass
class MessageNode:
    """A turn in the main actor's conversation: the chat itself."""

    actor: str
    role: str
    text: str
    seq: int
    command: str
    step: Optional[int] = None

    def to_json(self) -> dict:
        return {
            "kind": "message",
            "seq": self.seq,
            "actor": self.actor,
            "role": self.role,
            "text": self.text,
            "command": self.command,
            "step": self.step,
            "depth": 0,
        }


class ScenarioSpec:
    """A scenario directory, loaded once and reused by every session."""

    def __init__(self, scenario_dir: str | pathlib.Path):
        self.dir = pathlib.Path(scenario_dir).resolve()
        schema, actor_definitions, author_intent = load_scenario_config(str(self.dir))
        self.schema = schema
        self.actor_definitions = actor_definitions
        self.author_intent = author_intent
        self.actor_names: list[str] = list(schema["actors"])
        # `actor_types` is read here, not by the scenario loader: the loader
        # returns the schema as-is, and the host decides which Actor subclass
        # each name is built with (`examples/evil_AI/main.py` hardcodes the
        # same map in Python).
        self.actor_types: dict[str, Optional[str]] = {
            name: (schema.get("actor_types", {}) or {}).get(name) for name in self.actor_names
        }
        self.main_actor_name: str = schema.get("main_actor", self.actor_names[0])

    @property
    def name(self) -> str:
        parent = self.dir.parent.name
        return parent if self.dir.name == "scenario" else self.dir.name

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "dir": str(self.dir),
            "main_actor": self.main_actor_name,
            "actors": [
                {
                    "name": name,
                    "type": self.actor_types.get(name) or "actor",
                    "commands": len(self.actor_definitions[name]),
                }
                for name in self.actor_names
            ],
        }


class ChatSession:
    """A live scenario run plus the flow tree recorded from its steps."""

    MAX_STEPS_PER_TURN = 400

    def __init__(
        self,
        spec: ScenarioSpec,
        pipeline,
        storage_dir: str | pathlib.Path,
        title: Optional[str] = None,
    ):
        self.id = uuid.uuid4().hex[:7]
        self.spec = spec
        self.title = title or "New session"
        self.storage_dir = pathlib.Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        actors: list[Actor] = []
        for name in spec.actor_names:
            actors.append(
                actor_from_config(
                    ActorConfig(
                        name=name,
                        actor_type=spec.actor_types.get(name),
                        storage_dir=str(self.storage_dir),
                        instructions=spec.actor_definitions[name],
                        pipeline=pipeline,
                    )
                )
            )

        self.interpreter = Interpreter(actors, main_actor_name=spec.main_actor_name)
        # Streaming would go through `Interpreter.on_generate_delta`, but it
        # reaches the pipeline's `generate_stream`, which the llm_utils
        # pipelines do not define. Setting the hook against one of those would
        # raise on the first `generate`, so it is left unset.
        if hasattr(pipeline, "generate_stream"):
            self.interpreter.on_generate_delta = self._on_delta

        # The same session object chat mode builds, for the same exit checks.
        self.session = DebuggerSession(self.interpreter, spec.main_actor_name)

        self._seq = itertools.count()
        self.turns: list[Any] = []
        self._open_flows: list[FlowNode] = []
        self.deltas: list[dict] = []
        self.status = "new"
        self.error: Optional[str] = None
        self.exit_message: Optional[str] = None
        self.saved_path: Optional[str] = None
        self._pending_input: Optional[str] = None
        self.turn_count = 0

        for actor in actors:
            self._bind_web_input(actor)

    # ---------------------------------------------------------------- input

    def _bind_web_input(self, actor: Actor) -> None:
        """Make this actor's `prompt_user` read from the session, not stdin.

        Set on the instance so the actor keeps its own class: a `Scorer` stays
        a `Scorer`. The history side effects are the base method's, because
        `exec_INPUT_FROM` relies on them.
        """

        def prompt_user(prompt=None, store_to_history=True):
            prompt_str = "" if prompt is None else prompt
            user_input = self._take_input()
            if store_to_history:
                if prompt_str != "":
                    actor.history.add({"role": "assistant", "content": prompt_str})
                actor.history.add({"role": "user", "content": user_input})
            return user_input

        actor.prompt_user = prompt_user

    def _take_input(self) -> str:
        if self._pending_input is None:
            # `advance` stops before a human `input-from`, so this is only
            # reachable if a scenario asks for input somewhere it cannot be
            # seen coming.
            raise RuntimeError(
                f"Actor asked for human input in session {self.id} with none queued"
            )
        text = self._pending_input
        self._pending_input = None
        return text

    def _on_delta(self, actor_name: str, event: dict) -> None:
        self.deltas.append({"actor": actor_name, "event": event})

    # ------------------------------------------------------------ inspection

    def _working_actor(self) -> Optional[Actor]:
        if not self.interpreter.callstack:
            return None
        return self.interpreter.actor_fetch(self.interpreter.callstack[-1])

    def pending_human_prompt(self) -> Optional[str]:
        """The prompt of the next instruction, when it wants a human answer.

        Mirrors `exec_INPUT_FROM`'s own test: a `human_prompt` of `""` is a
        human prompt, `None` is not.
        """
        if self.status in {"finished", "error"}:
            return None
        actor = self._working_actor()
        if actor is None:
            return None
        try:
            instr = actor.get_current_instr()
        except (IndexError, KeyError):
            return None
        if instr is None or instr.name != "input-from":
            return None
        human_prompt = getattr(instr, "human_prompt", None)
        if human_prompt is None:
            return None
        if human_prompt == "":
            return ""
        return _as_text(self.interpreter.parse_prompt_object(human_prompt))

    # -------------------------------------------------------------- stepping

    def awaiting_input_now(self) -> bool:
        return self.pending_human_prompt() is not None

    def start(self) -> "ChatSession":
        self.status = "running"
        self.advance()
        return self

    def rebuild_from_history(self) -> None:
        """Rebuild the transcript from a restored session file.

        A session file holds each actor's history, the store and the callstack
        — not this tree, which is recorded from steps as they run. So a resumed
        session shows the main actor's conversation and says plainly that the
        frames from before the save are not in the file; frames opened from
        here on are recorded normally.
        """
        self.turns = []
        self._open_flows = []
        main_actor = self.interpreter.actor_fetch(self.spec.main_actor_name)
        for message in main_actor.history.read(merged=False):
            role = message.get("role")
            if role not in {"user", "assistant"}:
                continue
            self.turns.append(
                MessageNode(
                    actor=main_actor.name,
                    role=role,
                    text=_truncate(_as_text(message.get("content"))),
                    seq=next(self._seq),
                    command="load-conversation",
                )
            )
        self.turns.append(
            StepNode(
                actor=main_actor.name,
                command="load-conversation",
                depth=0,
                seq=next(self._seq),
                detail="restored — called flows from before the save are not in the session file",
            )
        )

    def send_input(self, text: str) -> "ChatSession":
        if self.status in {"finished", "error"}:
            return self
        if self.pending_human_prompt() is None:
            raise RuntimeError(f"Session {self.id} is not waiting for input")
        self._pending_input = text
        self.turn_count += 1
        if self.turn_count == 1 and self.title == "New session":
            self.title = _truncate(text.strip().splitlines()[0] if text.strip() else "Untitled", 60)
        self.advance()
        return self

    def advance(self) -> None:
        """Step until the scenario wants a human answer, or it ends."""
        for _ in range(self.MAX_STEPS_PER_TURN):
            self.exit_message = self.session.get_exit_message()
            if self.exit_message is not None:
                self.status = "finished"
                self._close_flows(len(self._open_flows), status="returned")
                return

            if self._pending_input is None and self.pending_human_prompt() is not None:
                self.status = "awaiting_input"
                return

            if not self._step():
                return

        self.status = "awaiting_input"

    def _step(self) -> bool:
        """Execute one interpreter step and record it. False stops the loop."""
        interpreter = self.interpreter
        stack_before = list(interpreter.callstack)
        if not stack_before:
            self.status = "finished"
            return False

        actor_name = stack_before[-1]
        actor = interpreter.actor_fetch(actor_name)
        instr = actor.get_current_instr()
        command = instr.name
        step_index = actor.cur_step
        depth = max(len(stack_before) - 1, 0)
        history_before = len(actor.history.read(merged=False))
        seq = next(self._seq)

        # A human `input-from` is recorded as the user's chat turn, so keep the
        # text before the step consumes it.
        submitted_input = self._pending_input if command == "input-from" else None

        try:
            result = self.session.working_actor = interpreter.exec_current()
        except Exception:
            detail = traceback.format_exc(limit=3).strip().splitlines()[-1]
            self.error = detail
            self.status = "error"
            node = StepNode(
                actor=actor_name,
                command=command,
                depth=depth,
                seq=seq,
                detail=self._detail(instr, actor),
                step=step_index,
                error=detail,
            )
            self._append(node)
            if self._open_flows:
                self._open_flows[-1].status = "failed"
                self._open_flows[-1].error = detail
                self._close_flows(len(self._open_flows), status="failed")
            return False

        stack_after = list(interpreter.callstack)

        if command == "run-actor":
            callee = getattr(instr, "actor_name", "?")
            flow = FlowNode(
                actor=callee,
                command="run-actor",
                depth=max(len(stack_after) - 1, 0),
                seq=seq,
                store=getattr(instr, "store", None),
            )
            self._append(flow)
            self._open_flows.append(flow)
        else:
            self._record_plain_step(
                instr=instr,
                actor=actor,
                actor_name=actor_name,
                command=command,
                depth=depth,
                seq=seq,
                step_index=step_index,
                history_before=history_before,
                submitted_input=submitted_input,
            )

        unwound = len(stack_before) - len(stack_after)
        if command == "run-actor":
            unwound = 0
        if unwound > 0:
            self._close_flows(unwound, status="returned")

        if isinstance(result, int):
            self.status = "finished"
            self.exit_message = self.session.get_exit_message()
            self._close_flows(len(self._open_flows), status="returned")
            return False
        return True

    def _record_plain_step(
        self,
        *,
        instr,
        actor: Actor,
        actor_name: str,
        command: str,
        depth: int,
        seq: int,
        step_index: int,
        history_before: int,
        submitted_input: Optional[str],
    ) -> None:
        is_main = actor_name == self.spec.main_actor_name and not self._open_flows

        if command == "input-from" and submitted_input is not None:
            if is_main:
                self._append(
                    MessageNode(
                        actor=actor_name,
                        role="user",
                        text=submitted_input,
                        seq=seq,
                        command=command,
                        step=step_index,
                    )
                )
            else:
                self._append(
                    StepNode(
                        actor=actor_name,
                        command=command,
                        depth=depth,
                        seq=seq,
                        detail="human input",
                        text=submitted_input,
                        step=step_index,
                    )
                )
            return

        generated = None
        if command in GENERATING_COMMANDS:
            generated = self._new_assistant_text(actor, history_before)

        if generated is not None and is_main:
            self._append(
                MessageNode(
                    actor=actor_name,
                    role="assistant",
                    text=generated,
                    seq=seq,
                    command=command,
                    step=step_index,
                )
            )
            return

        self._append(
            StepNode(
                actor=actor_name,
                command=command,
                depth=depth,
                seq=seq,
                detail=self._detail(instr, actor),
                text=generated,
                step=step_index,
            )
        )

    @staticmethod
    def _new_assistant_text(actor: Actor, history_before: int) -> Optional[str]:
        """The assistant message this step added, read off raw history.

        Raw history, not `get_latest_output()`: a `Generator` returns its whole
        scene from that and a `Scorer` returns a number, and what the
        transcript wants is the text the step itself produced.
        """
        history = actor.history.read(merged=False)
        for message in reversed(history[history_before:]):
            if message.get("role") == "assistant":
                return _truncate(_as_text(message.get("content")))
        return None

    def _detail(self, instr, actor: Actor) -> str:
        """A short, honest line about what the command was given."""
        command = instr.name
        if command in QUIET_COMMANDS:
            return ""
        try:
            if command == "system":
                return self._prompt_label(getattr(instr, "prompt", None))
            if command == "input-from":
                for attribute, label in (
                    ("input_from_actor", "from actor"),
                    ("input_from_store", "from store"),
                    ("input_from_file", "from file"),
                ):
                    value = getattr(instr, attribute, None)
                    if value:
                        target = self._prompt_label(value)
                        store = getattr(instr, "store", None)
                        suffix = f" → {store}" if store else ""
                        return f"{label} {target}{suffix}"
                return "human input"
            if command == "generate":
                prompt = getattr(instr, "prompt", None)
                return self._prompt_label(prompt) if prompt else "from history"
            if command == "assign":
                return f"{getattr(instr, 'var_name', '?')} = {_truncate(_as_text(getattr(instr, 'value', '')), 120)}"
            if command == "loop":
                return f"back to step {getattr(instr, 'step', 0)}"
            if command == "cond":
                conditions = getattr(instr, "conditions", []) or []
                return f"{len(conditions)} branches"
            if command == "agent":
                return (
                    f"workspace {getattr(instr, 'workspace', '.')} · "
                    f"limit {getattr(instr, 'request_limit', '?')}"
                )
            if command == "write":
                return str(getattr(instr, "path", ""))
            if command == "exit":
                return "returns to caller"
        except Exception:  # a detail line must never break a run
            return ""
        return ""

    def _prompt_label(self, value) -> str:
        """Prompt paths show as a scenario-relative name, not an absolute path."""
        text = _as_text(value)
        if not text:
            return ""
        try:
            path = pathlib.Path(text)
            if path.is_absolute() and path.exists():
                try:
                    return str(path.relative_to(self.spec.dir))
                except ValueError:
                    return path.name
        except OSError:
            pass
        return _truncate(text, 160)

    def _append(self, node) -> None:
        if self._open_flows:
            self._open_flows[-1].children.append(node)
        else:
            self.turns.append(node)

    def _close_flows(self, count: int, status: str) -> None:
        for _ in range(min(count, len(self._open_flows))):
            flow = self._open_flows.pop()
            if flow.status == "running":
                flow.status = status
            if flow.store and self.interpreter.store.has(flow.store):
                flow.returned = _truncate(_as_text(self.interpreter.store.get(flow.store)), 400)

    # --------------------------------------------------------------- session

    def save(self) -> str:
        path = self.interpreter.save_session(session_id=self.id)
        self.saved_path = str(path)
        return self.saved_path

    def store_json(self) -> list[dict]:
        store = self.interpreter.store.store
        waiting = {var: actor for var, actor in self.interpreter.waiting_store.items()}
        rows = []
        for name, value in store.items():
            rows.append(
                {
                    "name": name,
                    "type": type(value).__name__,
                    "value": _truncate(_as_text(value), 400),
                    "assigned": True,
                    "waiting_on": waiting.get(name),
                }
            )
        for name, actor in waiting.items():
            if name not in store:
                rows.append(
                    {
                        "name": name,
                        "type": "pending",
                        "value": "",
                        "assigned": False,
                        "waiting_on": actor,
                    }
                )
        return rows

    def to_json(self) -> dict:
        prompt = self.pending_human_prompt()
        working = self._working_actor()
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "scenario": self.spec.to_json(),
            "main_actor": self.spec.main_actor_name,
            "working_actor": working.name if working else None,
            "callstack": list(self.interpreter.callstack),
            "waiting_prompt": prompt,
            "awaiting_input": prompt is not None,
            "turn_count": self.turn_count,
            "exit_message": self.exit_message,
            "error": self.error,
            "saved_path": self.saved_path,
            "turns": [node.to_json() for node in self.turns],
            "store": self.store_json(),
            "step_pointers": {
                name: actor.cur_step for name, actor in self.interpreter.actors.items()
            },
        }

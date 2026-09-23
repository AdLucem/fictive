"""The nested flow tree a UI draws, recorded from a running scenario.

The tree is the transcript: the main actor's visible generations are the chat,
and every actor the scenario calls appears as a frame nested at its depth on the
interpreter's callstack. `TranscriptRecorder` owns that tree and nothing else --
it never imports `Interpreter`, so `WebRuntime` can hold one and the session can
read it without a cycle.

This module also holds `_TeeStdout`, because several scene commands say what
they did by printing: `exec_PRINT` and `exec_PRINT_LATEST` write to stdout, as
does `ask`'s slash-command error path and any plain Python a scenario runs
between commands. A terminal driver shows that text; an HTTP host has to capture
it. `contextlib.redirect_stdout` cannot: it swaps the global `sys.stdout`, and
FastAPI runs `def` handlers in a threadpool, so two sessions advancing at once
would cross-capture and restore in the wrong order. One tee with a thread-local
sink gives every thread its own buffer and still writes through, so uvicorn's
own logging reaches the terminal as before.
"""

from __future__ import annotations

import contextlib
import copy
import io
import itertools
import sys
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..actors import Actor

# Commands whose text output belongs in the transcript as prose.
GENERATING_COMMANDS = {"generate", "rag-generate", "web-search-and-generate"}

# A step that needs no detail line of its own in the UI.
QUIET_COMMANDS = {"refresh", "print", "print-latest"}

# Commands whose *input* is worth showing in full, not just named. A `system`
# or an `input-from` is usually written as a file path, and the file name alone
# says nothing about what the actor was actually handed.
DETAILED_COMMANDS = {"system", "input-from"}

# `detail_text` carries a whole prompt rather than a summary line, so it gets a
# far looser cap than `_truncate`'s -- loose enough that a real system prompt
# arrives whole, bounded only so one pathological file cannot bloat every
# response that redraws the tree.
DETAIL_TEXT_LIMIT = 40000


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


def _max_seq(node) -> int:
    """The highest `seq` anywhere in this node's subtree."""
    highest = node.seq
    for child in getattr(node, "children", ()) or ():
        highest = max(highest, _max_seq(child))
    return highest


def new_assistant_text(actor: Actor, history_before: int) -> Optional[str]:
    """The assistant message this command added, read off raw history.

    Raw history, not `get_latest_output()`: a `Generator` returns its whole scene
    from that and a `Scorer` returns a number, and what the transcript wants is
    the text the command itself produced.

    Diffing around the command rather than reading `Runtime.raw_latest_text()` is
    what makes `None` meaningful -- a `system` or `refresh` produced nothing, and
    must never be mislabelled as the previous generation's text. It also survives
    `Scorer.generate`'s remove-and-regenerate loop, whose churn all happens at
    indices at or past `history_before`.
    """
    history = actor.history.read(merged=False)
    for message in reversed(history[history_before:]):
        if message.get("role") == "assistant":
            return _truncate(_as_text(message.get("content")))
    return None


def new_history_text(actor: Actor, history_before: int) -> Optional[str]:
    """The message this command added to history, whatever role it took.

    Role-agnostic where `new_assistant_text` is not, because this reads what a
    command was *given* rather than what it generated: `input-from` appends the
    resolved input as a plain user turn, but an actor's latest output arrives as
    a dict carrying its own role and `append_to_history` keeps that role.
    """
    history = actor.history.read(merged=False)
    added = history[history_before:]
    if not added:
        return None
    return _truncate(_as_text(added[-1].get("content")), DETAIL_TEXT_LIMIT)


@dataclass
class FlowNode:
    """One called actor: an expandable bar in the UI.

    A frame is opened by `run-actor` -- whether the scenario issued it directly
    or through `call_actor` -- and closed when control returns.
    """

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
            "command_count": sum(1 for c in children if c["kind"] != "flow"),
            "nested_count": sum(1 for c in children if c["kind"] == "flow"),
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
    # What the command was handed, in full: the resolved system prompt, or the
    # text an `input-from` put into the actor. `detail` stays the one-line
    # label, so the UI has something to show while this is collapsed.
    detail_text: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "kind": "step",
            "seq": self.seq,
            "actor": self.actor,
            "command": self.command,
            "depth": self.depth,
            "detail": self.detail,
            "detail_text": self.detail_text,
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


class TranscriptRecorder:
    """The tree, plus the open-frame stack it is built against.

    Every mutation and every read holds `lock`, so a `GET` that serializes the
    tree cannot catch a half-built node list while another thread runs a turn.
    The lock is never held across a model call: the recorder is only ever handed
    finished facts.
    """

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self._seq = itertools.count()
        self.turns: list[Any] = []
        self.open_flows: list[FlowNode] = []
        # How many commands each actor has issued. Runtime actors have no
        # instruction list, so `cur_step` is always 0 and cannot serve as the
        # position readout a UI wants; the count of commands issued can.
        self.command_counts: Counter[str] = Counter()

    def next_seq(self) -> int:
        return next(self._seq)

    @property
    def depth(self) -> int:
        """The depth a non-frame command is recorded at.

        Read off the open-frame stack rather than the interpreter's callstack:
        `Interpreter.unwind_actor` silently no-ops when the name it is given is
        not on top, so the two can disagree, and the tree has to stay consistent
        with itself. `reconcile` puts them back in step.
        """
        return len(self.open_flows)

    def reset(self) -> None:
        with self.lock:
            self.turns = []
            self.open_flows = []
            self.command_counts.clear()

    def append(self, node) -> None:
        with self.lock:
            if self.open_flows:
                self.open_flows[-1].children.append(node)
            else:
                self.turns.append(node)

    def count_command(self, actor_name: str) -> int:
        with self.lock:
            self.command_counts[actor_name] += 1
            return self.command_counts[actor_name]

    def open_flow(
        self,
        actor: str,
        depth: int,
        seq: int,
        store: Optional[str] = None,
        command: str = "run-actor",
    ) -> FlowNode:
        flow = FlowNode(actor=actor, command=command, depth=depth, seq=seq, store=store)
        with self.lock:
            self.append(flow)
            self.open_flows.append(flow)
        return flow

    def close_flow(
        self,
        actor_name: Optional[str],
        status: str,
        error: Optional[str] = None,
        store_reader: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        """Close frames down to and including the one `actor_name` opened.

        Popping by name rather than one frame per call is what keeps the tree
        honest when a sub-flow leaves a frame open -- `unwind_actor` would not
        have popped the interpreter's callstack either, and the next `reconcile`
        cannot tell which of two frames was meant.
        """
        with self.lock:
            if not self.open_flows:
                return

            index = len(self.open_flows) - 1
            if actor_name is not None:
                matches = [
                    i for i, flow in enumerate(self.open_flows) if flow.actor == actor_name
                ]
                if not matches:
                    return
                index = matches[-1]

            while len(self.open_flows) > index:
                self._finish(self.open_flows.pop(), status, error, store_reader)

    def reconcile(
        self,
        callstack_depth: int,
        store_reader: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        """Close frames the interpreter has already left."""
        with self.lock:
            while len(self.open_flows) > max(callstack_depth, 0):
                self._finish(self.open_flows.pop(), "returned", None, store_reader)

    def fail_open_frames(self, error: Optional[str]) -> None:
        with self.lock:
            while self.open_flows:
                self._finish(self.open_flows.pop(), "failed", error, None)

    def _finish(
        self,
        flow: FlowNode,
        status: str,
        error: Optional[str],
        store_reader: Optional[Callable[[str], Optional[str]]],
    ) -> None:
        if flow.status == "running":
            flow.status = status
        if error and flow.error is None:
            flow.error = error
        if flow.store and (store_reader is not None) and (flow.returned is None):
            value = store_reader(flow.store)
            if value is not None:
                flow.returned = _truncate(value, 400)

    # ------------------------------------------------------------------
    # branching
    # ------------------------------------------------------------------

    def mark(self) -> tuple[int, "Counter[str]"]:
        """Where the transcript stands, for a checkpoint to come back to.

        The length of the top-level turn list, not a node's `seq`: a rewrite has
        to cut the tree at a boundary, and a length is the only reading of
        "before this turn" that stays correct when the turn that followed
        recorded nothing at all.
        """
        with self.lock:
            return len(self.turns), self.command_counts.copy()

    def node_at(self, index: int):
        with self.lock:
            if 0 <= index < len(self.turns):
                return self.turns[index]
            return None

    def truncate(self, turns_len: int, command_counts: "Counter[str]") -> None:
        """Cut the transcript back to a `mark()`, for a rewrite in place.

        The seq counter is deliberately not rewound. Nodes recorded after this
        get numbers no earlier node ever had, so a UI keyed on `seq` cannot
        confuse a replayed turn with the one it replaced.
        """
        with self.lock:
            del self.turns[turns_len:]
            self.open_flows = []
            self.command_counts = command_counts.copy()

    def prefix(self, turns_len: int) -> list:
        """A standalone copy of the transcript up to a `mark()`.

        Deep-copied under this recorder's own lock, because the caller is a
        second session: a fork and the session it branched from run on from here
        independently and must not share nodes.
        """
        with self.lock:
            return copy.deepcopy(self.turns[:turns_len])

    def adopt(self, turns: list, command_counts: "Counter[str]") -> None:
        """Take a `prefix()` from another recorder as this one's history.

        The seq counter is moved past everything adopted, so this recorder's own
        nodes cannot collide with the numbers it inherited.
        """
        highest = -1
        for node in turns:
            highest = max(highest, _max_seq(node))
        with self.lock:
            self.turns = list(turns)
            self.open_flows = []
            self.command_counts = command_counts.copy()
            self._seq = itertools.count(highest + 1)

    def rebuild_from_history(self, actor: Actor, instructions_re=None) -> None:
        """Rebuild the transcript from a restored session file.

        A session file holds each actor's history, the store and the callstack --
        not this tree, which is recorded from commands as they run. So a resumed
        session shows the main actor's conversation and says plainly that the
        frames from before the save are not in the file; frames opened from here
        on are recorded normally.
        """
        with self.lock:
            self.turns = []
            self.open_flows = []
            for message in actor.history.read(merged=False):
                role = message.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = _as_text(message.get("content"))
                if instructions_re is not None and role == "user":
                    # `(INSTRUCTIONS: ...)` turns are authored by the scenario,
                    # not typed by the reader; `History.to_scene` strips them for
                    # the same reason. Left in, they render as the reader's own
                    # chat bubbles.
                    text = instructions_re.sub("", text).strip()
                if not text.strip():
                    continue
                self.turns.append(
                    MessageNode(
                        actor=actor.name,
                        role=role,
                        text=_truncate(text),
                        seq=self.next_seq(),
                        command="load-conversation",
                    )
                )
            self.turns.append(
                StepNode(
                    actor=actor.name,
                    command="load-conversation",
                    depth=0,
                    seq=self.next_seq(),
                    detail=(
                        "restored — called flows from before the save are not in "
                        "the session file"
                    ),
                )
            )

    def to_json(self) -> list[dict]:
        with self.lock:
            return [node.to_json() for node in self.turns]


class _TeeStdout:
    """`sys.stdout`, with an optional per-thread capture buffer alongside it.

    A thread with no sink installed behaves exactly like the real stdout. One
    with a sink gets every write in its buffer *and* on the terminal, so a
    captured turn is still visible to whoever is running the server.
    """

    def __init__(self, real) -> None:
        self._real = real
        self._local = threading.local()

    # -- the stdout interface the print path needs -------------------------

    def write(self, text: str) -> int:
        sink = getattr(self._local, "sink", None)
        if sink is not None:
            sink.write(text)
        return self._real.write(text)

    def flush(self) -> None:
        self._real.flush()

    def isatty(self) -> bool:
        return self._real.isatty()

    def fileno(self) -> int:
        return self._real.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._real, "encoding", "utf-8")

    # -- capture ----------------------------------------------------------

    @contextlib.contextmanager
    def capture(self):
        """Collect this thread's stdout into a buffer for the duration.

        Nesting is safe: the previous sink is restored on exit, and a caller that
        wants one command's share of the output reads a slice by offset rather
        than installing a second buffer.
        """
        buffer = io.StringIO()
        previous = getattr(self._local, "sink", None)
        self._local.sink = buffer
        try:
            yield buffer
        finally:
            self._local.sink = previous


def install_tee() -> _TeeStdout:
    """Put one tee on `sys.stdout` and return it; idempotent."""
    if isinstance(sys.stdout, _TeeStdout):
        return sys.stdout
    tee = _TeeStdout(sys.stdout)
    sys.stdout = tee
    return tee

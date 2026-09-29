"""One scenario run, driven as a `Runtime` flow and recorded as a flow tree.

A library-runtime scenario is a generator: it yields an `InputRequest` wherever
it needs a human answer and resumes when the answer is sent back in. That is
exactly the shape an HTTP host wants, and it is what `drive_flow`'s docstring
describes as the alternative to its own blocking loop -- `next(flow)` runs up to
the first request, `flow.send(answer)` resumes it up to the next one, so a flow
stays parked between requests with no `input()` anywhere.

So there is no stepping loop here and no instruction pointer. `WebRuntime` is an
ordinary `Runtime` that records what each command did on its way through, and
`RuntimeChatSession` holds the parked generator plus that recording. One POST
resumes the generator, runs every command the turn reaches -- including every
actor the turn calls -- and returns at the next request.
"""

from __future__ import annotations

import pathlib
import sys
import threading
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..actors import Actor
from ..data_structures import INSTRUCTIONS_RE
from ..goals import GOALS_STORE_KEY, snapshot as goals_snapshot
from ..interpreter import Interpreter
from ..library_runtime import (
    RESUMED_STORE_KEY,
    CommandExit,
    CommandRestart,
    DebugQuit,
    INPUT_TIMEOUT,
    InputRequest,
    Runtime,
)
from ..session import restore_interpreter, snapshot_interpreter
from .scenario import RuntimeScenarioSpec
from .tree import (
    DETAIL_TEXT_LIMIT,
    DETAILED_COMMANDS,
    GENERATING_COMMANDS,
    QUIET_COMMANDS,
    MessageNode,
    StepNode,
    TranscriptRecorder,
    _as_text,
    _truncate,
    new_assistant_text,
    new_history_text,
)

# Distinguishes "this was not a `system` command" from a system prompt of None.
_UNSET = object()


class SessionBusy(RuntimeError):
    """A turn is already running in this session."""


class TurnBudgetExceeded(RuntimeError):
    """A turn issued too many commands without asking for input."""


class RuntimeChatSessionError(RuntimeError):
    """The session was asked to do something its state does not allow."""


class BranchPointUnknown(LookupError):
    """No checkpoint stands in front of the message a rewrite or fork names."""


@dataclass
class Checkpoint:
    """Everything needed to put a session back in front of one reader message.

    A flow's position lives in a parked Python generator and cannot be captured,
    so going back means throwing that generator away and starting a fresh one
    against restored state -- exactly what resuming a saved session already
    does. A checkpoint is that saved state, held in memory instead of a file,
    taken at the moment the flow parks and paired with the point in the
    transcript the same moment sits at.

    `state` comes from `snapshot_interpreter`, whose actor states are deep
    copies, so one checkpoint can be restored any number of times. The store is
    copied one level deep, the same guarantee a session file gives.
    """

    state: dict
    turns_len: int
    command_counts: "Counter[str]" = field(default_factory=Counter)
    turn_count: int = 0
    # Filled in once the turn has run and the message exists to point at.
    message_seq: Optional[int] = None


class WebRuntime(Runtime):
    """`Runtime`, recording every command into a tree a UI can draw.

    The hook is `cmd_exec`, not `cmd`: `cmd` is only trace bookkeeping in front
    of `cmd_exec`, and a scenario is free to call `cmd_exec` directly (the
    `examples/evil_AI` flows do, throughout). `Runtime.trace_hook` is no use
    either -- it fires *before* the command runs, so it cannot carry what the
    command produced.

    Four `Runtime` methods reach past the interpreter and so need hooks of their
    own: `return_from` (unwinds directly), `deliver` (writes history and store
    directly, which is why a human answer never passes through `cmd_exec`),
    `append`, and `load_session`. `store_set` deliberately has none -- the store
    is re-read whole on every response, so a node per assignment would be noise.
    Anything else a scenario does to an actor's history by hand is invisible
    here: this tree is a log of commands, not a mirror of history.
    """

    def __init__(
        self,
        interpreter: Interpreter,
        start_actor_name: str,
        recorder: TranscriptRecorder,
        scenario_dir: Optional[pathlib.Path] = None,
        max_commands_per_turn: int = 400,
    ):
        # Never "debug": `debug_pause` holds at a `debug> ` prompt on stdin
        # before every command, which an HTTP handler cannot answer.
        super().__init__(interpreter, start_actor_name, mode="chat")

        self.recorder = recorder
        self.scenario_dir = scenario_dir
        self.max_commands_per_turn = max_commands_per_turn

        self._turn_buffer = None
        self._stdout_attributed = 0
        self._commands_this_turn = 0
        self._last_command_error: Optional[str] = None
        # The `MessageNode` the last visible generation became, if it became
        # one, so `show_reply` can mark that node rather than add a second.
        self._visible_message: Optional[MessageNode] = None

    # ------------------------------------------------------------------
    # turn boundaries
    # ------------------------------------------------------------------

    def begin_turn(self, buffer) -> None:
        self._turn_buffer = buffer
        self._stdout_attributed = 0
        self._commands_this_turn = 0
        self._last_command_error = None

    def end_turn(self) -> None:
        self.flush_stdout()
        self._turn_buffer = None

    def _stdout_length(self) -> int:
        if self._turn_buffer is None:
            return 0
        return len(self._turn_buffer.getvalue())

    def _stdout_slice(self, start: int, end: Optional[int] = None) -> str:
        if self._turn_buffer is None:
            return ""
        text = self._turn_buffer.getvalue()
        return text[start:end] if end is not None else text[start:]

    def flush_stdout(self) -> None:
        """Record output printed outside any command as its own step.

        A scenario prints between commands too -- a helper that shows the reply
        it just collected, or a slash-command handler answering `/help`. That
        text belongs in the transcript, attributed to nothing in particular.
        """
        if self._turn_buffer is None:
            return
        pending = self._stdout_slice(self._stdout_attributed)
        self._stdout_attributed = self._stdout_length()
        pending = pending.strip()
        if not pending:
            return
        if self._echoes_visible(pending):
            return
        self.recorder.append(
            StepNode(
                actor=self.working_actor_name,
                command="stdout",
                depth=self.recorder.depth,
                seq=self.recorder.next_seq(),
                detail="printed",
                text=_truncate(pending),
            )
        )

    def _echoes_visible(self, printed: str) -> bool:
        """Is this printed text just the visible generation, shown again?

        A flow that plays in a terminal too prints the reply it marked visible,
        because a terminal has no transcript to read it from. Here that reply is
        already a message, so printing it again would show it twice.
        """
        if self.last_visible is None:
            return False
        visible = (self.last_visible[1] or "").strip()
        return bool(visible) and (printed == visible or printed in visible)

    # ------------------------------------------------------------------
    # the command funnel
    # ------------------------------------------------------------------

    def cmd_exec(self, command: str, **kwargs):
        self._commands_this_turn += 1
        if self._commands_this_turn > self.max_commands_per_turn:
            raise TurnBudgetExceeded(
                f"This turn ran {self.max_commands_per_turn} commands without asking "
                f"for input. A flow driven over HTTP has to reach a `yield from "
                f"ask(...)` for the reader's turn to end."
            )

        recorder = self.recorder
        # Anything printed since the last command belongs to the scenario's own
        # Python, not to this command.
        self.flush_stdout()

        actor_name = self.working_actor_name
        actor = self.actor()
        history_before = len(actor.history.read(merged=False))
        depth = recorder.depth
        seq = recorder.next_seq()
        count = recorder.count_command(actor_name)
        mark = self._stdout_length()
        # Set by `Runtime.generate` before it calls through, and cleared after.
        visible = self.visible_generate
        # `Runtime.generate` sets `last_visible` only once the command returns,
        # so this is still the *previous* visible generation.
        had_visible = self.last_visible is not None
        system_before = actor.system_prompt if command == "system" else _UNSET

        try:
            result = super().cmd_exec(command, **kwargs)
        except Exception:
            detail = self._last_traceback_line()
            self._last_command_error = detail
            recorder.append(
                StepNode(
                    actor=actor_name,
                    command=command,
                    depth=depth,
                    seq=seq,
                    detail=self._detail(command, kwargs),
                    step=count,
                    error=detail,
                )
            )
            recorder.fail_open_frames(detail)
            raise

        printed = self._stdout_slice(mark).strip()
        self._stdout_attributed = self._stdout_length()

        if (
            system_before is not _UNSET
            and actor.system_prompt == system_before
            and len(actor.history.read(merged=False)) == history_before
        ):
            # A `system` that changed nothing is not a step worth a line.
            # Replaying a flow over restored state -- what resuming, rewriting
            # and forking all do -- re-issues the flow's opening `system`
            # against an actor that already holds that prompt, and
            # `set_system_prompt` leaves a non-empty history alone. Recorded, it
            # would show as a stray `system` in the middle of a conversation.
            return result

        if command == "run-actor":
            # A frame-opening command is never also a step. Depth comes off the
            # open-frame stack rather than the callstack so the tree stays
            # self-consistent even if the two have drifted.
            recorder.open_flow(
                actor=str(kwargs.get("actor_name", "?")),
                depth=depth + 1,
                seq=seq,
                store=kwargs.get("store"),
            )
            return result

        generated = (
            new_assistant_text(actor, history_before)
            if command in GENERATING_COMMANDS
            else None
        )
        is_main_turn = (actor_name == self.main_actor_name) and (depth == 0)
        if visible:
            # Replaced just below when this generation becomes a message.
            self._visible_message = None

        if visible and (generated is not None) and is_main_turn:
            self._visible_message = MessageNode(
                actor=actor_name,
                role="assistant",
                text=generated,
                seq=seq,
                command=command,
                step=count,
            )
            recorder.append(self._visible_message)
            return result

        if (
            command == "print-latest"
            and is_main_turn
            and not had_visible
            and printed
        ):
            # A scenario that shows its replies with `show_latest()` and never
            # marks a generation visible still has a conversation to draw. The
            # `had_visible` guard means this can never double up on a
            # `generate(visible=True)`.
            recorder.append(
                MessageNode(
                    actor=actor_name,
                    role="assistant",
                    text=_truncate(printed),
                    seq=seq,
                    command=command,
                    step=count,
                )
            )
            return result

        recorder.append(
            StepNode(
                actor=actor_name,
                command=command,
                depth=depth,
                seq=seq,
                detail=self._detail(command, kwargs),
                detail_text=self._detail_text(command, kwargs, actor, history_before),
                text=generated if generated is not None else (printed or None),
                step=count,
            )
        )
        return result

    # ------------------------------------------------------------------
    # the methods that bypass the interpreter
    # ------------------------------------------------------------------

    def return_from(self, actor_name: str):
        """Close the frame `actor_name` opened, however control is leaving it.

        `call_actor` returns control from a `finally`, so this runs while an
        exception is propagating too -- which is how a failed sub-flow's frame
        gets marked. `unwind_actor` then calls `fill_variable`, and
        `Actor.get_latest_output` *raises* for a callee that produced no
        assistant or system message; inside that `finally` the raise would
        replace the real exception, so it is caught and recorded instead.

        (`get_latest_output` counts system messages, so a sub-flow that only did
        `refresh(); system(...)` fills its caller's store variable with its own
        system prompt rather than raising.)
        """
        propagating = sys.exc_info()[1]
        in_flight = (propagating is not None) or (self._last_command_error is not None)
        status = "failed" if in_flight else "returned"
        # Prefer the exception actually leaving the sub-flow. A pure-Python
        # failure never passed through `cmd_exec`, so this is the only place its
        # cause is visible.
        error = None
        if in_flight:
            error = self._last_command_error
            if error is None:
                error = f"{type(propagating).__name__}: {propagating}"

        try:
            return super().return_from(actor_name)
        except Exception as exc:
            status = "failed"
            if error is None:
                error = f"{type(exc).__name__}: {exc}"
            if not in_flight:
                raise
            # Already unwinding: this is a consequence of the real failure, and
            # raising here would replace it.
            return self.working_actor
        finally:
            self.recorder.close_flow(
                actor_name,
                status=status,
                error=error,
                store_reader=self.read_store,
            )
            self.recorder.reconcile(
                len(self.interpreter.callstack) - 1,
                store_reader=self.read_store,
            )

    def deliver(self, request: InputRequest, answer: str) -> str:
        """Apply a human answer and record it as the reader's turn.

        The node carries the raw answer, not the `enclosing_prompt`-wrapped text
        the model sees: the wrapper is the scenario talking to itself.
        """
        result = super().deliver(request, answer)

        recorder = self.recorder
        depth = recorder.depth
        seq = recorder.next_seq()
        if (request.actor_name == self.main_actor_name) and (depth == 0):
            recorder.append(
                MessageNode(
                    actor=request.actor_name,
                    role="user",
                    text=_truncate(answer),
                    seq=seq,
                    command="human-input",
                    step=recorder.command_counts.get(request.actor_name),
                )
            )
        else:
            suffix = f" → {request.store}" if request.store else ""
            recorder.append(
                StepNode(
                    actor=request.actor_name,
                    command="human-input",
                    depth=depth,
                    seq=seq,
                    detail=f"human input{suffix}",
                    text=_truncate(answer),
                )
            )
        return result

    def show_reply(self) -> Optional[str]:
        """Mark the reply the flow chose to show, which is what live mode draws.

        The usual case is a visible generation by the main actor at depth 0,
        which is already a `MessageNode`: it is flagged rather than duplicated.
        A reply generated anywhere else (another actor, or inside a called
        frame) was recorded as a step, so it gets a message of its own at the
        top level, where the conversation is drawn. The printed copy is
        attributed here, never left for `flush_stdout` to record as a stray step.
        """
        self.flush_stdout()
        reply = super().show_reply()
        self._stdout_attributed = self._stdout_length()
        if reply is None:
            return None

        node = self._visible_message
        if node is not None and node.text == reply:
            with self.recorder.lock:
                node.shown = True
            return reply

        recorder = self.recorder
        actor_name = self.last_visible[0] if self.last_visible else self.working_actor_name
        self._visible_message = MessageNode(
            actor=actor_name,
            role="assistant",
            text=_truncate(reply),
            seq=recorder.next_seq(),
            command="show-reply",
            shown=True,
        )
        recorder.append_turn(self._visible_message)
        return reply

    def clear_visible(self) -> None:
        super().clear_visible()
        self._visible_message = None

    def append(self, text: str):
        result = super().append(text)
        self.recorder.append(
            StepNode(
                actor=self.working_actor_name,
                command="append",
                depth=self.recorder.depth,
                seq=self.recorder.next_seq(),
                detail="to history",
                text=_truncate(_as_text(text)),
            )
        )
        return result

    def unwind_working_actor(self) -> Actor:
        result = super().unwind_working_actor()
        self.recorder.reconcile(
            len(self.interpreter.callstack) - 1,
            store_reader=self.read_store,
        )
        return result

    def load_session(self, path=None, session_id=None) -> str:
        """Restore a session, then make it a state a fresh flow can start on.

        A session file holds histories, the store, the waiting store and the
        callstack -- nothing of the flow's own position, which lives in a Python
        generator. So resuming means starting a flow again, and the restored
        state has to look like a flow's starting state: the callstack back to
        just the main actor, and no variables still waiting on frames that no
        longer exist. A save taken inside a called actor would otherwise run the
        new flow against the wrong working actor, with every depth off by one.
        """
        loaded_id = super().load_session(path=path, session_id=session_id)
        self.reset_for_replay()
        self.recorder.reset()
        self.recorder.rebuild_from_history(self.main_actor, INSTRUCTIONS_RE)
        return loaded_id

    def reset_for_replay(self) -> None:
        """Make restored state something a fresh flow can start on.

        Shared by every way of going back: loading a session file, and rewinding
        to a checkpoint. See `load_session` for why the callstack and the waiting
        store have to be normalized rather than left as the saved state had them.
        """
        self.interpreter.callstack = [self.main_actor_name]
        self.interpreter.waiting_store.clear()
        # A countdown belongs to the generator that started it, and every path
        # through here discards that generator.
        self.interpreter.clear_wait()
        self.working_actor = self.interpreter.actor_fetch(self.main_actor_name)
        self.clear_visible()
        self.store_set(RESUMED_STORE_KEY, True)

    # ------------------------------------------------------------------
    # checkpoints
    # ------------------------------------------------------------------

    def checkpoint(self, session_id: str) -> Checkpoint:
        """Capture the state and the transcript position, as one pair.

        Both halves have to be read at the same moment: a checkpoint whose state
        is a turn older than its transcript mark would restore a conversation
        the transcript still shows the rest of.
        """
        turns_len, counts = self.recorder.mark()
        return Checkpoint(
            state=snapshot_interpreter(self.interpreter, session_id),
            turns_len=turns_len,
            command_counts=counts,
        )

    def rewind_to(self, checkpoint: Checkpoint) -> None:
        """Put this runtime back at `checkpoint`, dropping everything after it."""
        restore_interpreter(self.interpreter, checkpoint.state)
        self.reset_for_replay()
        self.recorder.truncate(checkpoint.turns_len, checkpoint.command_counts)

    def branch_from(self, checkpoint: Checkpoint, turns: list) -> None:
        """Start this runtime on another session's `checkpoint` and transcript.

        The same restore as `rewind_to`, except the transcript is adopted from
        elsewhere rather than cut back: this runtime has no history of its own to
        cut.
        """
        restore_interpreter(self.interpreter, checkpoint.state)
        self.reset_for_replay()
        self.recorder.adopt(turns, checkpoint.command_counts)

    # ------------------------------------------------------------------
    # detail lines
    # ------------------------------------------------------------------

    def read_store(self, name: str) -> Optional[str]:
        if not self.interpreter.store.has(name):
            return None
        return _as_text(self.interpreter.store.get(name))

    @staticmethod
    def _last_traceback_line() -> str:
        formatted = traceback.format_exc(limit=3).strip().splitlines()
        return formatted[-1] if formatted else "unknown error"

    def _detail(self, command: str, kwargs: dict) -> str:
        """A short, honest line about what the command was given.

        Reads the keyword arguments a flow passed, where the JSON path read the
        fields of a parsed instruction. Never raises: a detail line must not be
        able to break a run.
        """
        if command in QUIET_COMMANDS:
            return ""
        try:
            if command == "system":
                return self._prompt_label(kwargs.get("prompt"))
            if command in GENERATING_COMMANDS:
                prompt = kwargs.get("prompt")
                return self._prompt_label(prompt) if prompt else "from history"
            if command == "input-from":
                for attribute, label in (
                    ("input_from_actor", "from actor"),
                    ("input_from_store", "from store"),
                    ("input_from_file", "from file"),
                ):
                    value = kwargs.get(attribute)
                    if value:
                        store = kwargs.get("store")
                        suffix = f" → {store}" if store else ""
                        return f"{label} {self._prompt_label(value)}{suffix}"
                return "human input"
            if command == "run-actor":
                store = kwargs.get("store")
                return f"→ {store}" if store else ""
            if command == "assign":
                return (
                    f"{kwargs.get('var_name', '?')} = "
                    f"{_truncate(_as_text(kwargs.get('value', '')), 120)}"
                )
            if command == "agent":
                return (
                    f"workspace {kwargs.get('workspace', '.')} · "
                    f"limit {kwargs.get('request_limit', '?')}"
                )
            if command == "write":
                return str(kwargs.get("path", ""))
            if command == "wait":
                return f"{kwargs.get('seconds', '?')}s"
        except Exception:
            return ""
        return ""

    def _detail_text(
        self,
        command: str,
        kwargs: dict,
        actor: Actor,
        history_before: int,
    ) -> Optional[str]:
        """The whole text the command was handed, for a collapsible block.

        `_detail` names a prompt; this is the prompt. A `system` or an
        `input-from` is nearly always written as a path, and a file name says
        nothing about what the actor was actually given -- which for reading a
        scenario back is the only thing that matters.

        Read off the actor after the command ran, rather than by resolving the
        path again here: `exec_SYSTEM` and `exec_INPUT_FROM` put the resolved
        text where it belongs, and reading it back is both simpler than
        reimplementing `parse_prompt_object` and honest about enclosing prompts
        and store lookups, which have no file behind them at all.

        Never raises, for the same reason `_detail` does not: a detail line must
        not be able to break a run.
        """
        if command not in DETAILED_COMMANDS:
            return None
        try:
            if command == "system":
                # The parsed prompt, which `exec_SYSTEM` has just set.
                return _truncate(_as_text(actor.system_prompt), DETAIL_TEXT_LIMIT) or None
            # `input-from` appends its resolved input to history, unless a
            # `store` took it instead (and `history` did not also ask for it).
            appended = new_history_text(actor, history_before)
            if appended:
                return appended
            store = kwargs.get("store")
            if store:
                value = self.read_store(str(store))
                if value:
                    return _truncate(value, DETAIL_TEXT_LIMIT)
        except Exception:
            return None
        return None

    def _prompt_label(self, value) -> str:
        """Prompt paths show as a scenario-relative name, not an absolute path."""
        text = _as_text(value)
        if not text:
            return ""
        try:
            path = pathlib.Path(text)
            if path.is_absolute() and path.exists():
                if self.scenario_dir is not None:
                    try:
                        return str(path.relative_to(self.scenario_dir))
                    except ValueError:
                        pass
                return path.name
        except OSError:
            pass
        return _truncate(text, 160)


class RuntimeChatSession:
    """A parked flow generator plus the transcript recorded from it."""

    MAX_COMMANDS_PER_TURN = 400

    # Each checkpoint holds a deep copy of every actor's history, so keeping one
    # per reader message costs memory that grows with the square of the
    # conversation. Past this many, the oldest are dropped: those messages stop
    # being rewritable, which `branch_points` reports, rather than the session
    # growing without bound.
    MAX_CHECKPOINTS = 50
    # How early a timeout may run: the browser counts down from a reading taken
    # when the response was built, so its call can arrive a little ahead.
    TIMEOUT_TOLERANCE = 1.0
    # How long a timeout call waits for a turn already running (typically the
    # backend's own timeout turn) before answering with the session as it is.
    TIMEOUT_LOCK_WAIT = 180.0

    def __init__(
        self,
        spec: RuntimeScenarioSpec,
        pipeline,
        storage_dir: str | pathlib.Path,
        tee,
        title: Optional[str] = None,
    ):
        self.id = uuid.uuid4().hex[:7]
        self.spec = spec
        self.tee = tee
        self.title = title or "New session"
        self.storage_dir = pathlib.Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        actors = spec.build_actors(self.storage_dir, pipeline)
        for actor in actors:
            self._forbid_terminal_input(actor)

        self.interpreter = Interpreter(
            actors,
            main_actor_name=spec.main_actor_name,
            # Named explicitly so `save_session` and the app's saved-session
            # listing look in one directory.
            conversations_dir=self.storage_dir / "conversations",
        )
        # Streaming reaches the pipeline's `generate_stream`, which the
        # llm_utils pipelines do not define; setting the hook against one of
        # those would raise on the first `generate`, so it stays unset.
        pipelines = pipeline.values() if isinstance(pipeline, dict) else [pipeline]
        if all(hasattr(p, "generate_stream") for p in pipelines):
            self.interpreter.on_generate_delta = self._on_delta

        self.recorder = TranscriptRecorder()
        self.runtime = WebRuntime(
            self.interpreter,
            spec.main_actor_name,
            recorder=self.recorder,
            scenario_dir=spec.dir,
            max_commands_per_turn=self.MAX_COMMANDS_PER_TURN,
        )
        spec.register_commands(self.runtime)

        self._flow = None
        self._pending_request: Optional[InputRequest] = None
        self._parked_at = 0.0
        self._turn_lock = threading.Lock()
        self._timeout_timer: Optional[threading.Timer] = None

        self.deltas: list[dict] = []
        self.status = "new"
        self.error: Optional[str] = None
        self.exit_message: Optional[str] = None
        self.saved_path: Optional[str] = None
        self.resumed_from: Optional[str] = None
        self.forked_from: Optional[str] = None
        self.forked_at: Optional[int] = None
        self.turn_count = 0

        # One per reader message that can be rewritten, oldest first, plus the
        # one for the turn currently being waited on -- which is not in the list
        # yet, because the message it belongs in front of does not exist.
        self.checkpoints: list[Checkpoint] = []
        self._parked_checkpoint: Optional[Checkpoint] = None
        self._transcript_replaced = False

    # ------------------------------------------------------------------ input

    @staticmethod
    def _forbid_terminal_input(actor: Actor) -> None:
        """Make a stdin read fail loudly instead of hanging the request.

        A flow asks for a human answer by yielding, and `Runtime.deliver` applies
        the answer without going near `prompt_user`. So the only way to reach
        this is an `input-from` command carrying a `human_prompt`, which belongs
        to the JSON runtime. Bound per instance, so a `Scorer` stays a `Scorer`.
        """

        def prompt_user(prompt=None, store_to_history=True):
            raise RuntimeChatSessionError(
                f"{actor.name} asked for terminal input: an `input-from` command with "
                f"a `human_prompt`. A flow driven over HTTP must suspend instead, "
                f"with `yield from ask(runtime, ...)`."
            )

        actor.prompt_user = prompt_user

    def _on_delta(self, actor_name: str, event: dict) -> None:
        self.deltas.append({"actor": actor_name, "event": event})

    # --------------------------------------------------------------- driving

    def start(self) -> "RuntimeChatSession":
        self.status = "running"
        self._flow = self.spec.make_flow(self.runtime, resumed=False)
        self._pump(self._advance)
        return self

    def resume(self, session_id: str) -> "RuntimeChatSession":
        """Load a saved session and start the flow again on restored state."""
        self.runtime.load_session(session_id=session_id)
        # `load_session` rebuilt the transcript from history, so every mark a
        # checkpoint holds points into a list that no longer exists.
        self.checkpoints.clear()
        self.resumed_from = session_id
        if self.title == "New session":
            self.title = f"Resumed {session_id}"
        self.status = "running"
        self._flow = self.spec.make_flow(self.runtime, resumed=True)
        self._pump(self._advance)
        return self

    def awaiting_input_now(self) -> bool:
        return self._pending_request is not None

    def send_input(self, text: str) -> "RuntimeChatSession":
        # Non-blocking on purpose: queueing a turn would deliver the reader's
        # message into a request the UI never made.
        if not self._turn_lock.acquire(blocking=False):
            raise SessionBusy(f"Session {self.id} is already running a turn.")
        try:
            if not self.awaiting_input_now():
                raise RuntimeChatSessionError(
                    f"Session {self.id} is {self.status}, not waiting for input"
                )
            self._pending_request = None
            self.turn_count += 1
            if self.turn_count == 1 and self.title == "New session":
                first_line = text.strip().splitlines()[0] if text.strip() else "Untitled"
                self.title = _truncate(first_line, 60)
            self._run_turn(text)
        finally:
            self._turn_lock.release()
        return self

    def input_timeout_remaining(self) -> Optional[float]:
        """Seconds until the pending request times out, or None when it has no timeout."""
        request = self._pending_request
        if request is None or request.timeout is None:
            return None
        return max(0.0, request.timeout - (time.monotonic() - self._parked_at))

    def send_timeout(self, expected: Optional[InputRequest] = None) -> "RuntimeChatSession":
        """Run the timeout turn if the pending timed request is due; otherwise do nothing.

        Both the backend's own timer and the browser call this, so it is
        idempotent: whichever arrives second (or early) finds nothing due and
        leaves the session as it is. `expected` pins the call to one request, so
        a timer set for a request that was answered meanwhile does nothing. It
        waits for a turn in progress rather than failing, since that turn is
        most likely the other caller's timeout. No reader message is delivered,
        so this is a turn without a branch point.
        """
        if not self._turn_lock.acquire(timeout=self.TIMEOUT_LOCK_WAIT):
            raise SessionBusy(f"Session {self.id} is still running a turn.")
        try:
            if expected is not None and self._pending_request is not expected:
                return self
            remaining = self.input_timeout_remaining()
            if remaining is None or remaining > self.TIMEOUT_TOLERANCE:
                return self
            self._pending_request = None
            self._run_turn(INPUT_TIMEOUT)
        finally:
            self._turn_lock.release()
        return self

    def _schedule_timeout(self) -> None:
        """Time out a timed request on the backend, so no browser has to be watching.

        Runs from `_pump`, under the turn lock; the timer's own call takes the
        lock afterwards and does nothing if its request is no longer pending.
        """
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None
        request = self._pending_request
        if request is None or request.timeout is None:
            return
        timer = threading.Timer(request.timeout, self._timeout_due, args=(request,))
        timer.daemon = True
        self._timeout_timer = timer
        timer.start()

    def _timeout_due(self, request: InputRequest) -> None:
        try:
            self.send_timeout(expected=request)
        except SessionBusy:
            pass

    def _run_turn(self, text: str) -> None:
        """Deliver one answer, keeping the checkpoint the turn started from.

        Read before the pump, because the pump parks again and takes the next
        turn's checkpoint over it.
        """
        started_from = self._parked_checkpoint
        self._pump(lambda: self._flow.send(text))
        self._commit_checkpoint(started_from)

    def _advance(self):
        return next(self._flow)

    def _pump(self, step: Callable[[], InputRequest]) -> None:
        """Run the generator until it wants an answer, or it is over.

        The one place the flow is resumed, so every way a flow can end is
        handled in one place: a yielded request parks it, `StopIteration` and
        `CommandExit` finish it, `CommandRestart` (a `/load` handler, which `ask`
        re-raises rather than swallowing) replaces the generator, and anything
        else is an error that kills it -- a generator that has raised out cannot
        be resumed.
        """
        self.error = None
        with self.tee.capture() as buffer:
            self.runtime.begin_turn(buffer)
            try:
                while True:
                    try:
                        self._pending_request = step()
                        self._parked_at = time.monotonic()
                        self.status = "awaiting_input"
                        self._park_checkpoint()
                        self._schedule_timeout()
                        return
                    except CommandRestart:
                        # A `/load` handler replaced the whole session under us.
                        self.checkpoints.clear()
                        self._transcript_replaced = True
                        self._flow = self.spec.make_flow(self.runtime, resumed=True)
                        step = self._advance
                        continue
            except StopIteration:
                self._finish("The flow finished.")
            except CommandExit:
                self._finish("The scenario exited.")
            except DebugQuit as quit_signal:
                self._finish(str(quit_signal) or "The run was stopped.")
            except TurnBudgetExceeded as exc:
                self._fail(str(exc))
            except RuntimeChatSessionError as exc:
                self._fail(str(exc))
            except Exception:
                self._fail(WebRuntime._last_traceback_line())
            finally:
                self.runtime.end_turn()

    def _finish(self, message: str) -> None:
        self._pending_request = None
        self._parked_checkpoint = None
        self._flow = None
        self.status = "finished"
        self.exit_message = message
        self.recorder.reconcile(0, store_reader=self.runtime.read_store)

    def _fail(self, detail: str) -> None:
        self._pending_request = None
        self._parked_checkpoint = None
        self._flow = None
        self.status = "error"
        self.error = detail
        self.recorder.fail_open_frames(detail)

    # -------------------------------------------------------------- branching

    def _park_checkpoint(self) -> None:
        """Checkpoint the state the turn about to be asked for will start from.

        Only a request the main actor makes at depth 0 qualifies. That is the
        one whose answer becomes a chat bubble, and so the only one a rewrite
        could be asked for; a mid-frame `ask` is a sub-flow's own question, and
        its frame is half-built, so the transcript has no boundary there to cut
        at. The interpreter's callstack is checked as well as the recorder's
        depth, because the two can drift and a rewind normalizes the callstack
        rather than restoring it.
        """
        request = self._pending_request
        self._parked_checkpoint = None
        if request is None or request.actor_name != self.spec.main_actor_name:
            return
        if self.recorder.depth != 0 or len(self.interpreter.callstack) != 1:
            return
        checkpoint = self.runtime.checkpoint(self.id)
        checkpoint.turn_count = self.turn_count
        self._parked_checkpoint = checkpoint

    def _commit_checkpoint(self, checkpoint: Optional[Checkpoint]) -> None:
        """Keep a checkpoint only once the message it stands in front of exists.

        A slash command answers without delivering anything -- `ask` runs the
        handler and loops back to the same `yield` -- so the transcript is where
        it was and there is no message for a rewrite to name. The same applies
        when the flow was replaced mid-turn, which is why one pump marks the
        transcript as no longer the one the checkpoint was measured against.
        """
        # Cleared first and unconditionally: the flag belongs to the turn that
        # just ran, so leaving it set when that turn had no checkpoint would
        # suppress the next turn's instead.
        replaced, self._transcript_replaced = self._transcript_replaced, False
        if checkpoint is None or replaced:
            return
        node = self.recorder.node_at(checkpoint.turns_len)
        if isinstance(node, MessageNode) and node.role == "user":
            checkpoint.message_seq = node.seq
            self.checkpoints.append(checkpoint)
            del self.checkpoints[: -self.MAX_CHECKPOINTS]

    def _checkpoint_index(self, message_seq: int) -> int:
        for index, checkpoint in enumerate(self.checkpoints):
            if checkpoint.message_seq == message_seq:
                return index
        raise BranchPointUnknown(
            f"Message {message_seq} is not a reader message this session can "
            f"branch at. Only the reader's own messages can be, and only ones "
            f"sent since the session was started or resumed."
        )

    def checkpoint_for(self, message_seq: int) -> Checkpoint:
        """The checkpoint taken just before the reader message `message_seq`."""
        return self.checkpoints[self._checkpoint_index(message_seq)]

    def branch_points(self) -> list[int]:
        """The reader messages that can be rewritten or forked from."""
        return [c.message_seq for c in self.checkpoints if c.message_seq is not None]

    def rewrite(self, message_seq: int, text: str) -> "RuntimeChatSession":
        """Replace one reader message and run the conversation on from there.

        Everything the original message led to is dropped -- later turns
        included. A rewrite is this conversation taking a different turn, not a
        variant kept beside the old one; `fork_from` is the other choice.

        Allowed whatever the session's status is, as long as no turn is in
        flight: rewriting the message that broke a flow is the natural way out
        of a failed session, and the flow being dead is no obstacle, since a
        rewind builds a new one either way.
        """
        if not self._turn_lock.acquire(blocking=False):
            raise SessionBusy(f"Session {self.id} is already running a turn.")
        try:
            index = self._checkpoint_index(message_seq)
            checkpoint = self.checkpoints[index]

            # Rewind first: `restore_interpreter` puts the previous state back if
            # any actor rejects its saved state, and dropping the checkpoints
            # before that would leave nothing to try again with.
            self.runtime.rewind_to(checkpoint)
            # This checkpoint and every later one describe turns that have just
            # stopped existing. The replayed turn parks and checkpoints itself.
            del self.checkpoints[index:]
            self.turn_count = checkpoint.turn_count
            self.exit_message = None
            self._start_replayed_flow(f"Rewriting message {message_seq}")
            self.turn_count += 1
            self._run_turn(text)
        finally:
            self._turn_lock.release()
        return self

    def fork_from(
        self,
        source: "RuntimeChatSession",
        message_seq: int,
        text: Optional[str] = None,
    ) -> "RuntimeChatSession":
        """Start this session as a branch of `source` at one of its messages.

        `source` is not touched: this session gets its own actors, its own
        interpreter and a deep copy of the transcript up to the branch point, so
        both conversations run on from there independently. That is what makes a
        fork the right answer when the message being changed has turns after it
        worth keeping.

        With no `text`, the fork parks where the original was asked for that
        message, and the reader answers it through the composer like any other
        turn.
        """
        checkpoint = source.checkpoint_for(message_seq)
        # This session is already in the app's index by the time it is filled in,
        # so it takes the same lock every other way of running a turn does.
        if not self._turn_lock.acquire(blocking=False):
            raise SessionBusy(f"Session {self.id} is already running a turn.")
        try:
            self.runtime.branch_from(
                checkpoint, source.recorder.prefix(checkpoint.turns_len)
            )
            self.forked_from = source.id
            self.forked_at = message_seq
            if self.title == "New session":
                self.title = f"{source.title} — fork"
            self.turn_count = checkpoint.turn_count
            self._start_replayed_flow(f"Forking session {source.id}")
            if text is not None:
                self.turn_count += 1
                self._run_turn(text)
        finally:
            self._turn_lock.release()
        return self

    def _start_replayed_flow(self, what: str) -> None:
        """Run a fresh flow up to the request the restored state was taken at.

        The flow has to reach its own `ask` before anything can be delivered
        into it -- the state says what the conversation is, not where in the
        scenario's Python it stands. `RESUMED_STORE_KEY` (set by
        `reset_for_replay`) is what keeps the prologue from running a second
        time.
        """
        self.status = "running"
        self._pending_request = None
        self._flow = self.spec.make_flow(self.runtime, resumed=True)
        self._pump(self._advance)
        if not self.awaiting_input_now():
            raise RuntimeChatSessionError(
                f"{what} left the flow {self.status}"
                + (f": {self.error}" if self.error else "")
                + ". There is nowhere to deliver a message."
            )

    # --------------------------------------------------------------- session

    def save(self) -> str:
        path = self.interpreter.save_session(session_id=self.id)
        self.saved_path = str(path)
        return self.saved_path

    def discard(self) -> None:
        """Drop this run: the parked flow, its checkpoints and its transcript.

        Taken under the same non-blocking turn lock as every other way of
        running a turn, so a session cannot be torn down from under a request
        that is mid-generation; the caller gets `SessionBusy` and can try again
        when the turn lands. The lock is released afterwards even though nothing
        should reach this session again -- the app drops its only reference on
        the way out, and a lock left held would be a lie about why.

        Everything a checkpoint holds is a deep copy of every actor's history,
        which is the bulk of a session's memory, so this is dropped explicitly
        rather than left to the reference count of whatever else may still be
        looking at the object.
        """
        if not self._turn_lock.acquire(blocking=False):
            raise SessionBusy(f"Session {self.id} is running a turn.")
        try:
            if self._timeout_timer is not None:
                self._timeout_timer.cancel()
                self._timeout_timer = None
            self._pending_request = None
            self._parked_checkpoint = None
            self._flow = None
            self.checkpoints.clear()
            self.recorder.reset()
            self.status = "discarded"
        finally:
            self._turn_lock.release()

    def store_json(self) -> list[dict]:
        store = self.interpreter.store.store
        waiting = dict(self.interpreter.waiting_store)
        rows = []
        for name, value in store.items():
            if name == GOALS_STORE_KEY:
                # Shown structured under `goals`; as a row it is a JSON slice.
                continue
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

    def histories_json(self) -> list[dict]:
        """Every actor's full history, main actor first, for the actor view.

        Unmerged, so each message is one row as the actor received it; the
        transcript tree is a log of commands, and this is the other half -- what
        the actor actually holds, including anything a flow wrote by hand.
        """
        main = self.spec.main_actor_name
        names = sorted(self.interpreter.actors, key=lambda name: name != main)
        return [
            {
                "name": name,
                "type": type(self.interpreter.actors[name]).__name__,
                "messages": [
                    {"role": message["role"], "content": message["content"]}
                    for message in self.interpreter.actors[name].history.read(merged=False)
                ],
            }
            for name in names
        ]

    def to_json(self) -> dict:
        request = self._pending_request
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "scenario": self.spec.to_json(),
            "main_actor": self.spec.main_actor_name,
            "working_actor": self.runtime.working_actor_name,
            "callstack": list(self.interpreter.callstack),
            # A request marked `content=False` is a bare turn-taking cue that
            # exists only because a terminal has to print something before
            # calling `input()`. A console-style UI supplies its own prompting
            # affordance, so the cue is withheld -- but the session is still
            # waiting, which is why `awaiting_input` is read off the request and
            # not off the prompt.
            "waiting_prompt": (
                request.prompt if (request is not None and request.content) else None
            ),
            "awaiting_input": request is not None,
            # Seconds until a timed request gives up. The backend times it out
            # itself; the browser posts to the timeout route then to catch up.
            # None when the request waits indefinitely.
            "input_timeout": (
                None if self.input_timeout_remaining() is None
                else round(self.input_timeout_remaining(), 3)
            ),
            "turn_count": self.turn_count,
            "exit_message": self.exit_message,
            "error": self.error,
            "saved_path": self.saved_path,
            "resumed_from": self.resumed_from,
            "forked_from": self.forked_from,
            "forked_at": self.forked_at,
            # The reader messages a rewrite or a fork can name. A session-level
            # list rather than a flag on each node: which messages can be
            # branched at is a fact about the checkpoints this session happens to
            # hold, not about the transcript, and a resumed session's messages
            # are real messages with no checkpoint in front of them.
            "branch_points": self.branch_points(),
            "turns": self.recorder.to_json(),
            "histories": self.histories_json(),
            "store": self.store_json(),
            "goals": goals_snapshot(self.interpreter.store.store),
            # Runtime actors have no instruction list, so there is no step
            # pointer to report; this is how many commands each actor has run.
            "step_pointers": {
                name: self.recorder.command_counts.get(name, 0)
                for name in self.interpreter.actors
            },
            # Seconds remaining rather than an absolute deadline: the browser's
            # clock need not agree with the host's, so the client counts down
            # from the reading it was handed instead of from a shared instant.
            "wait": {
                "active": self.interpreter.wait_active,
                "remaining": round(self.interpreter.wait_remaining, 3),
                "total": self.interpreter.wait_seconds,
            },
            "commands": sorted(self.runtime.commands),
        }

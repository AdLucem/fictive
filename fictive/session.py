"""Save and restore a whole interpreter session as one JSON file.

A session file records what is needed to resume a run with the same actors:
every actor's unmerged history, system prompt, step pointer and pending queue,
plus the interpreter's shared store, waiting store, callstack, and Bedrock RAG
session ids. It does not record instructions or pipelines. Those come from the
scenario the loading interpreter was built from, and its actor names must match
the file's exactly.

Files live under `<storage_dir>/conversations/<session_id>.json` by default,
which is also where the local RAG backend looks for past conversations.
"""

import contextlib
import dataclasses
import json
import os
import pathlib
import re
import tempfile
import uuid
from datetime import datetime, timezone

from .parser.commands import COND, CommandObj

SESSION_FORMAT = "fictive-session"
SESSION_VERSION = 1
CONVERSATIONS_DIR = "conversations"
SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def new_session_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def validate_session_id(session_id: str) -> str:
    """A session id becomes a file name, so it must be one plain path segment."""
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        raise ValueError(
            f"Invalid session id {session_id!r}: use letters, digits, '.', '_' "
            "and '-', starting with a letter or digit."
        )
    return session_id


def default_session_path(session_id: str) -> pathlib.Path:
    """The storage-dir-relative path of a session file."""
    return pathlib.Path(CONVERSATIONS_DIR) / f"{validate_session_id(session_id)}.json"


def command_to_dict(cmd: CommandObj) -> dict:
    """Inverse of `parse_command_dict`: a JSON-ready dict for a command object.

    Built field by field rather than with `dataclasses.asdict`, which would turn
    the command objects nested in a `cond` branch into dicts with no `cmd` key.
    """
    data = {"cmd": cmd.name}
    for field in dataclasses.fields(cmd):
        value = getattr(cmd, field.name)
        data[field.name] = str(value) if isinstance(value, pathlib.PurePath) else value

    if isinstance(cmd, COND):
        data["conditions"] = [
            {
                **{key: value for key, value in branch.items() if key not in ("commands", "block")},
                "commands": [
                    command_to_dict(inner) if isinstance(inner, CommandObj) else inner
                    for inner in branch.get("commands", [])
                ],
            }
            for branch in cmd.conditions
        ]
    return data


def snapshot_interpreter(interpreter, session_id: str) -> dict:
    return {
        "format": SESSION_FORMAT,
        "version": SESSION_VERSION,
        "session_id": validate_session_id(session_id),
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "main_actor": interpreter.main_actor_name,
        "callstack": list(interpreter.callstack),
        "waiting_store": dict(interpreter.waiting_store),
        "store": dict(interpreter.store.store),
        "rag_sessions": dict(interpreter.rag_sessions),
        "actors": {
            name: actor.state_dict() for name, actor in interpreter.actors.items()
        },
    }


def write_session_file(path, doc: dict) -> pathlib.Path:
    """Write `doc` as JSON, atomically, refusing values JSON cannot round-trip.

    There is deliberately no `default=str`: a store value that came back from a
    load as its string form would make it a different session.
    """
    for key, value in doc["store"].items():
        try:
            json.dumps(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(
                f"Cannot save session: store variable {key!r} holds a "
                f"{type(value).__name__}, which is not JSON-serializable."
            ) from exc
    try:
        text = json.dumps(doc, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"Cannot save session: {exc}") from exc

    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    return path


def check_session_doc(doc, source="session") -> None:
    if not isinstance(doc, dict) or doc.get("format") != SESSION_FORMAT:
        raise ValueError(f"{source} is not a fictive session file.")
    if doc.get("version") != SESSION_VERSION:
        raise ValueError(
            f"{source} has session format version {doc.get('version')!r}; "
            f"this fictive reads version {SESSION_VERSION}."
        )


def read_session_file(path) -> dict:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    check_session_doc(doc, path)
    return doc


def restore_interpreter(interpreter, doc: dict) -> None:
    """Replace the interpreter's session state with `doc`.

    All or nothing: if any actor rejects its saved state, the state from before
    the call is put back before the error propagates.
    """
    check_session_doc(doc)
    saved, present = set(doc["actors"]), set(interpreter.actors)
    if saved != present:
        raise ValueError(
            "Session actors do not match this interpreter's actors: "
            f"not in this interpreter {sorted(saved - present)}, "
            f"not in the session {sorted(present - saved)}."
        )
    unknown = [name for name in doc["callstack"] if name not in present]
    if unknown:
        raise ValueError(f"Session callstack names unknown actors: {unknown}.")

    previous = snapshot_interpreter(interpreter, interpreter.session_id)
    try:
        _apply_session(interpreter, doc)
    except Exception:
        _apply_session(interpreter, previous)
        raise


def _apply_session(interpreter, doc: dict) -> None:
    for name, state in doc["actors"].items():
        interpreter.actors[name].load_state_dict(state)
    interpreter.store.store = dict(doc["store"])
    interpreter.waiting_store = dict(doc["waiting_store"])
    interpreter.callstack = list(doc["callstack"])
    interpreter.rag_sessions = dict(doc.get("rag_sessions", {}))


def render_transcript(history) -> str:
    """Plain-text transcript of an unmerged history, without system messages."""
    lines = []
    for msg in history:
        if msg.get("role") == "system":
            continue
        content = msg.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        content = content.strip()
        if content:
            lines.append(f"{msg.get('role')}: {content}")
    return "\n\n".join(lines)

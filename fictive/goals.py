"""Scene goals: a tree of goals a flow pursues, kept in the runtime's store.

A scene starts with one root goal. Flow code (or the LLM planner, `plan`) adds
sub-goals beneath it; the tree is worked depth-first, so the deepest open goal
is the *focus* and pre-empts its ancestors until it closes. `inject` tells the
scene actor what the focus is through a hidden `(INSTRUCTIONS: ...)` turn, and
`judge` asks an LLM whether the focus has been achieved.

The whole tree is one JSON-serialisable dict under `GOALS_STORE_KEY`, so session
files and the web backend's rewrite/fork checkpoints carry it with no extra
code. Those checkpoints copy the store only one level deep, so this module
never hands out or mutates the stored dict: every read works on a deep copy and
every write stores a fresh one.

    root = goals.start_scene(rt, "Interrogate the boy about his nightly habits")
    yield from goals.plan(rt, "planner", goal_id=root)
    while goals.active(rt):
        yield from ask(rt, "boy> ")
        goals.tick(rt)
        yield from goals.judge(rt, "judge")
        goals.inject(rt)
        rt.generate(visible=True)
        rt.show_reply()
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable, Optional, Union

from .data_structures import format_instructions
from .library_runtime import Flow, Runtime, call_actor

GOALS_STORE_KEY = "_fictive_goals"

OPEN_STATUSES = ("pending", "active")
CLOSED_STATUSES = ("done", "failed", "abandoned")

DEFAULT_LIMITS = {
    # Levels of the tree, root included.
    "max_depth": 4,
    # Open children one goal may have at once.
    "max_open_children": 4,
    # Goals ever created in one scene, closed ones included.
    "max_goals": 40,
    # Turn budget given to planner-made goals that do not name one.
    "planner_turn_budget": 6,
    "max_events": 50,
    "max_notes": 10,
}

MAX_GOAL_TEXT = 300
SCENE_TAIL_CHARS = 6000
SNAPSHOT_EVENTS = 20

Template = Union[str, Callable[[list[dict]], str], None]


class GoalError(ValueError):
    """A goal operation that cannot apply to the current tree."""


class GoalLimitError(GoalError):
    """Adding a goal would exceed one of the tree's limits."""


class GoalOutputError(ValueError):
    """A planner or judge reply that is not the JSON object asked for."""


# ----------------------------------------------------------------------
# the tree
# ----------------------------------------------------------------------


class GoalTree:
    """Operations on one goal-tree dict. Knows nothing about the runtime.

    The constructor takes ownership of `state`; the runtime functions below
    always pass it a private copy.
    """

    def __init__(self, state: dict):
        self.state = state

    @classmethod
    def new(
        cls,
        text: str,
        *,
        criteria: Optional[str] = None,
        turn_budget: Optional[int] = None,
        limits: Optional[dict] = None,
    ) -> "GoalTree":
        tree = cls(
            {
                "version": 1,
                "root": None,
                "focus": None,
                "next_id": 1,
                "turn": 0,
                "limits": {**DEFAULT_LIMITS, **(limits or {})},
                "nodes": {},
                "events": [],
                "last_injected": None,
            }
        )
        tree.state["root"] = tree._create(
            text, parent=None, criteria=criteria, turn_budget=turn_budget,
            complete_with_children=False, source="flow", data=None,
        )
        tree._refocus()
        return tree

    # -- reading -------------------------------------------------------

    @property
    def nodes(self) -> dict:
        return self.state["nodes"]

    @property
    def limits(self) -> dict:
        return self.state["limits"]

    @property
    def turn(self) -> int:
        return self.state["turn"]

    @property
    def focus_id(self) -> Optional[str]:
        return self.state["focus"]

    def node(self, goal_id: str) -> dict:
        try:
            return self.nodes[goal_id]
        except KeyError:
            raise GoalError(f"No goal with id {goal_id!r}") from None

    def resolve(self, goal_id: Optional[str]) -> dict:
        """The named goal, or the focus when `goal_id` is None."""
        if goal_id is not None:
            return self.node(goal_id)
        if self.focus_id is None:
            raise GoalError("The scene has no open goal")
        return self.node(self.focus_id)

    def depth(self, goal_id: str) -> int:
        depth = 0
        node = self.node(goal_id)
        while node["parent"] is not None:
            depth += 1
            node = self.node(node["parent"])
        return depth

    def path(self, goal_id: Optional[str] = None) -> list[dict]:
        """Nodes from the root down to `goal_id` (default: the focus)."""
        if goal_id is None and self.focus_id is None:
            return []
        node = self.resolve(goal_id)
        chain = [node]
        while node["parent"] is not None:
            node = self.node(node["parent"])
            chain.append(node)
        return list(reversed(chain))

    def open_children(self, goal_id: str) -> list[dict]:
        return [
            self.nodes[c] for c in self.node(goal_id)["children"]
            if self.nodes[c]["status"] in OPEN_STATUSES
        ]

    # -- writing -------------------------------------------------------

    def add(
        self,
        text: str,
        *,
        parent: Optional[str] = None,
        index: Optional[int] = None,
        criteria: Optional[str] = None,
        turn_budget: Optional[int] = None,
        complete_with_children: bool = False,
        source: str = "flow",
        data: Optional[dict] = None,
    ) -> str:
        parent_node = self.resolve(parent)
        if parent_node["status"] not in OPEN_STATUSES:
            raise GoalError(f"Goal {parent_node['id']} is {parent_node['status']}; it cannot take sub-goals")
        if self.depth(parent_node["id"]) + 1 >= self.limits["max_depth"]:
            raise GoalLimitError(f"Goal {parent_node['id']} is already at the maximum depth")
        if len(self.open_children(parent_node["id"])) >= self.limits["max_open_children"]:
            raise GoalLimitError(f"Goal {parent_node['id']} already has the maximum number of open sub-goals")
        if len(self.nodes) >= self.limits["max_goals"]:
            raise GoalLimitError("The scene already has the maximum number of goals")

        goal_id = self._create(
            text, parent=parent_node["id"], criteria=criteria, turn_budget=turn_budget,
            complete_with_children=complete_with_children, source=source, data=data,
        )
        children = parent_node["children"]
        children.insert(len(children) if index is None else index, goal_id)
        self._refocus()
        return goal_id

    def close(self, goal_id: Optional[str], status: str, note: Optional[str] = None, kind: Optional[str] = None) -> str:
        if status not in CLOSED_STATUSES:
            raise GoalError(f"{status!r} is not a closing status")
        node = self.resolve(goal_id)
        if node["status"] not in OPEN_STATUSES:
            raise GoalError(f"Goal {node['id']} is already {node['status']}")
        self._close(node, status, note, kind or status)
        self._complete_parents(node)
        self._refocus()
        return node["id"]

    def add_note(self, text: str, goal_id: Optional[str] = None) -> None:
        node = self.resolve(goal_id)
        self._note(node, text)
        self._event("note", node["id"], text)

    def update(
        self,
        goal_id: str,
        *,
        text: Optional[str] = None,
        criteria: Optional[str] = None,
        turn_budget: Optional[int] = None,
        complete_with_children: Optional[bool] = None,
        data: Optional[dict] = None,
    ) -> None:
        node = self.node(goal_id)
        if text is not None:
            node["text"] = _clean_text(text)
        if criteria is not None:
            node["criteria"] = criteria
        if turn_budget is not None:
            node["turn_budget"] = turn_budget
        if complete_with_children is not None:
            node["complete_with_children"] = complete_with_children
        if data is not None:
            node["data"] = data

    def tick(self) -> list[dict]:
        """Advance one turn; fail the shallowest goal on the path whose budget ran out."""
        first_event = len(self.state["events"])
        self.state["turn"] += 1
        chain = self.path()
        for node in chain:
            node["turns"] += 1
        for node in chain:
            budget = node["turn_budget"]
            if budget is not None and node["turns"] >= budget:
                self.close(node["id"], "failed", f"Turn budget of {budget} used up", kind="budget")
                break
        return copy.deepcopy(self.state["events"][first_event:])

    # -- rendering -----------------------------------------------------

    def summary(self) -> str:
        lines: list[str] = []

        def walk(goal_id: str, depth: int) -> None:
            node = self.nodes[goal_id]
            marker = " <- focus" if goal_id == self.focus_id else ""
            budget = f", {node['turns']}/{node['turn_budget']} turns" if node["turn_budget"] else ""
            lines.append(f"{'  ' * depth}- [{goal_id}] ({node['status']}{budget}) {node['text']}{marker}")
            if node["criteria"]:
                lines.append(f"{'  ' * depth}    done when: {node['criteria']}")
            for child in node["children"]:
                walk(child, depth + 1)

        walk(self.state["root"], 0)
        return "\n".join(lines)

    def instruction_text(self, template: Template = None) -> Optional[str]:
        chain = self.path()
        if not chain:
            return None
        if callable(template):
            return template(copy.deepcopy(chain))

        focus = chain[-1]
        progress = f" [{focus['turns']}/{focus['turn_budget']} turns used]" if focus["turn_budget"] else ""
        fields = {
            "scene": " > ".join(node["text"] for node in chain[:-1]),
            "focus": focus["text"],
            "progress": progress,
            "criteria": focus["criteria"] or "",
        }
        if template is not None:
            return template.format(**fields)

        parts = []
        if fields["scene"]:
            parts.append(f"Scene goal: {fields['scene']}.")
        parts.append(f"Current focus: {fields['focus']}{progress}.")
        if fields["criteria"]:
            parts.append(f"Done when: {fields['criteria']}.")
        parts.append("Pursue the current focus in your next reply without announcing it.")
        return " ".join(parts)

    def snapshot(self) -> dict:
        def nest(goal_id: str) -> dict:
            node = copy.deepcopy(self.nodes[goal_id])
            node["focus"] = goal_id == self.focus_id
            node["children"] = [nest(child) for child in node["children"]]
            return node

        return {
            "turn": self.turn,
            "focus": self.focus_id,
            "root": nest(self.state["root"]),
            "events": copy.deepcopy(self.state["events"][-SNAPSHOT_EVENTS:]),
        }

    # -- internals -----------------------------------------------------

    def _create(self, text, *, parent, criteria, turn_budget, complete_with_children, source, data) -> str:
        goal_id = f"g{self.state['next_id']}"
        self.state["next_id"] += 1
        self.nodes[goal_id] = {
            "id": goal_id,
            "text": _clean_text(text),
            "criteria": criteria,
            "status": "pending",
            "parent": parent,
            "children": [],
            "source": source,
            "created_turn": self.turn,
            "started_turn": None,
            "closed_turn": None,
            "turns": 0,
            "turn_budget": turn_budget,
            "complete_with_children": complete_with_children,
            "notes": [],
            "data": data or {},
        }
        self._event("added", goal_id, self.nodes[goal_id]["text"])
        return goal_id

    def _close(self, node: dict, status: str, note: Optional[str], kind: str) -> None:
        node["status"] = status
        node["closed_turn"] = self.turn
        if note:
            self._note(node, note)
        self._event(kind, node["id"], note or node["text"])
        for child_id in node["children"]:
            child = self.nodes[child_id]
            if child["status"] in OPEN_STATUSES:
                self._close(child, "abandoned", f"Parent {node['id']} closed", "abandoned")

    def _complete_parents(self, node: dict) -> None:
        parent_id = node["parent"]
        while parent_id is not None:
            parent = self.nodes[parent_id]
            if not (parent["complete_with_children"] and parent["status"] in OPEN_STATUSES):
                return
            if self.open_children(parent_id):
                return
            if not any(self.nodes[c]["status"] == "done" for c in parent["children"]):
                return
            self._close(parent, "done", "All sub-goals done", "done")
            parent_id = parent["parent"]

    def _refocus(self) -> None:
        root = self.nodes[self.state["root"]]
        chain: list[str] = []
        if root["status"] in OPEN_STATUSES:
            node = root
            while True:
                chain.append(node["id"])
                open_children = self.open_children(node["id"])
                if not open_children:
                    break
                node = open_children[0]

        on_path = set(chain)
        for node in self.nodes.values():
            if node["status"] in OPEN_STATUSES:
                node["status"] = "active" if node["id"] in on_path else "pending"
                if node["id"] in on_path and node["started_turn"] is None:
                    node["started_turn"] = self.turn

        focus = chain[-1] if chain else None
        if focus != self.state["focus"]:
            self.state["focus"] = focus
            if focus is not None:
                self._event("focused", focus, self.nodes[focus]["text"])

    def _note(self, node: dict, text: str) -> None:
        node["notes"].append({"turn": self.turn, "text": text})
        del node["notes"][:-self.limits["max_notes"]]

    def _event(self, kind: str, goal_id: Optional[str], text: str) -> None:
        events = self.state["events"]
        events.append({"turn": self.turn, "goal": goal_id, "kind": kind, "text": text})
        del events[:-self.limits["max_events"]]


def _clean_text(text: Any) -> str:
    text = " ".join(str(text).split())
    if not text:
        raise GoalError("A goal needs some text")
    return text[:MAX_GOAL_TEXT]


# ----------------------------------------------------------------------
# runtime functions
# ----------------------------------------------------------------------


def _load(rt: Runtime) -> Optional[GoalTree]:
    state = rt.store_get(GOALS_STORE_KEY)
    if not isinstance(state, dict):
        return None
    return GoalTree(copy.deepcopy(state))


def _require(rt: Runtime) -> GoalTree:
    tree = _load(rt)
    if tree is None:
        raise GoalError("This scene has no goals; call goals.start_scene first")
    return tree


def _save(rt: Runtime, tree: GoalTree) -> None:
    try:
        # Round-tripping both checks the tree will save and hands the store a
        # copy nothing else holds.
        state = json.loads(json.dumps(tree.state))
    except TypeError as exc:
        raise GoalError(f"Goal data must be JSON-serialisable: {exc}") from None
    rt.store_set(GOALS_STORE_KEY, state)


def _edit(rt: Runtime, operation: Callable[[GoalTree], Any]) -> Any:
    tree = _require(rt)
    result = operation(tree)
    _save(rt, tree)
    return result


def start_scene(
    rt: Runtime,
    text: str,
    *,
    criteria: Optional[str] = None,
    turn_budget: Optional[int] = None,
    limits: Optional[dict] = None,
    reset: bool = False,
) -> str:
    """Give the scene its root goal and return the root's id.

    A flow restarts from the top when a session is resumed or a message is
    rewritten, so an existing tree is kept (and its root id returned) unless
    `reset` is true.
    """
    existing = _load(rt)
    if existing is not None and not reset:
        return existing.state["root"]
    tree = GoalTree.new(text, criteria=criteria, turn_budget=turn_budget, limits=limits)
    _save(rt, tree)
    return tree.state["root"]


def add(
    rt: Runtime,
    text: str,
    *,
    parent: Optional[str] = None,
    index: Optional[int] = None,
    criteria: Optional[str] = None,
    turn_budget: Optional[int] = None,
    complete_with_children: bool = False,
    source: str = "flow",
    data: Optional[dict] = None,
) -> str:
    """Add a sub-goal under `parent` (default: the focus) and return its id.

    A new child of the focus becomes the focus at once. Raises GoalLimitError
    past the tree's depth, open-children or goal-count limits.
    """
    return _edit(rt, lambda tree: tree.add(
        text, parent=parent, index=index, criteria=criteria, turn_budget=turn_budget,
        complete_with_children=complete_with_children, source=source, data=data,
    ))


def complete(rt: Runtime, goal_id: Optional[str] = None, note: Optional[str] = None) -> str:
    """Mark a goal (default: the focus) done; its open sub-goals are abandoned."""
    return _edit(rt, lambda tree: tree.close(goal_id, "done", note))


def fail(rt: Runtime, goal_id: Optional[str] = None, note: Optional[str] = None) -> str:
    """Mark a goal (default: the focus) failed; its open sub-goals are abandoned."""
    return _edit(rt, lambda tree: tree.close(goal_id, "failed", note))


def abandon(rt: Runtime, goal_id: Optional[str] = None, note: Optional[str] = None) -> str:
    """Drop a goal (default: the focus) without judging it."""
    return _edit(rt, lambda tree: tree.close(goal_id, "abandoned", note))


def note(rt: Runtime, text: str, goal_id: Optional[str] = None) -> None:
    """Attach a note to a goal (default: the focus)."""
    _edit(rt, lambda tree: tree.add_note(text, goal_id))


def update(rt: Runtime, goal_id: str, **changes) -> None:
    """Change a goal's text, criteria, turn_budget, complete_with_children or data."""
    _edit(rt, lambda tree: tree.update(goal_id, **changes))


def tick(rt: Runtime) -> list[dict]:
    """Count one scene turn against every goal on the focus path.

    Call it once per player turn. Returns the events it caused (a goal failing
    its turn budget, the focus moving).
    """
    tree = _load(rt)
    if tree is None:
        return []
    events = tree.tick()
    _save(rt, tree)
    return events


def active(rt: Runtime) -> Optional[dict]:
    """A copy of the focus goal, or None when no goal is open."""
    tree = _load(rt)
    if tree is None or tree.focus_id is None:
        return None
    return tree.node(tree.focus_id)


def path(rt: Runtime) -> list[dict]:
    """Copies of the goals from the root down to the focus."""
    tree = _load(rt)
    return tree.path() if tree is not None else []


def get(rt: Runtime, goal_id: str) -> dict:
    return _require(rt).node(goal_id)


def tree(rt: Runtime) -> Optional[dict]:
    """A copy of the whole goal-tree dict, or None."""
    loaded = _load(rt)
    return loaded.state if loaded is not None else None


def summary(rt: Runtime) -> str:
    """The tree as indented text, focus marked."""
    loaded = _load(rt)
    return loaded.summary() if loaded is not None else "(no scene goals)"


def instruction_text(rt: Runtime, template: Template = None) -> Optional[str]:
    """What `inject` would tell the scene actor, or None when no goal is open.

    `template` is a format string over {scene}, {focus}, {progress} and
    {criteria}, or a callable taking the list of goals from root to focus.
    """
    loaded = _load(rt)
    return loaded.instruction_text(template) if loaded is not None else None


def inject(rt: Runtime, *, template: Template = None, only_if_changed: bool = False) -> bool:
    """Append the focus as a hidden `(INSTRUCTIONS: ...)` turn to the working actor.

    Run it while the scene actor is the working actor, just before its visible
    `generate`. The turn is hidden from `get_scene()` and the web transcript.
    With `only_if_changed`, an instruction identical to the last one injected is
    skipped. Returns whether a turn was appended.
    """
    loaded = _load(rt)
    if loaded is None:
        return False
    text = loaded.instruction_text(template)
    if text is None:
        return False
    if only_if_changed and text == loaded.state.get("last_injected"):
        return False
    loaded.state["last_injected"] = text
    _save(rt, loaded)
    # Not `generate(prompt=...)`: that resolves prompt strings as file paths
    # and `var:` lookups.
    rt.append(format_instructions(text))
    return True


def snapshot(store: dict) -> Optional[dict]:
    """The nested goal tree plus recent events from a raw store dict, for display."""
    state = store.get(GOALS_STORE_KEY)
    if not isinstance(state, dict):
        return None
    return GoalTree(copy.deepcopy(state)).snapshot()


# ----------------------------------------------------------------------
# LLM helpers
# ----------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """You track progress through the goals of a scene. You will be shown the scene's goal tree, the goal currently in focus with its completion criteria, and the most recent part of the scene.

Decide whether the goal in focus has been achieved, has become impossible, or is still in progress. Judge only the goal in focus.

Respond ONLY with a JSON object matching this schema, with no surrounding prose and no markdown fences:
{"goal": "<id of the goal in focus>", "status": "continue" | "done" | "failed", "note": "<one short sentence of evidence>"}"""

PLANNER_SYSTEM_PROMPT = """You plan the goals of a scene. You will be shown the scene's goal tree and the most recent part of the scene, then either a goal to break down into sub-goals or an event that may call for new sub-goals.

Sub-goals are concrete, short, and achievable within a few exchanges. List them in the order they should be pursued. Propose no sub-goals when none are needed.

Respond ONLY with a JSON object matching this schema, with no surrounding prose and no markdown fences:
{"subgoals": [{"text": "<sub-goal>", "criteria": "<how to tell it is done>", "turn_budget": <integer or null>}], "exhaustive": true | false, "note": "<one short sentence>"}

Set "exhaustive" to true when completing every sub-goal completes the goal being planned."""

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def parse_json_object(text: str) -> dict:
    """The first `{...}` object in `text`, tolerating markdown fences and prose."""
    stripped = _FENCE_RE.sub("", str(text).strip())
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end < start:
        raise GoalOutputError(f"No JSON object in reply: {text!r}")
    try:
        value = json.loads(stripped[start:end + 1])
    except json.JSONDecodeError as exc:
        raise GoalOutputError(f"Reply is not valid JSON ({exc}): {text!r}") from None
    if not isinstance(value, dict):
        raise GoalOutputError(f"Reply is not a JSON object: {text!r}")
    return value


def _scene_tail(rt: Runtime, scene_actor: Optional[str]) -> str:
    scene = rt.actor(scene_actor or rt.main_actor_name).get_scene()
    return scene[-SCENE_TAIL_CHARS:]


def _ask_for_json(rt: Runtime, actor_name: str, system: str | Any, context: str,
                  validate: Callable[[dict], dict], max_retries: int) -> Flow:
    """Run `actor_name` once for a JSON reply; returns the validated dict or an error string."""

    def flow(r: Runtime) -> dict:
        r.refresh()
        r.system(system)
        r.append(context)
        r.generate()
        error = ""
        for attempt in range(max_retries + 1):
            try:
                return {"ok": validate(parse_json_object(r.raw_latest_text()))}
            except GoalOutputError as exc:
                error = str(exc)
            if attempt < max_retries:
                # Drop the bad reply so the retry sees the same history.
                r.actor().history.remove()
                r.generate()
        return {"error": error}

    result = yield from call_actor(rt, actor_name, flow)
    return result


def _handle_error(rt: Runtime, error: str, on_error: str, goal_id: Optional[str], kind: str) -> None:
    if on_error == "raise":
        raise GoalOutputError(error)
    loaded = _load(rt)
    if loaded is not None:
        loaded._event(kind, goal_id, error[:MAX_GOAL_TEXT])
        _save(rt, loaded)


def judge(
    rt: Runtime,
    actor_name: str,
    *,
    system: Any = None,
    scene_actor: Optional[str] = None,
    max_retries: int = 3,
    on_error: str = "ignore",
) -> Flow:
    """Ask `actor_name` whether the focus goal is done, failed, or still going, and apply it.

    Use as `verdict = yield from goals.judge(rt, "judge")`. Returns the parsed
    verdict dict, or None when there is no open goal or the reply never parsed
    (`on_error="raise"` raises GoalOutputError instead).
    """
    loaded = _load(rt)
    if loaded is None or loaded.focus_id is None:
        return None
    focus = loaded.node(loaded.focus_id)
    context = (
        f"GOAL TREE:\n{loaded.summary()}\n\n"
        f"GOAL IN FOCUS: [{focus['id']}] {focus['text']}\n"
        f"DONE WHEN: {focus['criteria'] or '(no criteria given; use judgement)'}\n\n"
        f"RECENT SCENE:\n{_scene_tail(rt, scene_actor)}"
    )

    def validate(value: dict) -> dict:
        if value.get("status") not in ("continue", "done", "failed"):
            raise GoalOutputError(f"'status' must be continue, done or failed: {value!r}")
        return value

    result = yield from _ask_for_json(rt, actor_name, system or JUDGE_SYSTEM_PROMPT, context, validate, max_retries)
    if "error" in result:
        _handle_error(rt, result["error"], on_error, focus["id"], "judge_error")
        return None

    verdict = result["ok"]
    loaded = _require(rt)
    if verdict.get("goal", focus["id"]) != focus["id"] or loaded.focus_id != focus["id"]:
        loaded._event("judge_error", focus["id"], f"Verdict named {verdict.get('goal')!r}, not the focus; ignored")
    elif verdict["status"] == "continue":
        if verdict.get("note"):
            loaded._note(loaded.node(focus["id"]), str(verdict["note"]))
    else:
        loaded.close(focus["id"], verdict["status"], str(verdict.get("note") or "") or None)
    _save(rt, loaded)
    return verdict


def plan(
    rt: Runtime,
    actor_name: str,
    *,
    goal_id: Optional[str] = None,
    event: Optional[str] = None,
    system: Any = None,
    scene_actor: Optional[str] = None,
    max_retries: int = 3,
    on_error: str = "ignore",
) -> Flow:
    """Ask `actor_name` for sub-goals and add them; returns the new goal ids.

    With `event`, the planner reacts to something that just happened and may
    add nothing. Otherwise it breaks `goal_id` (default: the focus) down, and
    marks that goal `complete_with_children` when it says the sub-goals cover
    it. Sub-goals over the tree's limits, or repeating an open sibling, are
    dropped with an event rather than raising.
    """
    loaded = _load(rt)
    if loaded is None or loaded.focus_id is None:
        return []
    target = loaded.resolve(goal_id)
    if event is not None:
        task = f"EVENT: {event}\nPropose sub-goals of [{target['id']}] that respond to this event, or none."
    else:
        task = f"GOAL TO BREAK DOWN: [{target['id']}] {target['text']}"
        if target["criteria"]:
            task += f"\nDONE WHEN: {target['criteria']}"
    context = f"GOAL TREE:\n{loaded.summary()}\n\n{task}\n\nRECENT SCENE:\n{_scene_tail(rt, scene_actor)}"

    def validate(value: dict) -> dict:
        if not isinstance(value.get("subgoals"), list):
            raise GoalOutputError(f"'subgoals' must be a list: {value!r}")
        return value

    result = yield from _ask_for_json(rt, actor_name, system or PLANNER_SYSTEM_PROMPT, context, validate, max_retries)
    if "error" in result:
        _handle_error(rt, result["error"], on_error, target["id"], "plan_error")
        return []

    loaded = _require(rt)
    added: list[str] = []
    for proposal in result["ok"]["subgoals"]:
        if isinstance(proposal, str):
            proposal = {"text": proposal}
        if not isinstance(proposal, dict) or not str(proposal.get("text") or "").strip():
            continue
        text = " ".join(str(proposal["text"]).split())[:MAX_GOAL_TEXT]
        siblings = {c["text"].casefold() for c in loaded.open_children(target["id"])}
        if text.casefold() in siblings:
            loaded._event("dropped", target["id"], f"Duplicate sub-goal: {text}")
            continue
        budget = proposal.get("turn_budget")
        if not isinstance(budget, int) or budget < 1:
            budget = loaded.limits["planner_turn_budget"]
        criteria = proposal.get("criteria")
        try:
            added.append(loaded.add(
                text, parent=target["id"], criteria=str(criteria) if criteria else None,
                turn_budget=budget, source="planner",
            ))
        except GoalError as exc:
            loaded._event("dropped", target["id"], f"{text}: {exc}")
    if event is None and added and result["ok"].get("exhaustive"):
        loaded.update(target["id"], complete_with_children=True)
    _save(rt, loaded)
    return added

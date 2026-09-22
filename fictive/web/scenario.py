"""Load a scenario written as Python against `fictive.Runtime`.

The JSON runtime finds a scenario in a directory: `schema.json` plus one
instruction list per actor. A library-runtime scenario is Python instead, so
there is nothing to parse -- there is a module to import, and a contract it has
to answer:

    NAME = "evil_AI"                    # optional; defaults to the directory name
    MAIN_ACTOR = "generator"            # required
    ACTOR_TYPES = {"generator": "generator", "helper": None}   # or ACTOR_NAMES
    def flow(runtime): ...              # required: the entry flow
    def resume_flow(runtime): ...       # optional; used instead of `flow` after a load
    def register_commands(runtime): ... # optional; slash commands

The host builds the actors, so one pipeline chosen on the command line serves a
whole scenario and the module says only which actors exist and what type each
one is. Actors are built with no `instructions`, which is a library-runtime
actor's correct starting state: its commands come from the flow, not a list.
"""

from __future__ import annotations

import importlib.util
import inspect
import pathlib
import sys
from typing import Optional

from ..actors import Actor, ActorConfig
from ..custom_actors import actor_from_config

# The filename looked for inside a directory. Named for what it is rather than
# `scenario.py`, because a scenario package may already have a `scenario/`
# directory holding its prompt files.
ENTRY_FILENAME = "fictive_scenario.py"


class ScenarioContractError(Exception):
    """A scenario module does not answer the contract above."""


class RuntimeScenarioSpec:
    """One scenario module, imported once and reused by every session."""

    def __init__(self, target: str | pathlib.Path):
        self.path = self._resolve(target)
        self.dir = self.path.parent
        self.module = self._import(self.path)

        self.main_actor_name: str = self._require_main_actor()
        self.actor_types: dict[str, Optional[str]] = self._require_actor_types()
        self._flow = self._require_flow()
        self._resume_flow = getattr(self.module, "resume_flow", None)
        self._register_commands = getattr(self.module, "register_commands", None)

        if self.main_actor_name not in self.actor_types:
            raise ScenarioContractError(
                f"{self.path} names MAIN_ACTOR {self.main_actor_name!r}, which is not "
                f"among its actors {sorted(self.actor_types)}."
            )

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(target: str | pathlib.Path) -> pathlib.Path:
        path = pathlib.Path(target).expanduser().resolve()
        if path.is_dir():
            entry = path / ENTRY_FILENAME
            if not entry.is_file():
                raise FileNotFoundError(
                    f"{path} is not a Runtime scenario: it holds no {ENTRY_FILENAME}. "
                    f"Point --scenario at a scenario module, or at a directory "
                    f"containing one."
                )
            return entry
        if path.is_file():
            return path
        raise FileNotFoundError(f"No scenario module at {path}.")

    @staticmethod
    def _import(path: pathlib.Path):
        """Import the module, with its own directory first on `sys.path`.

        Scenario packages in this repository import their siblings flat --
        `from config import ...`, not `from .config import ...` -- because they
        are run as scripts rather than installed. Putting the module's directory
        on `sys.path` before importing keeps that working when the module is
        loaded from somewhere else instead.

        The cost is that those flat names (`config`, `flows`) land in the global
        `sys.modules`, so one process serves one scenario: two scenarios would
        collide on `config`. That is why the app builds a single spec at startup
        and never swaps it.
        """
        directory = str(path.parent)
        if directory not in sys.path:
            sys.path.insert(0, directory)

        module_name = f"fictive_scenario_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ScenarioContractError(f"Could not load {path} as a Python module.")

        module = importlib.util.module_from_spec(spec)
        # Registered before execution so a module that imports itself, directly
        # or through a sibling, does not run twice.
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        return module

    # ------------------------------------------------------------------
    # contract
    # ------------------------------------------------------------------

    def _require_main_actor(self) -> str:
        name = getattr(self.module, "MAIN_ACTOR", None)
        if not isinstance(name, str) or not name:
            raise ScenarioContractError(
                f"{self.path} must define MAIN_ACTOR as the name of the actor whose "
                f"generations are the conversation."
            )
        return name

    def _require_actor_types(self) -> dict[str, Optional[str]]:
        types = getattr(self.module, "ACTOR_TYPES", None)
        if isinstance(types, dict) and types:
            return {str(name): value for name, value in types.items()}

        names = getattr(self.module, "ACTOR_NAMES", None)
        if isinstance(names, (list, tuple)) and names:
            return {str(name): None for name in names}

        raise ScenarioContractError(
            f"{self.path} must define ACTOR_TYPES (a name -> type mapping, with None "
            f"for a plain Actor) or ACTOR_NAMES (a list of names)."
        )

    def _require_flow(self):
        flow = getattr(self.module, "flow", None)
        if not callable(flow):
            raise ScenarioContractError(
                f"{self.path} must define flow(runtime): the scenario's entry flow, a "
                f"generator that yields an InputRequest wherever it needs a human "
                f"answer (see fictive.library_runtime.ask)."
            )
        return flow

    # ------------------------------------------------------------------
    # use
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        declared = getattr(self.module, "NAME", None)
        if isinstance(declared, str) and declared:
            return declared
        return self.dir.name

    @property
    def actor_names(self) -> list[str]:
        return list(self.actor_types)

    def build_actors(self, storage_dir: str | pathlib.Path, pipeline) -> list[Actor]:
        """One actor per name, sharing one pipeline and holding no instructions."""
        return [
            actor_from_config(
                ActorConfig(
                    name=name,
                    actor_type=self.actor_types.get(name),
                    storage_dir=str(storage_dir),
                    pipeline=pipeline,
                )
            )
            for name in self.actor_names
        ]

    def make_flow(self, runtime, resumed: bool = False):
        """The generator to drive: `resume_flow` when resuming and defined."""
        entry = self._resume_flow if (resumed and self._resume_flow is not None) else self._flow
        return entry(runtime)

    def register_commands(self, runtime) -> None:
        if self._register_commands is None:
            return
        self._register_commands(runtime)

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "dir": str(self.dir),
            "module": str(self.path),
            "main_actor": self.main_actor_name,
            "actors": [
                {
                    "name": name,
                    "type": self.actor_types.get(name) or "actor",
                    # A Runtime actor has no instruction list to count. The field
                    # stays so the shape a UI reads is unchanged.
                    "commands": 0,
                }
                for name in self.actor_names
            ],
            "entry_flow": getattr(self._flow, "__name__", "flow"),
            "resumable": self._resume_flow is not None,
            "slash_commands": sorted(_declared_commands(self.module)),
        }


def _declared_commands(module) -> list[str]:
    """Slash-command names, when the module's `register_commands` exposes them.

    Best effort and display-only: a scenario registers its commands against a
    live `Runtime`, so the authoritative list is `Runtime.commands` once a
    session exists. This reads the conventional `_COMMANDS` registry a scenario
    fills with a decorator, and says nothing when there isn't one.
    """
    registry = getattr(module, "_COMMANDS", None)
    if isinstance(registry, dict):
        return [str(name) for name in registry]
    commands_module = inspect.getmodule(getattr(module, "register_commands", None))
    registry = getattr(commands_module, "_COMMANDS", None)
    if isinstance(registry, dict):
        return [str(name) for name in registry]
    return []

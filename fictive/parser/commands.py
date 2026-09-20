import pathlib
import re
from typing import Dict, List, Optional, Tuple
from enum import Enum, auto
from dataclasses import dataclass
from copy import deepcopy

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        pass


class Cmd(StrEnum):
    # You can modify this Enum class init for new commans
    SYSTEM = "system"
    INPUT_FROM = "input-from"
    GENERATE = "generate"
    AGENT = "agent"
    RUN_ACTOR = "run-actor"
    REFRESH = "refresh"
    LOOP = "loop"
    ASSIGN = "assign"
    WRITE = "write"
    PRINT = "print"
    PRINT_LATEST = "print-latest"
    COND = "cond"
    EXIT = "exit"
    SAVE_CONVERSATION = "save-conversation"
    LOAD_CONVERSATION = "load-conversation"
    RAG_GENERATE = "rag-generate"
    WEB_SEARCH_AND_GENERATE = "web-search-and-generate"

    @classmethod
    def _missing_(cls, value):
        """Resolve a command name written in any separator style or case.

        `from_name` already maps `_` to `-`, which covers `rag_generate`. This
        also resolves camelCase and run-together spellings, so
        `webSearchAndGenerate` is `web-search-and-generate`.

        Resolution only: the member's value, and therefore the `name` on its
        dataclass, stays canonical, so `Interpreter.exec_map` lookups and saved
        sessions are unaffected. `Enum.__call__` only reaches here after an
        exact-value match fails, so the canonical path costs nothing.
        """
        if not isinstance(value, str):
            return None
        key = re.sub(r"[-_\s]", "", value).casefold()
        for member in cls:
            if re.sub(r"[-_]", "", member.value).casefold() == key:
                return member
        return None

    @staticmethod
    def define_map():
        """
        Define the command: dataclass map here
        You can modify this function for new commands
        """
        command_maps = {
            Cmd.SYSTEM: SYSTEM,
            Cmd.INPUT_FROM: INPUT_FROM,
            Cmd.GENERATE: GENERATE,
            Cmd.AGENT: AGENT,
            Cmd.RUN_ACTOR: RUN_ACTOR,
            Cmd.REFRESH: REFRESH,
            Cmd.LOOP: LOOP,
            Cmd.ASSIGN: ASSIGN,
            Cmd.WRITE: WRITE,
            Cmd.PRINT: PRINT,
            Cmd.PRINT_LATEST: PRINT_LATEST,
            Cmd.COND: COND,
            Cmd.EXIT: EXIT,
            Cmd.SAVE_CONVERSATION: SAVE_CONVERSATION,
            Cmd.LOAD_CONVERSATION: LOAD_CONVERSATION,
            Cmd.RAG_GENERATE: RAG_GENERATE,
            Cmd.WEB_SEARCH_AND_GENERATE: WEB_SEARCH_AND_GENERATE,
        }
        return command_maps

    @staticmethod
    def from_name(command_name: str) -> "Cmd":
        """Look up a command by name, accepting `_` for `-`, so `rag_generate` is `rag-generate`."""
        return Cmd(str(command_name).replace("_", "-"))
    
    def map_to_dataclass(self):
        """
        Map from the command to the appropriate dataclass
        init method
        """
        cmd_map = Cmd.define_map()
        return cmd_map[self]

    def normalize_params(self, cmd_data: dict) -> dict:
        """
        Normalize documented command parameter names into dataclass field names.
        """
        normalized = {k.replace("-", "_"): v for k, v in cmd_data.items()}
        if self == Cmd.ASSIGN and ("name" in normalized) and ("var_name" not in normalized):
            normalized["var_name"] = normalized.pop("name")
        return normalized


@dataclass
class CommandObj:
    """Main class for the following command objects."""
    pass 


@dataclass
class SYSTEM(CommandObj):
    """Set system prompt."""
    
    prompt: str | pathlib.Path
    name = "system"
    

@dataclass
class INPUT_FROM(CommandObj):
    """Take input from a source."""

    name = "input-from"

    enclosing_prompt: Optional[str | pathlib.Path] = None
    prompt: Optional[str | pathlib.Path] = None
    store: Optional[str] = None 

    human_prompt: Optional[str | pathlib.Path] = None
    input_from_actor: Optional[str] = None
    input_from_file: Optional[str | pathlib.Path] = None
    input_from_store: Optional[str] = None

    history: bool = True

            
@dataclass
class GENERATE(CommandObj):
    """Pass history to pipeline to get text-generation output."""
    
    name = "generate"
    prompt: Optional[str | pathlib.Path] = None


@dataclass
class AGENT(CommandObj):
    """Run a bounded agent using actor history and an optional immediate task."""

    profile: str
    name = "agent"
    prompt: Optional[str | pathlib.Path | dict] = None
    workspace: str | pathlib.Path = "."
    tools: Optional[List[str]] = None
    request_limit: int = 20
    tool_call_limit: int = 50
    store: Optional[str] = None
    trace_store: Optional[str] = None

@dataclass
class RUN_ACTOR(CommandObj):
    """Run a single cycle of the given actor (NO LOOPING), and get the output at the end of the cycle."""

    actor_name: str

    name = "run-actor"
    start_step: int = 0

    prompt: Optional[str | pathlib.Path] = None
    store: Optional[str] = None 

@dataclass
class REFRESH(CommandObj):
    """Refresh the actor's history i.e: delete everything except (if applicable) system prompt."""

    name = "refresh"


@dataclass
class LOOP(CommandObj):
    """Loop around to the beginning of the actor's instructions (or, optionally, loop to given step.)"""

    name = "loop"
    step: int = 0


@dataclass
class ASSIGN(CommandObj):
    """Assign a variable <name> some value <value>."""

    name = "assign"
    var_name: str
    value: str | pathlib.Path


@dataclass
class WRITE(CommandObj):
    """Write text or actor history to a file."""

    name = "write"
    path: str | pathlib.Path
    read_from: Optional[str | pathlib.Path | dict] = None
    overwrite: bool = False
    write_history: Optional[str] = None

@dataclass
class PRINT(CommandObj):
    """Print some text to the screen."""

    name = "print"
    prompt: str | pathlib.Path


@dataclass
class PRINT_LATEST(CommandObj):
    """Print the latest assistant output from an actor's history."""

    name = "print-latest"
    actor_name: Optional[str] = None
    n: int = 0


@dataclass
class COND(CommandObj):
    """Evaluate ordered conditions and queue the first matching command block."""

    name = "cond"
    conditions: List[dict]

    def __post_init__(self):
        normalized_conditions = []
        for raw_condition in self.conditions:
            if not isinstance(raw_condition, dict):
                raise TypeError("Each cond condition must be a dict.")

            condition = deepcopy(raw_condition)
            commands = condition.get("commands", condition.get("block", []))
            if not isinstance(commands, list):
                raise TypeError("Each cond branch must define a list of commands.")

            condition["commands"] = [
                parse_command_dict(cmd) if isinstance(cmd, dict) else cmd
                for cmd in commands
            ]
            normalized_conditions.append(condition)

        self.conditions = normalized_conditions


@dataclass
class EXIT(CommandObj):
    """Exit the current actor and return control to the previous actor."""

    name = "exit"


@dataclass
class SAVE_CONVERSATION(CommandObj):
    """Save the whole interpreter session to a JSON file (by default `conversations/<session-id>.json` under the storage directory)."""

    name = "save-conversation"
    path: Optional[str | pathlib.Path] = None
    session_id: Optional[str] = None
    store: Optional[str] = None


@dataclass
class LOAD_CONVERSATION(CommandObj):
    """Replace the whole interpreter session with one written by `save-conversation`."""

    name = "load-conversation"
    path: Optional[str | pathlib.Path] = None
    session_id: Optional[str] = None

    def __post_init__(self):
        if (self.path is None) == (self.session_id is None):
            raise ValueError("load-conversation takes exactly one of path or session-id.")


@dataclass
class RAG_GENERATE(CommandObj):
    """Retrieve relevant past conversations, then generate the actor's next message from them."""

    name = "rag-generate"
    prompt: Optional[str | pathlib.Path | dict] = None
    query: Optional[str | dict] = None
    top_k: int = 4
    actor_filter: Optional[str] = None
    enclosing_prompt: Optional[str | pathlib.Path] = None
    backend: Optional[str] = None
    model_arn: Optional[str] = None
    store: Optional[str] = None
    sources_store: Optional[str] = None
    fallback_on_retrieval_error: bool = False

    def __post_init__(self):
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int) or self.top_k < 1:
            raise ValueError(f"rag-generate top-k must be a positive integer, got {self.top_k!r}.")


@dataclass
class WEB_SEARCH_AND_GENERATE(CommandObj):
    """Search the web, then generate the actor's next message from the results."""

    name = "web-search-and-generate"
    prompt: Optional[str | pathlib.Path | dict] = None
    query: Optional[str | dict] = None
    max_results: int = 5
    enclosing_prompt: Optional[str | pathlib.Path] = None
    backend: Optional[str] = None
    filters: Optional[dict] = None
    store: Optional[str] = None
    sources_store: Optional[str] = None
    fallback_on_search_error: bool = False

    def __post_init__(self):
        # `True` is an `int` and would otherwise pass the range check.
        if (
            isinstance(self.max_results, bool)
            or not isinstance(self.max_results, int)
            or not (1 <= self.max_results <= 25)
        ):
            raise ValueError(
                "web-search-and-generate max-results must be an integer between 1 and 25, "
                f"got {self.max_results!r}."
            )
        if self.filters is not None and not isinstance(self.filters, dict):
            raise TypeError(
                f"web-search-and-generate filters must be a dict, got {type(self.filters).__name__}."
            )


def parse_command_dict(instr: dict) -> CommandObj:
    cmd = Cmd.from_name(instr["cmd"])
    data_init = cmd.map_to_dataclass()
    cmd_data = deepcopy(instr)
    cmd_data.pop("cmd")
    cmd_data = cmd.normalize_params(cmd_data)
    return data_init(**cmd_data)

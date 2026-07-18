import pathlib
from typing import Dict, List, Optional, Tuple
from enum import Enum, auto
from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:
    class StrEnum(str, Enum):
        pass


class Cmd(StrEnum):
    # You can modify this Enum class init for new commans
    SYSTEM = auto()
    INPUT_FROM = "input-from"
    GENERATE = auto()
    RUN_ACTOR = "run-actor"
    REFRESH = auto()
    LOOP = auto()
    ASSIGN = auto()
    PRINT = auto()
    PRINT_LATEST = "print-latest"

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
            Cmd.RUN_ACTOR: RUN_ACTOR,
            Cmd.REFRESH: REFRESH,
            Cmd.LOOP: LOOP,
            Cmd.ASSIGN: ASSIGN,
            Cmd.PRINT: PRINT,
            Cmd.PRINT_LATEST: PRINT_LATEST,
        }
        return command_maps
    
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
    input_from_store: Optional[str] = None

    history: bool = True

            
@dataclass
class GENERATE(CommandObj):
    """Pass history to pipeline to get text-generation output."""
    
    name = "generate"
    prompt: Optional[str | pathlib.Path] = None

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

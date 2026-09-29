"""The contract the web backend reads to run the ttrpg scenario.

Run it with:

    python -m fictive.web --scenario examples/ttrpg --pipeline-type openai --model <model>
"""

from config import ACTOR_TYPES, SCENARIO_DIR
from flows.generator import play
from special_commands import register_commands

NAME = "ttrpg"
MAIN_ACTOR = "generator"
flow = play

__all__ = ["ACTOR_TYPES", "MAIN_ACTOR", "NAME", "SCENARIO_DIR", "flow", "register_commands"]

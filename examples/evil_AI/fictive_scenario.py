"""The contract the web backend reads to run this scenario.

`fictive/web/scenario.py` imports this module and asks it four things: which
actor's generations are the conversation, which actors exist and what type each
one is, and what the entry flow is. Everything else stays where it was --
`config.py` owns the paths and the argument parser, `flows.py` owns the flows,
and `main.py` remains the terminal entry point.

Run it with:

    python -m fictive.web --scenario examples/evil_AI --pipeline-type mock
"""

from config import ACTOR_TYPES, SCENARIO_DIR
from flows import flow

NAME = "evil_AI"
MAIN_ACTOR = "generator"

__all__ = ["ACTOR_TYPES", "MAIN_ACTOR", "NAME", "SCENARIO_DIR", "flow"]

"""The contract the web backend reads to run this scenario.

`fictive/web/scenario.py` imports this module and asks it four things: which
actor's generations are the conversation, which actors exist and what type each
one is, and what the entry flow is. 

Other files:
- `config.py` contains the paths and the argument parser
- `flows.py` contains the flows

Run it with:

    python -m fictive.web --scenario examples/evil_AI --pipeline-type <pipeline type> --model <model>
"""

from config import ACTOR_TYPES, SCENARIO_DIR
from flows import flow

NAME = "evil_AI"
MAIN_ACTOR = "generator"

__all__ = ["ACTOR_TYPES", "MAIN_ACTOR", "NAME", "SCENARIO_DIR", "flow"]

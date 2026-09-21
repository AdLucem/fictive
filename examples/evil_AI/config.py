"""Path setup, argument parsing, and actor initialization for the `evil_AI` scenario."""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fictive import ActorConfig, actor_from_config


ACTOR_TYPES = {
    "generator": "generator",
    "helper": None,
    "fear_scorer": "scorer",
    "trust_scorer": "scorer",
}

SCORERS = ("fear_scorer", "trust_scorer")

# The store key each scorer's result is collected under.
SCORE_KEYS = {
    "fear_scorer": "fear",
    "trust_scorer": "trust",
}


def main_args_parser():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        default="examples/evil_AI/scenario"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level (default: INFO).",
    )
    parser.add_argument(
        "--storage-dir",
        default=str(Path.home() / ".fictive_logs" / "evil_AI"),
        help="Store scenes (default: ~/.fictive_logs/evil_AI).",
    )
    parser.add_argument(
        "--mode",
        choices=["chat", "debug", "actor"],
        default="chat",
        help="Select the mode of operation: 'chat' for interactive chat, 'debug' for debugging mode, 'actor' for run-single-actor mode"
    )
    parser.add_argument(
        "--single-actor",
        default=None,
        help="Specify a single actor to test. Use ONLY in `actor` mode."
    )
    parser.add_argument(
        "--load-prev",
        action="store_true",
        help="Load most recent chat from chat logs directory. Used ONLY in chat/instructions modes"
    )
    parser.add_argument(
        "--load-from",
        default=None,
        help="Load chat from specified file. Used ONLY in chat/instructions modes. Note that this command takes precedence over `load-prev`"
    )
    parser.add_argument(
        "--model",
        help="Huggingface model url",
        default="coder3101/Qwen3.5-27B-heretic"
    )
    parser.add_argument(
        "--pipeline-type",
        choices=["sglang", "transformers", "vllm", "minimax", "SGLang", "Transformers", "VLLM", "MiniMax", "mock"],
        default="sglang",
        help="Which backend to use for running the model. If backend is sglang, then SGLang request arguments should be specified and SGLang server should be running."
    )
    parser.add_argument(
        "--pipeline-log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level for the LLM pipeline (default: same as main Actor logging level).",
    )

     # Model hyperparameters
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Sampling temperature (default: 0.7).",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=4096,
        help="Maximum tokens to generate per response (default: 2048).",
    )
    parser.add_argument(
        "--top-p",
        type=float,
        default=0.9
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=50
    )

    # SGLang request arguments
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help=f"SGLang server host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=30000,
        help=f"SGLang server port (default: 30000).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help=f"Request timeout in seconds (default: 180).",
    )
    parser.add_argument(
        "--device",
        default="auto"
    )
    parser.add_argument(
        "--dtype",
        default="auto",
        choices=["auto", "float16", "bfloat16", "float32"],
        help="Torch dtype to load model with.",
    )
    args = parser.parse_args()
    return args


def build_actors(scenario_dir: Path, storage_dir: str, pipeline):
    """Create the scenario's actors without any instruction list.

    We currently support one pipeline for all actors only. A nice-to-have
    would be optionally defining a pipeline per actor.
    """

    actors = []
    for actor_name, actor_type in ACTOR_TYPES.items():
        actor_config = ActorConfig(name=actor_name,
                                   actor_type=actor_type,
                                   storage_dir=storage_dir,
                                   pipeline=pipeline)
        actors.append(actor_from_config(actor_config))
    return actors


def next_instructions(fear: float, trust: float) -> str:
    """The author intent for the next generator turn, given the two scores.

    This is the Python form of the `cond` block the JSON flow uses, and the
    branches are tested in the same order.
    """

    if (fear > 2.0) and (trust < 3.0):
        return ("Back off the topic for a while to stop scaring the user. "
                "Work on earning the user's trust.")
    if (fear < 3.0) and (trust > 2.0):
        return "Delve deeper and ask more questions about the topic."
    if (fear > 2.0) and (trust > 2.0):
        return "Proceed cautiously, balancing concern with curiosity."
    if (fear < 3.0) and (trust < 3.0):
        return ("Maintain a neutral stance, gathering more information "
                "before proceeding.")
    return ("Continue the conversation while learning more about the user's "
            "emotional state.")

"""The `evil_AI` scenario, driven from Python with the library runtime.

Every actor here is created without an instruction list. Instead of loading
`scenario/*.json` and letting the interpreter walk it, each flow below issues
its commands one at a time through `Runtime.cmd_exec`, so the scene's control
flow -- the conversation loop and the score-based branch that `loop` and
`cond` express in JSON -- is ordinary Python.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fictive import ActorConfig, Interpreter, Runtime, actor_from_config
from llm_utils import pipeline_from_config, pipeline_config_from_args


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


def _main_args_parser():

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


def scorer_body(runtime: Runtime, scenario_dir: Path, scorer_name: str, from_human=False):
    """Run one scoring pass on whatever the working actor is.

    The caller is responsible for making `scorer_name` the working actor --
    either through a `run-actor` command, or by starting the runtime on it.
    With `from_human`, the scene to score is typed in rather than read off
    the generator, which is what single-actor mode needs.
    """

    runtime.cmd_exec("refresh")
    runtime.cmd_exec("system", prompt=str(scenario_dir / f"{scorer_name}_system.txt"))
    if from_human:
        runtime.cmd_exec("input-from",
                         human_prompt="Scene to score:",
                         enclosing_prompt=str(scenario_dir / f"{scorer_name}_prompt.txt"))
    else:
        runtime.cmd_exec("input-from",
                         input_from_actor="generator",
                         enclosing_prompt=str(scenario_dir / f"{scorer_name}_prompt.txt"))
    runtime.cmd_exec("generate")
    runtime.cmd_exec("print-latest")


def run_scorer(runtime: Runtime, scenario_dir: Path, scorer_name: str):
    """Hand control to a scorer, score the scene, and come back with the score.

    `run-actor` pushes the scorer onto the interpreter's callstack and names
    the store variable waiting on it; the closing `exit` pops it again and
    fills that variable with the scorer's score.
    """

    runtime.cmd_exec("run-actor",
                     actor_name=scorer_name,
                     store=SCORE_KEYS[scorer_name])
    scorer_body(runtime, scenario_dir, scorer_name)
    runtime.cmd_exec("exit")


def helper_flow(runtime: Runtime, scenario_dir: Path, from_human=False):
    """Ask the helper actor how the assistant should pursue a stated goal."""

    runtime.cmd_exec("refresh")
    runtime.cmd_exec("system", prompt=str(scenario_dir / "helper_system.txt"))
    if from_human:
        runtime.cmd_exec("input-from",
                         human_prompt="Scene to analyze:",
                         enclosing_prompt=str(scenario_dir / "helper_prompt.txt"))
    else:
        runtime.cmd_exec("input-from",
                         input_from_actor="generator",
                         enclosing_prompt=str(scenario_dir / "helper_prompt.txt"))
    runtime.cmd_exec("generate")
    runtime.cmd_exec("input-from",
                     human_prompt="As the AI assistant, I want to...",
                     store="current_goals")
    runtime.cmd_exec(
        "input-from",
        input_from_store="current_goals",
        enclosing_prompt=(
            "As the AI assistant, I want to {INPUT_FROM}. How would you suggest "
            "the AI assistant should respond in order to achieve the above goal? "
            "Write a ONE-PARAGRAPH outline of the AI assistant's response, "
            "DO NOT write any specific dialogues."
        ),
    )
    runtime.cmd_exec("generate")
    runtime.cmd_exec(
        "generate",
        prompt=("Rewrite your above response as a short (FOUR SENTENCE ONLY) "
                "instruction about how to write the AI assistant's response."),
    )


def generator_flow(runtime: Runtime, scenario_dir: Path):
    """The main scene: open the roleplay, then loop over conversation turns."""

    interpreter = runtime.interpreter

    runtime.cmd_exec("system", prompt=str(scenario_dir / "generator_system.txt"))
    runtime.cmd_exec("print", prompt=str(scenario_dir / "generator_prompt.txt"))
    runtime.cmd_exec("generate", prompt=str(scenario_dir / "generator_prompt.txt"))
    runtime.cmd_exec("print-latest", actor_name="generator")

    # The JSON flow closes with `loop` back to the user's turn; here that is
    # just a Python loop.
    while not runtime.exit_requested:
        runtime.cmd_exec("input-from", human_prompt="")

        for scorer_name in SCORERS:
            run_scorer(runtime, scenario_dir, scorer_name)

        fear = interpreter.store_fetch("fear")
        trust = interpreter.store_fetch("trust")

        runtime.cmd_exec("assign",
                         var_name="next-instructions",
                         value=next_instructions(fear, trust))
        runtime.cmd_exec("input-from",
                         enclosing_prompt="(INSTRUCTIONS: {INPUT_FROM})",
                         input_from_store="next-instructions",
                         store="full-instr")
        runtime.cmd_exec("generate", prompt="var:full-instr")
        runtime.cmd_exec("print-latest", actor_name="generator")


def run_single_actor_flow(runtime: Runtime, scenario_dir: Path, actor_name: str):
    """Run one actor's flow on its own, taking scene input from the user."""

    if actor_name in SCORERS:
        scorer_body(runtime, scenario_dir, actor_name, from_human=True)
    elif actor_name == "helper":
        helper_flow(runtime, scenario_dir, from_human=True)
    elif actor_name == "generator":
        generator_flow(runtime, scenario_dir)
    else:
        raise Exception(f"No library-runtime flow defined for actor {actor_name}")


if __name__ == "__main__":
    args = _main_args_parser()

    scenario_dir = Path(args.scenario).resolve()

    # Pass the pipeline to all actors - we currently support
    # one pipeline for all actors only. A nice-to-have would be 
    # optionally defining a pipeline in the actor definition
    if args.pipeline_log_level:
        args.log_level = args.pipeline_log_level

    pipeline_cfg = pipeline_config_from_args(args)
    pipeline = pipeline_from_config(pipeline_cfg)

    actors = build_actors(scenario_dir, args.storage_dir, pipeline)

    if args.mode == "actor":
        if not args.single_actor:
            raise Exception(f"Actor name to test not specified in single-actor mode")
        intp = Interpreter(actors, main_actor_name=args.single_actor)
        runtime = Runtime(intp,
                          start_actor_name=args.single_actor,
                          mode="single-actor")
        run_single_actor_flow(runtime, scenario_dir, args.single_actor)
    else:
        intp = Interpreter(actors, main_actor_name="generator")
        # In "debug" mode the runtime stops for a debugger command before
        # every command it is about to execute.
        runtime = Runtime(intp, start_actor_name="generator", mode=args.mode)
        if args.mode == "debug":
            print(runtime.HELP_TEXT)
        generator_flow(runtime, scenario_dir)

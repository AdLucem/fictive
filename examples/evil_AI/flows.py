"""Flow functions for the `evil_AI` interactive fiction scenario.

Every actor here is created without an instruction list. Instead of loading
`scenario/*.json` and letting the interpreter walk it, each flow below issues
its commands one at a time through `Runtime.cmd_exec`, so the scene's control
flow -- the conversation loop and the score-based branch that `loop` and
`cond` express in JSON -- is ordinary Python.
"""

from pathlib import Path

from config import SCORERS, SCORE_KEYS, next_instructions

from fictive import Runtime


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

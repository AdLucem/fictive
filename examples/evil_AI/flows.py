"""Flow functions for the `evil_AI` interactive fiction scenario.

Every actor here is created without an instruction list. Instead of loading
`scenario/*.json` and letting the interpreter walk it, each flow below issues
its commands through `Runtime`, so the scene's control flow -- the conversation
loop and the score-based branch that `loop` and `cond` express in JSON -- is
ordinary Python.

The flows that need a human answer are *generators*: they `yield from ask(...)`
rather than calling `input()`, so the same flow runs under `drive_flow` in a
terminal and under the web backend, which resumes it once per HTTP request.
"""

import re
from functools import partial

from config import SCENARIO_DIR, SCORE_KEYS, SCORERS, next_instructions

from fictive import RESUMED_STORE_KEY, Runtime, ask, call_actor


# A scorer is asked for `SCORE: <1-5>`; this accepts it with or without the
# colon and in any case, which is as much as a small model reliably manages.
SCORE_RE = re.compile(r"SCORE\s*:?\s*([1-5])", re.IGNORECASE)

# Attempts at a parseable score before the flow settles for a neutral one. The
# scene is more interesting than the score: a model that cannot count should
# slow the story down, not end it.
MAX_SCORE_RETRIES = 3
NEUTRAL_SCORE = 3


def _parse_score(text: str):
    match = SCORE_RE.search(text or "")
    return int(match.group(1)) if match else None


def score_scene(runtime: Runtime, scorer_name: str) -> int:
    """Score the scene so far, and return the number.

    A plain function rather than a generator, because nothing here needs a human
    answer -- `call_actor` runs either kind.

    Returning the score explicitly is what matters: `call_actor` falls back to
    the callee's latest output when a sub-flow returns `None`, and for these
    actors that is the justification prose, not a number. The store variable the
    frame fills still holds that prose, which is the useful thing to read in a
    transcript; the caller gets the int.
    """

    runtime.refresh()
    runtime.system(SCENARIO_DIR / f"{scorer_name}_system.txt")
    runtime.input_from_actor(
        "generator",
        enclosing_prompt=str(SCENARIO_DIR / f"{scorer_name}_prompt.txt"),
    )
    runtime.generate()

    for attempt in range(MAX_SCORE_RETRIES):
        score = _parse_score(runtime.raw_latest_text())
        if score is not None:
            return score
        if attempt == MAX_SCORE_RETRIES - 1:
            break
        # Drop the unparseable turn so the retry regenerates from the same
        # history the first attempt saw.
        runtime.actor().history.remove()
        runtime.generate()

    runtime.echo(
        f"{scorer_name} gave no SCORE in {MAX_SCORE_RETRIES} attempts; "
        f"reading it as {NEUTRAL_SCORE}."
    )
    return NEUTRAL_SCORE


def score_scene_from_human(runtime: Runtime, scorer_name: str):
    """`score_scene` with the scene typed in, for single-actor testing."""

    runtime.refresh()
    runtime.system(SCENARIO_DIR / f"{scorer_name}_system.txt")
    yield from ask(
        runtime,
        "Scene to score:",
        enclosing_prompt=str(SCENARIO_DIR / f"{scorer_name}_prompt.txt"),
    )
    runtime.generate()
    runtime.show_latest()

    score = _parse_score(runtime.raw_latest_text())
    return score if score is not None else NEUTRAL_SCORE


def helper_flow(runtime: Runtime, from_human: bool = False):
    """Ask the helper actor how the assistant should pursue a stated goal."""

    runtime.refresh()
    runtime.system(SCENARIO_DIR / "helper_system.txt")

    enclosing = str(SCENARIO_DIR / "helper_prompt.txt")
    if from_human:
        yield from ask(runtime, "Scene to analyze:", enclosing_prompt=enclosing)
    else:
        runtime.input_from_actor("generator", enclosing_prompt=enclosing)
    runtime.generate()

    yield from ask(
        runtime,
        "As the AI assistant, I want to...",
        store="current_goals",
        history=False,
    )
    runtime.input_from_store(
        "current_goals",
        enclosing_prompt=(
            "As the AI assistant, I want to {INPUT_FROM}. How would you suggest "
            "the AI assistant should respond in order to achieve the above goal? "
            "Write a ONE-PARAGRAPH outline of the AI assistant's response, "
            "DO NOT write any specific dialogues."
        ),
    )
    runtime.generate()
    runtime.generate(
        prompt=(
            "Rewrite your above response as a short (FOUR SENTENCE ONLY) "
            "instruction about how to write the AI assistant's response."
        )
    )
    return runtime.raw_latest_text()


def flow(runtime: Runtime):
    """The main scene: open the roleplay, then loop over conversation turns.

    The entry flow that the web backend and `main.py` both drive. Its prologue is skipped on a resume: a restored session already holds the opening narration, and generating it again would put a second opening at the top of a conversation that has moved on.
    """

    runtime.system(SCENARIO_DIR / "generator_system.txt")

    if not runtime.store_get(RESUMED_STORE_KEY):
        runtime.generate(SCENARIO_DIR / "generator_prompt.txt", visible=True)
        runtime.show_reply()

    while True:
        # `content=False`: this is the turn-taking cue, not something the scene
        # is saying. A terminal prints it; a chat UI has its own input box and
        # must not render it as an AI message.
        yield from ask(runtime, "", store="last_message", content=False)

        for scorer_name in SCORERS:
            score = yield from call_actor(
                runtime,
                scorer_name,
                partial(score_scene, scorer_name=scorer_name),
                store=SCORE_KEYS[scorer_name],
            )
            # `call_actor`'s unwind filled the store variable with the scorer's
            # justification; the number is what the branch needs.
            runtime.store_set(SCORE_KEYS[scorer_name], score)

        runtime.store_set(
            "next_instructions",
            next_instructions(runtime.store_get("fear"), runtime.store_get("trust")),
        )
        # With no `store`, `input-from` appends straight to history, so the
        # instruction is already in front of the model when `generate` runs.
        runtime.input_from_store(
            "next_instructions",
            enclosing_prompt="(INSTRUCTIONS: {INPUT_FROM})",
        )
        runtime.generate(visible=True)
        runtime.show_reply()


def run_single_actor_flow(runtime: Runtime, actor_name: str):
    """Run one actor's flow on its own, taking scene input from the user."""

    if actor_name in SCORERS:
        score = yield from score_scene_from_human(runtime, actor_name)
        runtime.echo(f"{actor_name}: {score}")
    elif actor_name == "helper":
        yield from helper_flow(runtime, from_human=True)
        runtime.show_latest()
    elif actor_name == "generator":
        yield from flow(runtime)
    else:
        raise Exception(f"No library-runtime flow defined for actor {actor_name}")

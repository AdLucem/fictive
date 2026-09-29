"""Helpers every sub-actor flow shares."""

import json

from fictive import goals

import config
import rules


def start_actor(runtime, actor, **fields):
    """Reset the working actor, then give it its system prompt and its filled-in task prompt."""
    runtime.refresh()
    runtime.system(config.prompt_path(actor, "system"))
    runtime.append(config.load_prompt(actor, "prompt", **fields))


def generate_json(runtime, validate, retries=config.MAX_JSON_RETRIES):
    """Generate a JSON object and return `validate(obj)`; regenerate when either step fails.

    `validate` raises ValueError, KeyError or TypeError for a reply that isn't what
    the actor was asked for. Raises RuntimeError when no reply passes.
    """
    runtime.generate()
    for attempt in range(retries + 1):
        try:
            return validate(goals.parse_json_object(runtime.raw_latest_text()))
        except (ValueError, KeyError, TypeError) as exc:  # goals.GoalOutputError is a ValueError
            error = exc
        if attempt < retries:
            runtime.actor().history.remove()
            runtime.generate()
    raise RuntimeError(f"{runtime.working_actor_name} gave no valid JSON after {retries + 1} tries: {error}")


def check_changes(reply):
    """Validator for the state handlers' {"changes": [...]} replies."""
    if not isinstance(reply["changes"], list):
        raise TypeError('"changes" must be a list')
    return reply["changes"]


def scene_tail(runtime):
    """The most recent part of the story, as the narrator told it (hidden instructions removed)."""
    return runtime.actor("generator").get_scene()[-config.SCENE_TAIL_CHARS:]


def describe_check(check):
    """The check as game-master actors see it: numbers, DC and band."""
    if check is None:
        return "No check was needed."
    tier = check["tier"].replace("_", " ")
    band = check["band"].replace("_", " ")
    return f"{check['ability'].capitalize()} check, {tier} (DC {check['dc']}): {rules.roll_line(check)}, a {band}."


def as_json(value):
    return json.dumps(value, indent=2)

"""The Encounter Creator: plans the next encounter toward the scene goal."""

from fictive import goals

import config
import state
from flows.common import as_json, generate_json, scene_tail, start_actor


def create_encounter(runtime, adv):
    """Returns a validated plan: {"encounter", "criteria", "steps", "characters", "secrets"}."""
    start_actor(
        runtime, "encounter_creator",
        premise=adv.get("premise", ""),
        goal=adv["scene_goal"],
        criteria=adv["criteria"],
        progress=goals.summary(runtime),
        game=as_json(state.game(runtime)),
        locations=as_json(adv["locations"]),
        flags=as_json(adv["flags"]),
        character_sheets=as_json(character_sheets_view(adv, state.characters(runtime))),
        scene=scene_tail(runtime),
        max_steps=config.MAX_ENCOUNTER_STEPS,
    )
    return generate_json(runtime, lambda plan: check_plan(adv, plan))


def character_sheets_view(adv, sheets):
    """Every character sheet but the player character's, marked with whether one is already in play."""
    in_play = {sheet["sheet_id"] for sheet in sheets.values()}
    return {
        sheet_id: {**entry, "in_play": sheet_id in in_play}
        for sheet_id, entry in adv["character_sheets"].items()
        if sheet_id != adv["player_character"]
    }


def check_plan(adv, plan):
    for field in ("encounter", "criteria", "secrets"):
        if not isinstance(plan[field], str) or not plan[field].strip():
            raise ValueError(f'"{field}" needs some text')
    steps = plan["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= config.MAX_ENCOUNTER_STEPS:
        raise ValueError(f'"steps" must be a list of 1 to {config.MAX_ENCOUNTER_STEPS} steps')
    for step in steps:
        if not isinstance(step["text"], str) or not step["text"].strip():
            raise ValueError("every step needs text")
        if not isinstance(step.get("turn_budget"), int) or step["turn_budget"] < 1:
            step["turn_budget"] = config.STEP_TURN_BUDGET
    if not isinstance(plan["characters"], list):
        raise TypeError('"characters" must be a list')
    for sheet_id in plan["characters"]:
        if sheet_id not in adv["character_sheets"] or sheet_id == adv["player_character"]:
            raise ValueError(f"{sheet_id!r} is not a character sheet other than the player character's")
    return plan

"""The Character State Handler: proposes changes to the sheets of the characters in the scene."""

import state
from flows.common import as_json, check_changes, describe_check, generate_json, scene_tail, start_actor


def update_characters(runtime, adv, turn):
    """Returns the proposed character changes; code checks and applies them."""
    sheets, game_state = state.characters(runtime), state.game(runtime)
    start_actor(
        runtime, "character_state_handler",
        sheets=as_json([state.full_sheet(adv, sheets[char_id]) for char_id in game_state["present"]]),
        message=turn["message"],
        ruling=as_json(turn["ruling"]),
        check=describe_check(turn["check"]),
        scene=scene_tail(runtime),
    )
    try:
        return generate_json(runtime, check_changes)
    except RuntimeError as exc:
        print(f"[character_state_handler] {exc}; no character changes this turn")
        return []

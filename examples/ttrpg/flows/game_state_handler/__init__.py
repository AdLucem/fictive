"""The Game State Handler: proposes changes to the world."""

import state
from flows.common import as_json, check_changes, describe_check, generate_json, scene_tail, start_actor


def update_world(runtime, adv, turn):
    """Returns the proposed game changes; code checks and applies them."""
    roster = {
        roster_id: {"name": entry["name"], "kind": entry["kind"], "unique": entry["unique"]}
        for roster_id, entry in adv["roster"].items()
    }
    start_actor(
        runtime, "game_state_handler",
        game=as_json(state.game(runtime)),
        locations=as_json(adv["locations"]),
        flags=as_json(adv["flags"]),
        roster=as_json(roster),
        message=turn["message"],
        ruling=as_json(turn["ruling"]),
        check=describe_check(turn["check"]),
        scene=scene_tail(runtime),
    )
    try:
        return generate_json(runtime, check_changes)
    except RuntimeError as exc:
        print(f"[game_state_handler] {exc}; no game changes this turn")
        return []

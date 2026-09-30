"""Encounters: children of the scene goal, with their steps as children of their own."""

from fictive import goals

import config
import state


def current(rt):
    """The id of the encounter in progress, or None (clearing a finished one from the game state)."""
    game_state = state.game(rt)
    encounter_id = game_state["encounter"]
    if encounter_id is None:
        return None
    if goals.get(rt, encounter_id)["status"] in goals.OPEN_STATUSES:
        return encounter_id
    game_state["encounter"] = None
    state.save_game(rt, game_state)
    return None


def start(rt, adv, plan):
    """Add the Encounter Creator's plan to the goal tree and bring its characters in; returns its id."""
    root = goals.tree(rt)["root"]
    try:
        encounter_id = goals.add(
            rt, plan["encounter"], parent=root, criteria=plan["criteria"], complete_with_children=True,
            data={"kind": "encounter", "secrets": plan["secrets"], "tone": None},
        )
        for step in plan["steps"]:
            goals.add(rt, step["text"], parent=encounter_id, criteria=step.get("criteria"),
                      turn_budget=step["turn_budget"])
    except goals.GoalError as exc:
        print(f"[goals] could not start the encounter: {exc}")
        return None

    sheets, game_state = state.characters(rt), state.game(rt)
    for sheet_id in plan["characters"]:
        state.spawn(adv, sheets, game_state, sheet_id)
    game_state["encounter"] = encounter_id
    state.save_characters(rt, sheets)
    state.save_game(rt, game_state)
    return encounter_id


def set_tone(rt, encounter_id, tone):
    # goals.update replaces `data` whole, so read it, change it, and write it all back.
    data = goals.get(rt, encounter_id)["data"]
    data["tone"] = tone
    goals.update(rt, encounter_id, data=data)

"""The Adjudicator: how the player's message is handled, and whether it needs a check."""

import config
import state
from flows.common import as_json, generate_json, scene_tail, start_actor


def adjudicate(runtime, adv):
    """Returns the ruling: {"kind", "check", "ability", "tier", "stakes"}."""
    sheets, game_state = state.characters(runtime), state.game(runtime)
    location = adv["locations"][game_state["location"]]
    present = [
        {"id": char_id, "name": state.entry(adv, sheets[char_id])["name"],
         "description": state.entry(adv, sheets[char_id])["description"]}
        for char_id in game_state["present"]
    ]
    start_actor(
        runtime, "adjudicator",
        scene=scene_tail(runtime),
        location=f"{location['name']}: {location['description']}",
        present=as_json(present),
        message=runtime.store_get(config.LAST_MESSAGE_KEY),
    )
    return generate_json(runtime, check_ruling)


def check_ruling(ruling):
    if ruling["kind"] not in ("in_fiction", "ooc"):
        raise ValueError('"kind" must be "in_fiction" or "ooc"')
    if not isinstance(ruling["check"], bool):
        raise TypeError('"check" must be true or false')
    if ruling["kind"] == "ooc":
        ruling["check"] = False
    if ruling["check"] and (ruling.get("ability") not in config.ABILITIES or ruling.get("tier") not in config.DC_BY_TIER):
        raise ValueError("a check needs a known ability and tier")
    if not isinstance(ruling.get("stakes"), dict):
        ruling["stakes"] = {}
    return ruling

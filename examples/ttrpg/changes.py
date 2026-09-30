"""Checking and applying the changes the state handlers propose."""

import config
import state

CHARACTER_FIELDS = ("lp", "status", "add_condition", "remove_condition", "disposition", "visible", "note")
GAME_FIELDS = ("move_to", "set_flag", "reveal", "enter", "leave")


class Rejected(ValueError):
    """A proposed change that breaks the rules. It is dropped; the rest still apply."""


def _require(ok, why):
    if not ok:
        raise Rejected(why)


def _require_text(value):
    _require(isinstance(value, str) and value.strip(), "needs some text")


def _one_field(change, allowed, extra):
    """The one field in `allowed` that `change` sets. Anything outside `allowed` and `extra` is rejected."""
    _require(isinstance(change, dict), "not a JSON object")
    unknown = [key for key in change if key not in allowed and key not in extra]
    _require(not unknown, f"can't change {', '.join(unknown)}")
    fields = [key for key in change if key in allowed]
    _require(len(fields) == 1, f"needs exactly one of {', '.join(allowed)}")
    return fields[0]


def _apply_all(proposed, apply_one):
    applied = []
    for change in proposed:
        try:
            apply_one(change)
            applied.append(change)
        except (Rejected, TypeError) as exc:
            print(f"[state] rejected {change!r}: {exc}")
    return applied


# -- character changes -----------------------------------------------------


def apply_character_changes(rt, adv, proposed):
    """Apply each valid character change; returns the ones applied."""
    sheets, game_state = state.characters(rt), state.game(rt)
    applied = _apply_all(proposed, lambda change: _apply_character_change(sheets, game_state, change))
    state.save_characters(rt, sheets)
    return applied


def _apply_character_change(sheets, game_state, change):
    field = _one_field(change, CHARACTER_FIELDS, extra=("character", "reason"))
    _require(change.get("character") in game_state["present"], f"{change.get('character')!r} is not in the scene")
    sheet, value = sheets[change["character"]], change[field]
    if field == "lp":
        _require(isinstance(value, int) and not isinstance(value, bool), "lp must be a whole number")
        sheet["lp"] = max(0, min(config.MAX_LP, sheet["lp"] + value))
        if sheet["lp"] == 0 and sheet["status"] != "dead":
            sheet["status"] = "down"
    elif field == "status":
        _require(value in config.STATUSES, f"status must be one of {', '.join(config.STATUSES)}")
        sheet["status"] = value
    elif field == "add_condition":
        _require_text(value)
        if value not in sheet["conditions"]:
            sheet["conditions"].append(value)
    elif field == "remove_condition":
        _require(value in sheet["conditions"], f"{sheet['id']} has no condition {value!r}")
        sheet["conditions"].remove(value)
    elif field == "disposition":
        _require(value in config.DISPOSITIONS, f"disposition must be one of {', '.join(config.DISPOSITIONS)}")
        sheet["disposition"] = value
    elif field == "visible":
        _require(isinstance(value, bool), "visible must be true or false")
        sheet["visible"] = value
    elif field == "note":
        _require_text(value)
        sheet["notes"].append(value)


# -- game changes ------------------------------------------------------------


def apply_game_changes(rt, adv, proposed):
    """Apply each valid game change; returns the ones applied."""
    sheets, game_state = state.characters(rt), state.game(rt)
    applied = _apply_all(proposed, lambda change: _apply_game_change(adv, sheets, game_state, change))
    state.save_characters(rt, sheets)
    state.save_game(rt, game_state)
    return applied


def _apply_game_change(adv, sheets, game_state, change):
    field = _one_field(change, GAME_FIELDS, extra=("via", "value", "reason"))
    value = change[field]
    if field == "move_to":
        # Any declared location, not only an exit: actions can open new routes (README "Game State Handler").
        _require(value in adv["locations"], f"{value!r} is not a declared location")
        _require(value != game_state["location"], "the player character is already there")
        game_state["moves"].append({"from": game_state["location"], "to": value, "via": str(change.get("via") or "")})
        game_state["location"] = value
    elif field == "set_flag":
        _require(value in adv["flags"], f"{value!r} is not a declared flag")
        _require(isinstance(change.get("value"), bool), "a flag's value must be true or false")
        game_state["flags"][value] = change["value"]
    elif field == "reveal":
        _require_text(value)
        if value not in game_state["revealed"]:
            game_state["revealed"].append(value)
    elif field == "enter":
        _require(value in adv["character_sheets"] and value != adv["player_character"], f"{value!r} can't enter")
        state.spawn(adv, sheets, game_state, value)
    elif field == "leave":
        _require(value in game_state["present"] and value != adv["player_character"], f"{value!r} can't leave")
        game_state["present"].remove(value)


# -- telling the narrator ----------------------------------------------------


def describe(rt, adv, applied):
    """Sentences about the applied changes that the player is allowed to know."""
    sheets = state.characters(rt)
    lines = (_describe(adv, sheets, change) for change in applied)
    return [line for line in lines if line]


def _describe(adv, sheets, change):
    if "character" in change:
        return _describe_character(adv, sheets[change["character"]], change)
    if "move_to" in change:
        place = adv["locations"][change["move_to"]]["name"]
        return f"The player character is now in {place}. How: {change.get('via') or 'unspecified'}."
    if "set_flag" in change:
        text = adv["flags"][change["set_flag"]]["description"]
        return text if change["value"] else f"No longer true: {text}"
    if "reveal" in change:
        return f"The player character has learned: {change['reveal']}"
    if "enter" in change:
        return f"{adv['character_sheets'][change['enter']]['name']} enters the scene."
    if "leave" in change:
        return f"{state.entry(adv, sheets[change['leave']])['name']} leaves the scene."
    return None


def _describe_character(adv, sheet, change):
    who = state.entry(adv, sheet)["name"]
    if "lp" in change:
        if sheet["visible"]:
            verb = "loses" if change["lp"] < 0 else "regains"
            line = f"{who} {verb} {abs(change['lp'])} LP ({sheet['lp']} left)."
        else:
            line = f"{who} is {'hurt' if change['lp'] < 0 else 'recovering'}."
        return line + (f" {who} is down." if sheet["lp"] == 0 else "")
    if "status" in change:
        return f"{who} is now {change['status']}."
    if "add_condition" in change:
        return f"{who} is now {change['add_condition']}."
    if "remove_condition" in change:
        return f"{who} is no longer {change['remove_condition']}."
    if "disposition" in change:
        return f"{who} is now {change['disposition']} toward the player character."
    if change.get("visible"):
        abilities = ", ".join(f"{name} {value:+d}" for name, value in state.entry(adv, sheet)["abilities"].items())
        return f"The player character now knows what {who} is capable of: {abilities}; {sheet['lp']} LP."
    return None  # notes, and hiding a sheet, are never narrated

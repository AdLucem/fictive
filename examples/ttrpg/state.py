"""The adventure file, and the character sheets and game state kept in the store."""

import copy
import json

import config

CHARACTERS_KEY = "ttrpg_characters"
GAME_KEY = "ttrpg_game"


# -- the adventure file --------------------------------------------------


def load_adventure(path=config.ADVENTURE_FILE):
    with open(path) as f:
        adventure = json.load(f)
    check_adventure(adventure)
    return adventure


def check_adventure(adv):
    """Raise ValueError if the adventure file breaks the README's rules."""
    roster, locations = adv["roster"], adv["locations"]
    pc = roster.get(adv["player_character"])
    if pc is None or pc["kind"] != "pc":
        raise ValueError(f"player_character {adv['player_character']!r} must be a roster entry of kind 'pc'")
    if adv["start_location"] not in locations:
        raise ValueError(f"start_location {adv['start_location']!r} is not a declared location")
    for location_id, location in locations.items():
        for exit_id in location["exits"]:
            if exit_id not in locations:
                raise ValueError(f"{location_id} has an exit to undeclared location {exit_id!r}")
    for roster_id, entry in roster.items():
        abilities = entry["abilities"]
        if set(abilities) != set(config.ABILITIES) or not all(
            isinstance(value, int) and -5 <= value <= 5 for value in abilities.values()
        ):
            raise ValueError(f"{roster_id} needs {', '.join(config.ABILITIES)}, each a whole number from -5 to 5")
    for name, flag in adv["flags"].items():
        if not isinstance(flag.get("initial"), bool):
            raise ValueError(f"flag {name!r} needs an 'initial' of true or false")


# -- reading and writing the store ----------------------------------------


def _read(rt, key):
    return copy.deepcopy(rt.store_get(key))


def _write(rt, key, value):
    rt.store_set(key, json.loads(json.dumps(value)))


def characters(rt):
    return _read(rt, CHARACTERS_KEY) or {}


def save_characters(rt, sheets):
    _write(rt, CHARACTERS_KEY, sheets)


def game(rt):
    return _read(rt, GAME_KEY)


def save_game(rt, game_state):
    _write(rt, GAME_KEY, game_state)


# -- setting up and bringing characters into play -------------------------


def init_state(rt, adv):
    """The state at the start of the adventure: the player character alone at the start location."""
    sheets = {}
    game_state = {
        "location": adv["start_location"],
        "present": [],
        "flags": {name: flag["initial"] for name, flag in adv["flags"].items()},
        "encounter": None,
        "revealed": [],
        "moves": [],
    }
    spawn(adv, sheets, game_state, adv["player_character"])
    save_characters(rt, sheets)
    save_game(rt, game_state)


def new_sheet(adv, char_id, roster_id):
    return {
        "id": char_id,
        "roster_id": roster_id,
        "lp": config.MAX_LP,
        "status": "active",
        "conditions": [],
        "disposition": "neutral",
        "visible": adv["roster"][roster_id]["visible"],
        "notes": [],
    }


def spawn(adv, sheets, game_state, roster_id):
    """Bring a roster character into play and into the scene; returns its id in play.

    Edits `sheets` and `game_state` in place; the caller saves them. A unique
    character keeps its roster id and is never copied; a non-unique one gets the
    next free numbered id.
    """
    if adv["roster"][roster_id]["unique"]:
        char_id = roster_id
    else:
        n = 1
        while f"{roster_id}_{n}" in sheets:
            n += 1
        char_id = f"{roster_id}_{n}"
    if char_id not in sheets:
        sheets[char_id] = new_sheet(adv, char_id, roster_id)
    if char_id not in game_state["present"]:
        game_state["present"].append(char_id)
    return char_id


# -- reading sheets --------------------------------------------------------


def entry(adv, sheet):
    """The roster entry a sheet was made from: name, kind, abilities, description, secrets."""
    return adv["roster"][sheet["roster_id"]]


def full_sheet(adv, sheet):
    """Everything about a character, secrets included. For game-master actors only."""
    return {**entry(adv, sheet), **sheet}


def modifier(adv, sheet, ability):
    return entry(adv, sheet)["abilities"][ability]


def perceived(adv, sheet):
    """What the player character can perceive of a character: numbers only if its sheet is visible."""
    card = entry(adv, sheet)
    text = f"{card['name']}: {card['description']}"
    if sheet["visible"]:
        conditions = ", ".join(sheet["conditions"]) or "none"
        text += f" [LP {sheet['lp']}/{config.MAX_LP}, {sheet['status']}, conditions: {conditions}]"
    return text


def pc_out(rt, adv):
    """Whether the player character can no longer act."""
    return characters(rt)[adv["player_character"]]["status"] in ("down", "dead")

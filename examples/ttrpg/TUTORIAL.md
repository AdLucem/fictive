# Tutorial: building the `ttrpg` scenario

This tutorial walks through implementing the tabletop roleplaying game described in [README.md](README.md) as a `fictive` scenario. Each step gives you one file, explains the `fictive` ideas it relies on, and ends with a quick check where one makes sense. It follows the structure of `.local/inft`, the most complete scenario in the repository, so reading the two side by side is a good way to learn the project.

## What you're building

The scenario is a **library-runtime** scenario: Python generator functions ("flows") drive the actors by issuing commands through `fictive.Runtime`, and the web backend (`fictive/web/`) runs them. `REPOSITORY_DOCS.md` explains both under `fictive/library_runtime.py` and `fictive/web/`.

One player turn goes like this (README, "Turn Order"):

```
player message ──> generator (main actor)
                    ├─ judge                    is the encounter step in focus done?
                    ├─ adjudicator              in fiction or out of character? which check, how hard?
                    ├─ code: roll d20 + modifier vs DC -> result band; show the roll
                    ├─ character_state_handler  proposes sheet changes -> code checks and applies them
                    ├─ game_state_handler       proposes world changes -> code checks and applies them
                    ├─ encounter_creator        only when no encounter is in progress
                    ├─ tone_handler             only when an encounter starts, or on a complication
                    └─ generator narrates       the only reply the player sees
```

The split to keep in mind throughout: **LLM actors make judgements; code does arithmetic and enforces rules.** Every actor except the generator replies in JSON, and code decides what to do with it.

## Final layout

```
examples/ttrpg/
  README.md               # the design (already written)
  TUTORIAL.md             # this file
  fictive_scenario.py     # the contract the web backend reads          (step 12)
  config.py               # paths, constants, prompt lookup             (step 1)
  adventure.json          # the adventure: roster, map, flags           (step 2)
  rules.py                # dice, DCs and result bands                  (step 3)
  state.py                # character sheets and game state             (step 4)
  changes.py              # checking and applying proposed changes      (step 5)
  encounters.py           # encounters in the goal tree                 (step 6)
  special_commands.py     # /help /save /load /list /quit /sheet /where /dc   (step 11)
  flows/
    __init__.py           # empty
    common.py             # helpers every sub-actor flow shares         (step 7)
    judge/__init__.py                      # (step 8)
    adjudicator/__init__.py                # (step 8)
    character_state_handler/__init__.py    # (step 8)
    game_state_handler/__init__.py         # (step 8)
    encounter_creator/__init__.py          # (step 8)
    tone_handler/__init__.py               # (step 8)
    generator/__init__.py                  # (step 9)
  prompts/
    <actor>/<actor>_<key>.txt              # already written (step 10)
```

Two conventions, which differ from `.local/inft`:

- **Prompts** are never given a variable name of their own. A prompt is found from the prompts folder, an actor name and an optional key: actor `generator` with key `system` is `prompts/generator/generator_system.txt` (or `.md`). An actor with no key is `prompts/<actor>/<actor>.txt`.
- **Flows** live in `flows/<actor>/`, grouped by the actor they belong to. Short flows go in the package's `__init__.py`. A flow longer than 30 lines gets a file of its own in its actor's package, such as `flows/generator/play.py`. Every flow in this tutorial is under 30 lines, so each actor's flows fit in its `__init__.py`. If you grow one past 30 lines, move it into its own file. Don't import that file from the package's `__init__.py`: the new file imports helpers from `__init__.py`, so the imports would be circular.

Everything imports "flat" (`import config`, `from flows.common import ...`) because `fictive/web/scenario.py` puts the scenario's own directory on `sys.path` before importing it.

The prompt files in `prompts/` are already written (step 10 explains them); you write everything else. To follow along, start from an installed repository (`pip install -e .`) and work in `examples/ttrpg/`.

---

## Step 1: `config.py`

`config.py` holds the paths, the game's constants, the actor list, and the one function every piece of code uses to find a prompt.

```python
"""Paths, constants and prompt lookup for the ttrpg scenario."""

import string
from pathlib import Path

SCENARIO_ROOT = Path(__file__).resolve().parent
SCENARIO_DIR = SCENARIO_ROOT
PROMPTS_DIR = SCENARIO_ROOT / "prompts"
ADVENTURE_FILE = SCENARIO_ROOT / "adventure.json"

PROMPT_SUFFIXES = (".txt", ".md")


def prompt_path(actor, key=None):
    """The prompt file for `actor` and optional `key`: prompts/<actor>/<actor>[_<key>].txt or .md."""
    stem = f"{actor}_{key}" if key else actor
    candidates = [PROMPTS_DIR / actor / f"{stem}{suffix}" for suffix in PROMPT_SUFFIXES]
    found = [path for path in candidates if path.is_file()]
    if len(found) != 1:
        problem = "No prompt file" if not found else "Multiple prompt files"
        raise FileNotFoundError(f"{problem} for actor {actor!r}, key {key!r}: " + " / ".join(map(str, candidates)))
    return found[0]


def load_prompt(actor, key=None, **fields):
    """A prompt's text, with its `$name` placeholders filled in from `fields`."""
    text = prompt_path(actor, key).read_text()
    return string.Template(text).substitute(fields) if fields else text


# Rules (README "Checks").
ABILITIES = ("strength", "knowledge", "mana")
DC_BY_TIER = {"easy": 8, "medium": 12, "hard": 16, "very_hard": 20}
BAND_TEXT = {
    "strong_success": "strong success: it works, and the character gains something extra",
    "success": "success: it works",
    "success_at_cost": "success at a cost: it works but at a price, or it fails but gains something",
    "failure_complication": "failure with a complication: it fails, and the situation gets worse",
}

# Character sheets (README "Character Sheets").
MAX_LP = 20
STATUSES = ("active", "down", "dead", "fled")
DISPOSITIONS = ("hostile", "neutral", "friendly")

TONES = ("tense", "eerie", "comic", "triumphant", "somber", "mysterious", "desperate")

# How many times a JSON-replying actor may retry a reply that doesn't parse.
MAX_JSON_RETRIES = 5
# How much of the story the sub-actors are shown.
SCENE_TAIL_CHARS = 4000

# Encounters, as goals under the scene goal (see fictive/goals.py).
MAX_ENCOUNTER_STEPS = 5
STEP_TURN_BUDGET = 6
GOAL_LIMITS = {"max_goals": 200, "max_open_children": MAX_ENCOUNTER_STEPS + 1}

# Store keys.
LAST_MESSAGE_KEY = "last_message"
LAST_CHECK_KEY = "ttrpg_last_check"
LAST_VIEW_KEY = "ttrpg_last_view"

# None means a plain Actor; "generator" is fictive's Generator, whose output is its whole scene.
ACTOR_TYPES = {
    "generator": "generator",
    "judge": None,
    "adjudicator": None,
    "character_state_handler": None,
    "game_state_handler": None,
    "encounter_creator": None,
    "tone_handler": None,
}
```

**Why `string.Template`?** Prompts contain JSON examples full of `{` and `}`, which `str.format` would try to fill in. `Template` only looks for `$name`.

**Framework note: how prompts reach an actor.** There are two ways, and it matters which one you use:

- A **system prompt** is passed as a `Path` to `runtime.system(...)`. The interpreter sees a path to an existing file and reads it (`Interpreter.parse_prompt_object`).
- A **filled-in template** is a string, and goes through `runtime.append(text)`, which adds it to the working actor's history as a user turn. Don't pass it to `runtime.generate(prompt=...)`: that tries to resolve the string as a file path or a `var:` lookup.

---

## Step 2: `adventure.json`

This is the README's example adventure, plus three additions: a `premise` for the opening narration, an `abbey_cloister` location outside the crypt, and a `relic_recovered` flag. The additions let the adventure actually be finished: the criteria now describe a state the Game State Handler can reach.

```json
{
  "premise": "The Relic of Saint Veyra, a silver reliquary said to calm floodwaters, was lost when the crypt beneath the abbey flooded a century ago. The abbey's archivist has found the crypt's old plans and gone down alone to bring it back.",
  "scene_goal": "Recover the relic from the flooded crypt",
  "criteria": "Mira is back in the abbey cloister holding the relic",
  "player_character": "mira",
  "start_location": "crypt_entrance",
  "roster": {
    "mira": {
      "name": "Mira", "kind": "pc", "unique": true,
      "abilities": {"strength": 1, "knowledge": 3, "mana": -1},
      "description": "A young archivist with an axe she barely knows how to use.",
      "visible": true
    },
    "ferryman": {
      "name": "The Ferryman", "kind": "npc", "unique": true,
      "abilities": {"strength": -1, "knowledge": 4, "mana": 2},
      "description": "A hooded figure poling a flat boat across the black water.",
      "secrets": "He drowned here a century ago and cannot leave the crypt. He knows the relic lies in the lower vault.",
      "visible": false
    },
    "drowned_dead": {
      "name": "Drowned Dead", "kind": "monster", "unique": false,
      "abilities": {"strength": 3, "knowledge": -4, "mana": 0},
      "description": "A bloated corpse that drags itself out of the water.",
      "visible": false
    }
  },
  "locations": {
    "abbey_cloister": {
      "name": "Abbey Cloister",
      "description": "A quiet square of worn flagstones around a dry fountain.",
      "exits": ["crypt_entrance"]
    },
    "crypt_entrance": {
      "name": "Crypt Entrance",
      "description": "Worn steps descend into cold, standing water.",
      "exits": ["abbey_cloister", "flooded_nave"]
    },
    "flooded_nave": {
      "name": "Flooded Nave",
      "description": "A drowned hall, crossed by a rotting rope bridge.",
      "exits": ["crypt_entrance", "lower_vault"]
    },
    "lower_vault": {
      "name": "Lower Vault",
      "description": "A sealed chamber below the waterline.",
      "exits": ["flooded_nave"]
    }
  },
  "flags": {
    "bridge_collapsed": {"initial": false, "description": "The rope bridge over the nave has fallen into the water."},
    "ferryman_paid": {"initial": false, "description": "Mira has paid the Ferryman's toll."},
    "relic_recovered": {"initial": false, "description": "Mira holds the Relic of Saint Veyra."}
  }
}
```

---

## Step 3: `rules.py`

This is pure Python with no runtime: the mechanical rules from the README's "Checks" section. Keeping it free of `fictive` makes it trivial to check.

```python
"""The mechanical rules: rolling a check and working out its result band."""

import random

import config


def result_band(die, total, dc):
    """The README's four result bands; a natural 20 or 1 overrides the total."""
    if die == 20:
        return "strong_success"
    if die == 1:
        return "failure_complication"
    margin = total - dc
    if margin >= 5:
        return "strong_success"
    if margin >= 0:
        return "success"
    if margin >= -4:
        return "success_at_cost"
    return "failure_complication"


def roll_check(ability, modifier, tier, rng=random):
    """Roll d20 + `modifier` against the DC for `tier`."""
    die = rng.randint(1, 20)
    dc = config.DC_BY_TIER[tier]
    total = die + modifier
    return {
        "ability": ability, "die": die, "modifier": modifier, "total": total,
        "tier": tier, "dc": dc, "band": result_band(die, total, dc),
    }


def roll_line(check):
    """The roll as the player sees it, such as "Strength: 14 + 3 = 17". No DC, no band."""
    sign = "+" if check["modifier"] >= 0 else "-"
    return f"{check['ability'].capitalize()}: {check['die']} {sign} {abs(check['modifier'])} = {check['total']}"
```

**Check your work** (from `examples/ttrpg/`):

```bash
python -c "
from rules import result_band as b
assert [b(10, 17, 12), b(10, 12, 12), b(10, 8, 12), b(10, 7, 12)] == ['strong_success', 'success', 'success_at_cost', 'failure_complication']
assert b(1, 30, 12) == 'failure_complication' and b(20, 15, 16) == 'strong_success'
print('rules ok')"
```

---

## Step 4: `state.py`

This module loads and checks the adventure file, and keeps the two live states, the character sheets and the game state, in the interpreter's **store**.

**Framework note: why the store, and why all the copying.** The store (`runtime.store_get` / `store_set`) is saved with the session, so saving, loading, rewriting a message and forking a session all carry the game state along for free. `fictive/goals.py` keeps its goal tree in the store the same way. There's one trap. The web backend's rewrite and fork checkpoints (`fictive/web/chat.py`) copy the store only **one level deep**, so if you edit a dict you got from the store in place, you also edit the checkpoint's copy, and a rewrite would silently keep the discarded turn's damage. `goals.py` therefore deep-copies on every read and stores a fresh copy on every write, and so does this module (`_read` / `_write`). The JSON round trip on write also catches anything that wouldn't survive being saved.

```python
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
```

`spawn` edits the dicts it's given instead of reading and saving the store itself. That matters in step 5: the Game State Handler's `enter` change spawns a character while `apply_game_changes` holds its own copy of the game state. If `spawn` saved separately, the caller's later save would overwrite it.

---

## Step 5: `changes.py`

The state handlers never rewrite state. They propose changes, and this module checks each change against the README's rules ("Changes"). It applies the valid ones and prints and drops the rest. It also turns the applied changes into sentences the narrator is allowed to see.

```python
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
        _require(value in adv["roster"] and value != adv["player_character"], f"{value!r} can't enter")
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
        return f"{adv['roster'][change['enter']]['name']} enters the scene."
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
```

**Check your work.** A fake runtime with nothing but a store lets you exercise `state` and `changes` without a model. Save this in a scratch file (not under `test/`) and run it from `examples/ttrpg/`:

```python
import state, changes

class FakeRuntime:
    def __init__(self):
        self.store = {}
    def store_get(self, key, default=None):
        value = self.store.get(key)
        return default if value is None else value
    def store_set(self, key, value):
        self.store[key] = value

rt, adv = FakeRuntime(), state.load_adventure()
state.init_state(rt, adv)
changes.apply_game_changes(rt, adv, [{"enter": "drowned_dead"}, {"enter": "drowned_dead"}, {"enter": "ferryman"}, {"enter": "ferryman"}])
assert state.game(rt)["present"] == ["mira", "drowned_dead_1", "drowned_dead_2", "ferryman"]

applied = changes.apply_character_changes(rt, adv, [
    {"character": "drowned_dead_1", "lp": -25},           # clamps to 0 and goes down
    {"character": "mira", "abilities": {"strength": 5}},  # roster field: rejected
    {"character": "nobody", "lp": -1},                    # not in the scene: rejected
])
assert len(applied) == 1 and state.characters(rt)["drowned_dead_1"]["status"] == "down"

applied = changes.apply_game_changes(rt, adv, [
    {"move_to": "lower_vault", "via": "Smashed through the vault door"},  # not an exit, but allowed
    {"set_flag": "moon_is_up", "value": True},                             # undeclared: rejected
    {"move_to": "the_moon"},                                               # undeclared: rejected
])
assert len(applied) == 1 and state.game(rt)["moves"][-1]["to"] == "lower_vault"
print(changes.describe(rt, adv, applied))
print("state and changes ok")
```

---

## Step 6: `encounters.py`

Encounters are kept in `fictive`'s **goal tree** (`fictive/goals.py`), not in our own state.

**Framework note: goals.** A goal tree is worked depth-first: the deepest open goal is the *focus*. The adventure's scene goal is the root; each encounter is a child of the root, and each encounter step is a child of the encounter. So the focus is always the current step. `goals.judge` closes the focus when the story shows it done or impossible, and a goal marked `complete_with_children` closes itself when its last child closes. That's how an encounter ends. `goals.tick` counts a turn against every goal on the path to the focus, and fails a step whose `turn_budget` runs out, which moves the story on. `.local/inft/flows.py`'s `add_plan` is the model for `start` below.

Hidden information goes in a goal's `data`, which the judge's goal summary never shows and which our narrator's instructions (step 9) never include.

```python
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
    for roster_id in plan["characters"]:
        state.spawn(adv, sheets, game_state, roster_id)
    game_state["encounter"] = encounter_id
    state.save_characters(rt, sheets)
    state.save_game(rt, game_state)
    return encounter_id


def set_tone(rt, encounter_id, tone):
    # goals.update replaces `data` whole, so read it, change it, and write it all back.
    data = goals.get(rt, encounter_id)["data"]
    data["tone"] = tone
    goals.update(rt, encounter_id, data=data)
```

---

## Step 7: `flows/common.py`

Create `flows/__init__.py` as an empty file, then `flows/common.py`.

**Framework note: calling another actor.** `call_actor(runtime, "adjudicator", some_flow)` (`fictive/library_runtime.py`) pushes that actor onto the interpreter's call stack and makes it the *working actor*. It then runs `some_flow(runtime)`, where every command such as `runtime.system`, `runtime.append` or `runtime.generate` acts on the adjudicator's own history, and pops the actor when the flow returns. What `call_actor` gives back is the flow's return value. One trap: **if the flow returns `None`, `call_actor` gives back the actor's latest text instead**, so every sub-actor flow here returns something that isn't `None`, even when there's nothing to report (`[]` or `""`). `call_actor` is itself a generator, so you always write `result = yield from call_actor(...)`. That lets a called actor, in principle, stop and ask the human something.

**Framework note: getting reliable JSON.** This is the pattern `.local/inft/flows.py`'s routers use. Generate, try to parse and validate, and on failure remove the bad reply (`history.remove()`) and generate again. The retry then sees exactly the history the first attempt saw. `goals.parse_json_object` tolerates markdown fences and stray prose around the object.

```python
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
```

`runtime.refresh()` clears the actor's history, so every call starts from a clean slate. The sub-actors are stateless; everything they need is in the prompt.

---

## Step 8: the sub-actor flows

Each actor gets a package: create `flows/<actor>/__init__.py` for each of the six below.

### `flows/judge/__init__.py`

`goals.judge` already runs the named actor through `call_actor` and applies its verdict to the tree, so this flow is a thin wrapper that supplies our own system prompt. Because `goals.judge` calls the actor itself, call `judge_focus` directly with `yield from`, never inside another `call_actor`.

```python
"""The Judge: closes the goal in focus when the story shows it done or impossible."""

from fictive import goals

import config


def judge_focus(runtime):
    return (yield from goals.judge(runtime, "judge", system=config.prompt_path("judge", "system")))
```

### `flows/adjudicator/__init__.py`

The Adjudicator is never shown anyone's ability modifiers (README).

```python
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
```

A ruling that never parses raises and ends the turn with an error. Without a ruling the turn can't go on. In the web UI, rewriting the message is the way out, just as in `.local/inft`.

### `flows/character_state_handler/__init__.py`

`turn` is a dict built by the generator's flow in step 9: `{"message", "ruling", "check"}`.

```python
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
```

Unlike the Adjudicator, a failure here doesn't end the turn: a turn with no sheet changes is still playable.

### `flows/game_state_handler/__init__.py`

```python
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
```

### `flows/encounter_creator/__init__.py`

```python
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
        roster=as_json(roster_view(adv, state.characters(runtime))),
        scene=scene_tail(runtime),
        max_steps=config.MAX_ENCOUNTER_STEPS,
    )
    return generate_json(runtime, lambda plan: check_plan(adv, plan))


def roster_view(adv, sheets):
    """Every roster character but the player character, marked with whether one is already in play."""
    in_play = {sheet["roster_id"] for sheet in sheets.values()}
    return {
        roster_id: {**entry, "in_play": roster_id in in_play}
        for roster_id, entry in adv["roster"].items()
        if roster_id != adv["player_character"]
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
    for roster_id in plan["characters"]:
        if roster_id not in adv["roster"] or roster_id == adv["player_character"]:
            raise ValueError(f"{roster_id!r} is not a roster character other than the player character")
    return plan
```

### `flows/tone_handler/__init__.py`

```python
"""The Tone Handler: picks the mood the narrator uses for the encounter in progress."""

from fictive import goals

import config
import state
from flows.common import generate_json, scene_tail, start_actor


def pick_tone(runtime, adv, reason):
    """Returns one of config.TONES, or "" if none could be picked."""
    encounter = goals.get(runtime, state.game(runtime)["encounter"])
    start_actor(
        runtime, "tone_handler",
        encounter=encounter["text"], reason=reason, scene=scene_tail(runtime), tones=", ".join(config.TONES),
    )
    try:
        return generate_json(runtime, check_tone)
    except RuntimeError as exc:
        print(f"[tone_handler] {exc}; the tone is unchanged")
        return ""


def check_tone(reply):
    if reply["tone"] not in config.TONES:
        raise ValueError(f'"tone" must be one of {", ".join(config.TONES)}')
    return reply["tone"]
```

---

## Step 9: `flows/generator/__init__.py`

The generator is the **main actor**. `play` is the scenario's entry flow: it runs as the generator, calls every other actor, and is the only flow that generates something the player sees.

**Framework notes for this step:**

- **`ask`** suspends the flow until the player answers: `message = yield from ask(...)`. With `store=` and `history=True`, the answer goes into the store and into the generator's history as a user turn. A message starting with `/` runs a slash command (step 11) and asks again.
- **Hidden instructions.** The narrator is steered by appending a user turn wrapped by `format_instructions` (`fictive/data_structures.py`): `(INSTRUCTIONS: ...)`. `get_scene()` and the web transcript hide those turns, so neither the player nor the sub-actors' `scene_tail` ever see them.
- **`generate(visible=True)` + `show_reply()`** is how a flow says "the player sees this reply now". The web UI's live mode shows only these.
- **Resuming.** A flow can't be rewound. When a session is loaded, or a message rewritten or forked, the web backend restores the store and histories and then runs `play` again from the top with `RESUMED_STORE_KEY` set. So `play` skips its setup when that key is set, and `goals.start_scene` is safe to call again.
- **The roll line.** `show_to_player` sets `runtime.last_visible` by hand and calls `show_reply()`. In the terminal it's simply printed. In the web UI, `WebRuntime.show_reply` (`fictive/web/chat.py`) gives any text that isn't the last visible generation a message of its own. So the player sees the roll as its own message, and it never enters the generator's history, where the narrator would see it.

Instructions go to the narrator only as player-safe text. `focus_template` uses a goal's `text` and `data.tone`, never its `criteria` or `data.secrets`, and `scene_view_note` gives numbers only for visible sheets.

```python
"""The Generator: the game master's voice. `play` is the scenario's entry flow."""

from functools import partial

from fictive import RESUMED_STORE_KEY, ask, call_actor, goals
from fictive.data_structures import format_instructions

import changes
import config
import encounters
import rules
import state
from flows.adjudicator import adjudicate
from flows.character_state_handler import update_characters
from flows.encounter_creator import create_encounter
from flows.game_state_handler import update_world
from flows.judge import judge_focus
from flows.tone_handler import pick_tone

OOC_NOTE = (
    "The player's message was out of character. Answer it briefly as the game master, "
    "out of character, and don't advance the story in this reply."
)


# -- the entry flow ------------------------------------------------------------


def play(runtime):
    """Set up the adventure (unless resuming), then trade turns with the player until it ends."""
    adv = state.load_adventure()
    if not runtime.store_get(RESUMED_STORE_KEY):
        yield from begin(runtime, adv)
    while True:
        message = yield from ask(runtime, "you> ", store=config.LAST_MESSAGE_KEY, history=True, content=False)
        notes = yield from take_turn(runtime, adv, message)
        ending = ending_note(runtime, adv)
        if ending:
            narrate(runtime, adv, [ending])
            return
        narrate(runtime, adv, notes)


def begin(runtime, adv):
    runtime.system(config.prompt_path("generator", "system"))
    state.init_state(runtime, adv)
    goals.start_scene(runtime, adv["scene_goal"], criteria=adv["criteria"], limits=config.GOAL_LIMITS)
    if (yield from next_encounter(runtime, adv, judge_scene=False)):
        yield from choose_tone(runtime, adv, "The adventure begins.")
    narrate(runtime, adv, [opening_note(adv)])


def take_turn(runtime, adv, message):
    """One player turn, in the README's turn order; returns the notes for the narrator."""
    yield from judge_focus(runtime)
    ruling = yield from call_actor(runtime, "adjudicator", partial(adjudicate, adv=adv))
    if ruling["kind"] == "ooc":
        return [OOC_NOTE]  # no roll, no state changes, no turn counted

    goals.tick(runtime)
    check = roll(runtime, adv, ruling) if ruling["check"] else None
    turn = {"message": message, "ruling": ruling, "check": check}

    proposed = yield from call_actor(runtime, "character_state_handler", partial(update_characters, adv=adv, turn=turn))
    applied = changes.apply_character_changes(runtime, adv, proposed)
    proposed = yield from call_actor(runtime, "game_state_handler", partial(update_world, adv=adv, turn=turn))
    applied += changes.apply_game_changes(runtime, adv, proposed)

    started = yield from next_encounter(runtime, adv)
    if started:
        yield from choose_tone(runtime, adv, "A new encounter begins.")
    elif check and check["band"] == "failure_complication":
        yield from choose_tone(runtime, adv, "The player's last action ended in a complication.")
    return turn_notes(ruling, check) + changes.describe(runtime, adv, applied)


# -- steps of a turn --------------------------------------------------------------


def roll(runtime, adv, ruling):
    """Roll the player character's check and show the roll to the player."""
    pc_sheet = state.characters(runtime)[adv["player_character"]]
    ability = ruling["ability"]
    check = rules.roll_check(ability, state.modifier(adv, pc_sheet, ability), ruling["tier"])
    runtime.store_set(config.LAST_CHECK_KEY, check)
    show_to_player(runtime, rules.roll_line(check))
    return check


def next_encounter(runtime, adv, judge_scene=True):
    """Start the next encounter if none is in progress; returns whether one started."""
    if encounters.current(runtime) is not None:
        return False
    if judge_scene:
        # With no encounter open, the focus is the scene goal itself: is the adventure over?
        yield from judge_focus(runtime)
        if goals.active(runtime) is None:
            return False
    plan = yield from call_actor(runtime, "encounter_creator", partial(create_encounter, adv=adv))
    return encounters.start(runtime, adv, plan) is not None


def choose_tone(runtime, adv, reason):
    encounter_id = encounters.current(runtime)
    if encounter_id is None:
        return
    tone = yield from call_actor(runtime, "tone_handler", partial(pick_tone, adv=adv, reason=reason))
    if tone:
        encounters.set_tone(runtime, encounter_id, tone)


# -- what the narrator is told ----------------------------------------------------


def turn_notes(ruling, check):
    """How the player's action turned out, with no numbers."""
    if check is None:
        return ["The player's action needs no roll: narrate its natural result."]
    stakes = ruling["stakes"]
    return [
        f"The player's action is a {config.BAND_TEXT[check['band']]}.",
        f"On success: {stakes.get('success', 'it works as intended')}. "
        f"On failure: {stakes.get('failure', 'it does not work')}.",
    ]


def opening_note(adv):
    pc = adv["roster"][adv["player_character"]]
    location = adv["locations"][adv["start_location"]]
    return config.load_prompt(
        "generator", "opening",
        premise=adv.get("premise", ""), goal=adv["scene_goal"],
        pc=f"{pc['name']}: {pc['description']}", location=f"{location['name']}: {location['description']}",
    )


def ending_note(runtime, adv):
    """The instructions for the closing narration, or None while the adventure goes on."""
    if state.pc_out(runtime, adv):
        outcome = "The player character has fallen, and the adventure ends in defeat."
    elif goals.active(runtime) is None:
        root = goals.get(runtime, goals.tree(runtime)["root"])
        outcome = "The adventure's goal is achieved." if root["status"] == "done" else "The adventure's goal is lost."
    else:
        return None
    return config.load_prompt("generator", "ending", outcome=outcome)


def scene_view_note(runtime, adv):
    """What the player character can perceive, or None when it hasn't changed since last time."""
    sheets, game_state = state.characters(runtime), state.game(runtime)
    location = adv["locations"][game_state["location"]]
    lines = [
        f"Location: {location['name']}. {location['description']}",
        "Exits: " + ", ".join(adv["locations"][exit_id]["name"] for exit_id in location["exits"]),
    ]
    lines += ["Present: " + state.perceived(adv, sheets[char_id]) for char_id in game_state["present"]]
    lines += [f"Known: {fact}" for fact in game_state["revealed"]]
    view = "\n".join(lines)
    if view == runtime.store_get(config.LAST_VIEW_KEY):
        return None
    runtime.store_set(config.LAST_VIEW_KEY, view)
    return view


def focus_template(chain):
    """`goals.instruction_text` template: the goal in focus and the mood. No criteria, no secrets."""
    parts = [f"Working toward: {chain[-1]['text']}."]
    tone = next((goal["data"]["tone"] for goal in reversed(chain) if goal["data"].get("tone")), None)
    if tone:
        parts.append(f"Mood: {tone}.")
    parts.append("Steer the story toward this through the world and its characters, without announcing it.")
    return " ".join(parts)


# -- speaking to the player -------------------------------------------------------


def narrate(runtime, adv, notes):
    """Voice one reply: this turn's notes, what the player can perceive, and the goal in focus."""
    parts = list(notes)
    view = scene_view_note(runtime, adv)
    if view:
        parts.append(view)
    focus = goals.instruction_text(runtime, template=focus_template)
    if focus:
        parts.append(focus)
    runtime.append(format_instructions("\n\n".join(parts)))
    runtime.generate(visible=True)
    runtime.show_reply()


def show_to_player(runtime, text):
    """Show `text` as its own message, without adding it to the narrator's history."""
    runtime.last_visible = ("generator", text)
    runtime.show_reply()
```

Why the order in `play` matters: `take_turn` can close the scene goal (in `next_encounter`) or leave the player character down. So `play` checks for an ending *before* narrating the turn, and narrates the ending instead.

---

## Step 10: the prompts

The prompt files are already written, in `prompts/<actor>/`; read them alongside this step. System prompts are given to their actor unchanged. Task prompts (`_prompt`, `_opening`, `_ending`) are templates filled in by `config.load_prompt`, and each `$name` must match a keyword the flow passes. `string.Template` raises `KeyError` naming any placeholder the flow forgot.

- `generator/generator_system.txt`: the narrator. How to follow the hidden instructions, the style, what to keep secret, and a summary of the rules for out-of-character questions.
- `generator/generator_opening.txt`: `$premise`, `$goal`, `$pc`, `$location`, filled by `opening_note`.
- `generator/generator_ending.txt`: `$outcome`, filled by `ending_note`.
- `adjudicator/adjudicator_system.txt`: in fiction or out of character, when a check is needed, which ability, how to pick the tier, and the ruling's JSON schema.
- `adjudicator/adjudicator_prompt.txt`: `$scene`, `$location`, `$present`, `$message`, filled by `adjudicate`.
- `character_state_handler/character_state_handler_system.txt`: the sheet fields, the change vocabulary, how much each result band should change, and the `{"changes": [...]}` schema.
- `character_state_handler/character_state_handler_prompt.txt`: `$sheets`, `$message`, `$ruling`, `$check`, `$scene`, filled by `update_characters`.
- `game_state_handler/game_state_handler_system.txt`: the game state fields and the change vocabulary, including that movement isn't limited to exits.
- `game_state_handler/game_state_handler_prompt.txt`: `$game`, `$locations`, `$flags`, `$roster`, `$message`, `$ruling`, `$check`, `$scene`, filled by `update_world`.
- `encounter_creator/encounter_creator_system.txt`: what an encounter is, what the narrator sees versus what goes in `secrets`, planning guidance, and the plan's JSON schema.
- `encounter_creator/encounter_creator_prompt.txt`: `$premise`, `$goal`, `$criteria`, `$progress`, `$game`, `$locations`, `$flags`, `$roster`, `$scene`, `$max_steps`, filled by `create_encounter`.
- `tone_handler/tone_handler_system.txt`: the `{"tone": ...}` schema.
- `tone_handler/tone_handler_prompt.txt`: `$encounter`, `$reason`, `$scene`, `$tones`, filled by `pick_tone`.
- `judge/judge_system.txt`: a TTRPG version of `goals.JUDGE_SYSTEM_PROMPT`.

Things that tie the prompts to your code:

- **The JSON schemas live in system prompts**, which is why system prompts aren't templates: their braces never pass through `load_prompt`.
- **The change vocabularies must match `changes.py`.** The keys the state handlers are told about are `CHARACTER_FIELDS` and `GAME_FIELDS`. If you add a kind of change, add it in both places.
- **The tone list comes from `config.TONES`** through `$tones`, so the prompt and `check_tone` can't disagree.
- **The judge's schema must stay exactly as it is**, because `goals.judge` parses the reply itself.

Expect to tune the prompts once you've seen a model play: they're starting points.

**Check your work:** every prompt the code asks for exists.

```bash
python -c "
import config
for actor, key in [('generator','system'),('generator','opening'),('generator','ending'),('judge','system')] + \
        [(a, k) for a in ('adjudicator','character_state_handler','game_state_handler','encounter_creator','tone_handler') for k in ('system','prompt')]:
    print(config.prompt_path(actor, key))"
```

---

## Step 11: `special_commands.py`

**Framework note:** `runtime.register_command(name, handler)` makes `/name args` call `handler(runtime, args)` whenever `ask` is waiting. `ask` then asks again, so a command never counts as a turn. Raising `CommandRestart` restarts the flow, which is what `/load` needs, and `CommandExit` ends it. In the web UI, what a command prints is recorded as a step in the transcript, visible in `dev` view.

The registry and the save, load, list and quit commands follow `.local/inft/special_commands.py`. `/help` prints each handler's docstring instead of `inft`'s hand-written list.

```python
"""Slash commands: /help, /save, /load, /list, /quit, /sheet, /where, /dc."""

from fictive import CommandExit, CommandRestart

import config
import rules
import state

_COMMANDS = {}


def command(name):
    def register(handler):
        _COMMANDS[name] = handler
        return handler
    return register


def register_commands(runtime):
    for name, handler in _COMMANDS.items():
        runtime.register_command(name, handler)


@command("help")
def handle_help(runtime, args):
    """List the commands."""
    for name, handler in sorted(_COMMANDS.items()):
        print(f"  /{name:<6} {handler.__doc__}")


@command("save")
def handle_save(runtime, args):
    """Save the game."""
    print(f"Game saved: {runtime.save_session()}")


def _saved_sessions(runtime):
    """Saved session ids, newest first (ids start with a timestamp)."""
    folder = runtime.interpreter.conversations_root(runtime.main_actor)
    if not folder.exists():
        return []
    return sorted((path.stem for path in folder.glob("*.json")), reverse=True)


@command("list")
def handle_list(runtime, args):
    """List saved games."""
    sessions = _saved_sessions(runtime)
    print("\n".join(f"  {session_id}" for session_id in sessions) or "No saved games.")


@command("load")
def handle_load(runtime, args):
    """Load a saved game: /load [id or start of an id]. The newest by default."""
    prefix = args.strip()
    matches = [session_id for session_id in _saved_sessions(runtime) if session_id.startswith(prefix)]
    if not matches or (prefix and len(matches) > 1 and prefix not in matches):
        print("No saved game matches." if not matches else "Several saved games match; give more of the id.")
        return
    session_id = prefix if prefix in matches else matches[0]
    runtime.load_session(session_id=session_id)
    print(f"Loaded {session_id}")
    raise CommandRestart()


@command("quit")
def handle_quit(runtime, args):
    """End the game."""
    raise CommandExit()


@command("sheet")
def handle_sheet(runtime, args):
    """Show a character sheet: /sheet [id]. Your own by default."""
    adv, sheets = state.load_adventure(), state.characters(runtime)
    sheet = sheets.get(args.strip() or adv["player_character"])
    if sheet is None or not sheet["visible"]:
        print("You don't know.")
        return
    card = state.entry(adv, sheet)
    abilities = ", ".join(f"{name.capitalize()} {value:+d}" for name, value in card["abilities"].items())
    print(f"{card['name']}: {sheet['lp']}/{config.MAX_LP} LP, {sheet['status']}. {abilities}.")
    if sheet["conditions"]:
        print("Conditions: " + ", ".join(sheet["conditions"]))


@command("where")
def handle_where(runtime, args):
    """Show where you are, the exits, and who is here."""
    adv, sheets, game_state = state.load_adventure(), state.characters(runtime), state.game(runtime)
    location = adv["locations"][game_state["location"]]
    print(f"{location['name']}: {location['description']}")
    print("Exits: " + ", ".join(adv["locations"][exit_id]["name"] for exit_id in location["exits"]))
    print("Here: " + ", ".join(f"{state.entry(adv, sheets[i])['name']} ({i})" for i in game_state["present"]))


@command("dc")
def handle_dc(runtime, args):
    """Debug: the last check, with its hidden DC."""
    check = runtime.store_get(config.LAST_CHECK_KEY)
    if not check:
        print("No check yet.")
        return
    print(f"{rules.roll_line(check)} against DC {check['dc']} ({check['tier']}): {check['band']}")
```

---

## Step 12: `fictive_scenario.py`

This is the contract `fictive/web/scenario.py` reads: which actor's replies are the conversation, which actors exist and what type each is, the entry flow, and the slash commands.

```python
"""The contract the web backend reads to run the ttrpg scenario.

Run it with:

    python -m fictive.web --scenario examples/ttrpg --pipeline-type openai --model <model>
"""

from config import ACTOR_TYPES, SCENARIO_DIR
from flows.generator import play
from special_commands import register_commands

NAME = "ttrpg"
MAIN_ACTOR = "generator"
flow = play

__all__ = ["ACTOR_TYPES", "MAIN_ACTOR", "NAME", "SCENARIO_DIR", "flow", "register_commands"]
```

**Check your work:** the backend can load the scenario. Run this from the repository root:

```bash
python -c "from fictive.web.scenario import RuntimeScenarioSpec; s = RuntimeScenarioSpec('examples/ttrpg'); print(s.name, s.actor_names)"
```

---

## Step 13: play it

Every actor but the generator must reply with valid JSON, so the `mock` pipeline can't run this scenario; use a real model. `ui/README.md` explains the web UI's two-process setup, or build the UI once with `npm run build` so one process serves both.

```bash
python -m fictive.web --scenario examples/ttrpg --pipeline-type openai --model <provider/model>
```

Things to try, and what to look for:

- **Opening:** one narration that sets the scene. In `dev` view, you'll see the encounter creator and tone handler running first. The inspector's goals panel shows the scene goal, the first encounter and its steps.
- **An action that needs a check** ("I force the door"): the roll appears as its own message (`Strength: 14 + 1 = 15`), and the narration has no numbers in it. `/dc` shows the hidden DC.
- **An action that needs no check** ("I look around"): no roll message.
- **An out-of-character question** ("how do checks work?"): an answer, with no roll and no state change.
- **Moving by an unusual route** ("I smash through the vault wall"): `ttrpg_game.moves` in the store gains an entry, even though the nave's exits don't list the wall.
- **`/sheet`, `/sheet ferryman`, `/where`:** a hidden sheet answers "You don't know."
- **Rewrite an earlier message:** LP, `moves` and the goal tree roll back to that point, which is the payoff of step 4's copying rules.

If a turn fails, the dev view shows which actor failed and its reply. A handler's rejected change prints `[state] rejected ...` with the reason.

---

## Step 14: update the README

The implementation settles some details the README doesn't cover yet:

- **Turn Order:** an out-of-character message skips steps 3 to 7 and doesn't count as a turn. When no encounter is in progress, the Judge first judges the scene goal itself, which is how the adventure ends. The game also ends when the player character is down or dead.
- **Adventure File:** add the optional `premise` field.
- A short **Files** section pointing to this tutorial's layout, and a **Running** section with the command from step 13.

(`DOCS.md` and `REPOSITORY_DOCS.md` don't need updating: `AGENTS.md` excludes changes under `examples/`.)

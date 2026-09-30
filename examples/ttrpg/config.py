"""Paths, constants and prompt lookup for the ttrpg scenario."""

import string
from pathlib import Path

SCENARIO_ROOT = Path(__file__).resolve().parent
SCENARIO_DIR = SCENARIO_ROOT
PROMPTS_DIR = SCENARIO_ROOT / "prompts"
ADVENTURE_FILE = SCENARIO_ROOT / "adventure.json"
LOCATIONS_FILE = SCENARIO_ROOT / "locations.json"
CHARACTER_SHEETS_FILE = SCENARIO_ROOT / "character_sheets.json"

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

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
    pc = adv["character_sheets"][adv["player_character"]]
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

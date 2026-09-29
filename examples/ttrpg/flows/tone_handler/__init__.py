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

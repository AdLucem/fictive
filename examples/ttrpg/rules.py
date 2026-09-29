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

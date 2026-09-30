# Actors

The seven actors of the `ttrpg` scenario, and what each one sees and returns. See the [README](../README.md) for the turn order they run in.

## Generator

Type: generator (the main actor)

The game master/narrator. It receives instructions describing:

(a) the check result
(b) what changed
(c) what the story is working toward right now: the current step of the encounter in progress (for example, "get the Ferryman to carry Mira across the water")
(d) the mood to narrate in (for example, "eerie"), set by the Tone Handler

And returns a player-facing narration.

The Generator only sees what the player character can perceive. For example, it never sees the DC, the roll, or the character sheets of characters who aren't visible. The roll is shown to the player directly (for example, `Strength: 14 + 3 = 17`). This is to prevent information leakage between the generator and player.

## Adjudicator

Type: router

Decides how the player's message is handled. It returns:
- whether the message is in-fiction or out of character (for example, a rules question)
- whether the action needs a check
- which ability the check uses (**Strength**, **Knowledge** or **Mana**)
- the difficulty tier (Easy, Medium, Hard or Very Hard)
- the stakes: what success and failure would mean

The DC it implies is kept private from the Generator and the player.

The Adjudicator doesn't see any character's ability modifiers.

## Character State Handler

Type: State Handler

Keeps every character sheet in the game: the player character, NPCs and monsters are all tracked the same way. Given what happened and the check result, it proposes changes to the sheets of the characters involved. The changes are taken and character sheets are deterministically updated.

This is a single actor that handles every sheet.

Each character sheet carries a `visible: Bool` flag. A visible sheet can be shown to the player, and the Generator may describe its numbers; a hidden sheet (a monster's, say) cannot. The flag can change during play: for example, a successful **Knowledge** check against a monster can reveal its sheet.

## Game State Handler

Type: State Handler

Keeps the state of the world: where the player character is, what has changed in the world, and which encounter is in progress. Like the Character State Handler, it returns proposed changes, which are deterministically applied to the game state.

The player character isn't limited to a location's exits. They can act according to their abilities: a character with high **Strength** might break through a window, and one with high **Mana** might step through a ward. When an action takes the player character from one location to another, the Game State Handler judges where they end up, and the move is recorded along with how it happened.

## Encounter Creator

Type: planner

When no encounter is in progress, it plans the next one toward the adventure's scene goal: what the encounter is, what resolves it, the steps along the way, and which characters from the character sheets take part. The encounter becomes a sub-goal of the scene goal, and its steps become sub-goals of the encounter.

Anything the player shouldn't know yet (a trap, an NPC's real motive) is kept with the encounter where the Generator can't see it.

## Tone Handler

Type: router

Picks the tone of the scene from a fixed set (for example, tense, eerie, comic or triumphant) and attaches it to the encounter in progress, where the Generator picks it up. It runs when an encounter starts and when a check ends in a complication.

## Judge

Type: judge

Decides whether the encounter step in focus is resolved, so the game can move on to the next step or the next encounter.

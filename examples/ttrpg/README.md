# Tabletop Roleplaying Game (TTRPG)

This is a minimal tabletop roleplaying game implementation. If you're familiar with [Dungeons and Dragons](https://en.wikipedia.org/wiki/Dungeons_%26_Dragons), then you might be familiar with some of the mechanics of this game. Instead of individually programming each rule, we rely on LLMs to interpret rules and update the game state. 

## Game, Rules and Character Sheets

To keep it simple, instead of adapting a full TTRPG ruleset, we will have a very simple character sheet and ruleset.

### Character Sheets

#### Life Points

Each character has a set of Life Points (LP). In this game, all characters start with a total of 20 Life Points.

#### Ability Modifiers

Each character has three ability modifiers:
- **Strength**
- **Knowledge**
- **Mana**

Each ability modifier is assigned a number between +5 and -5. Character sheets are pre-assigned.

### Checks

A character's stats affect what the character can do in the world; a character with high strength, for example, could try to break open a locked door. The game master might ask the player for a **Strength** check- a `check` is done by rolling a `d20`, and then adding the relevant ability modifier to it. The total is compared against the action's `Difficulty Score` (DC), which is decided in private by the game master. An action whose outcome is not in doubt needs no check.

#### Difficulty

The game master judges how hard the proposed action is and picks one of four difficulty tiers. The tier sets the DC:

| Difficulty | DC |
|------------|----|
| Easy       | 8  |
| Medium     | 12 |
| Hard       | 16 |
| Very Hard  | 20 |

#### Results

A check has one of four results, depending on how far the total lands from the DC:

| Result | When | What happens |
|--------|------|--------------|
| **Strong success** | Total beats the DC by 5 or more | The character performs the action and gains something extra. |
| **Success** | Total meets or beats the DC | The character performs the action. |
| **Success at a cost** | Total misses the DC by 1 to 4 | The game master chooses: the character performs the action but pays a price, or fails but gains something. |
| **Failure with a complication** | Total misses the DC by 5 or more | The character attempts the action and fails, and the situation gets worse. |

A natural 20 on the die is always a strong success, and a natural 1 is always a failure with a complication, whatever the total.

## Adventure and Roster

The game is a fixed adventure: one player character pursues a single top-level scene goal (for example, "recover the relic from the flooded crypt"). Encounters are the steps along the way.

Every character in the adventure, including the player character, Non-Player Characters (NPCs) and monsters, has a pre-assigned character sheet. The characters, the map and everything else fixed about the adventure are defined in an adventure file; see [State](#state).

## Actors

The game master's job is split across several actors. Only the Generator speaks to the player; every other actor works behind the scenes and hands its decisions to the Generator.

The maths of it- the life point updates, rolling the `d20`, adding the modifier, comparing against the DC, etc. - is deterministic. The LLM-based actors stand in for the game master's judgement: whether an action needs a check, how hard it is, and what the outcome means in the story.

### Turn Order

Each time the player sends a message:

1. The **Judge** checks whether the current encounter step is resolved.
2. The **Adjudicator** decides whether the message needs a check, and if so, which ability and difficulty tier apply.
3. If there is a check, code rolls it and works out the result.
4. The **Character State Handler** updates the character sheets of everyone the action affected.
5. The **Game State Handler** updates the state of the world.
6. If no encounter is in progress, the **Encounter Creator** starts the next one.
7. If an encounter just started, or the check ended in a complication, the **Tone Handler** sets the tone.
8. The **Generator** narrates what happened.

An out-of-character message (a rules question, say) skips steps 3 to 7: nothing is rolled, no state changes, and it doesn't count as a turn. The Generator answers it out of character.

When no encounter is in progress, the Judge first judges the scene goal itself before the Encounter Creator plans another encounter. That's how the adventure ends: once the scene goal is done or has failed, the Generator narrates the ending instead of the turn. The adventure also ends when the player character is `down` or `dead`.

### Generator

Type: generator (the main actor)

The game master/narrator. It receives instructions describing:

(a) the check result
(b) what changed
(c) what the story is working toward right now: the current step of the encounter in progress (for example, "get the Ferryman to carry Mira across the water")
(d) the mood to narrate in (for example, "eerie"), set by the Tone Handler

And returns a player-facing narration.

The Generator only sees what the player character can perceive. For example, it never sees the DC, the roll, or the character sheets of characters who aren't visible. The roll is shown to the player directly (for example, `Strength: 14 + 3 = 17`). This is to prevent information leakage between the generator and player.

### Adjudicator

Type: router

Decides how the player's message is handled. It returns:
- whether the message is in-fiction or out of character (for example, a rules question)
- whether the action needs a check
- which ability the check uses (**Strength**, **Knowledge** or **Mana**)
- the difficulty tier (Easy, Medium, Hard or Very Hard)
- the stakes: what success and failure would mean

The DC it implies is kept private from the Generator and the player.

The Adjudicator doesn't see any character's ability modifiers.

### Character State Handler

Type: State Handler

Keeps every character sheet in the game: the player character, NPCs and monsters are all tracked the same way. Given what happened and the check result, it proposes changes to the sheets of the characters involved. The changes are taken and character sheets are deterministically updated.

This is a single actor that handles every sheet.

Each character sheet carries a `visible: Bool` flag. A visible sheet can be shown to the player, and the Generator may describe its numbers; a hidden sheet (a monster's, say) cannot. The flag can change during play: for example, a successful **Knowledge** check against a monster can reveal its sheet.

### Game State Handler

Type: State Handler

Keeps the state of the world: where the player character is, what has changed in the world, and which encounter is in progress. Like the Character State Handler, it returns proposed changes, which are deterministically applied to the game state.

The player character isn't limited to a location's exits. They can act according to their abilities: a character with high **Strength** might break through a window, and one with high **Mana** might step through a ward. When an action takes the player character from one location to another, the Game State Handler judges where they end up, and the move is recorded along with how it happened.

### Encounter Creator

Type: planner

When no encounter is in progress, it plans the next one toward the adventure's scene goal: what the encounter is, what resolves it, the steps along the way, and which characters from the roster take part. The encounter becomes a sub-goal of the scene goal, and its steps become sub-goals of the encounter.

Anything the player shouldn't know yet (a trap, an NPC's real motive) is kept with the encounter where the Generator can't see it.

### Tone Handler

Type: router

Picks the tone of the scene from a fixed set (for example, tense, eerie, comic or triumphant) and attaches it to the encounter in progress, where the Generator picks it up. It runs when an encounter starts and when a check ends in a complication.

### Judge

Type: judge

Decides whether the encounter step in focus is resolved, so the game can move on to the next step or the next encounter.

## State

The game has three kinds of state:

- the **adventure file**, written in advance and never changed during play
- the **character sheets** of the characters in play, kept by the Character State Handler
- the **game state**, kept by the Game State Handler

Items and inventory are left out for now.

### Adventure File

The adventure file defines everything fixed about the adventure: the scene goal, the player character, the roster of characters, the locations, and the flags. The example below is shortened; the full adventure is [adventure.json](adventure.json).

```json
{
  "premise": "The Relic of Saint Veyra, a silver reliquary said to calm floodwaters, was lost when the crypt beneath the abbey flooded a century ago.",
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
      "secrets": "He drowned here a century ago and cannot leave the crypt.",
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
    "crypt_entrance": {
      "name": "Crypt Entrance",
      "description": "Worn steps descend into cold, standing water.",
      "exits": ["flooded_nave"]
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
    "ferryman_paid": {"initial": false, "description": "Mira has paid the Ferryman's toll."}
  }
}
```

At the top level:

- `premise` (optional): the background the opening narration and the Encounter Creator start from.
- `scene_goal`: the adventure's single top-level goal, the root of the goal tree.
- `criteria`: what the Judge looks for to decide the scene goal is done.
- `player_character`: the roster id of the player character, whose `kind` must be `pc`.
- `start_location`: the location the player character starts in.

Each **roster entry** has:

- `name`: the character's display name.
- `kind`: `pc`, `npc` or `monster`.
- `unique`: whether the character can be in play only once. A named NPC is unique; a monster type can be brought in several times.
- `abilities`: the three ability modifiers, each between +5 and -5.
- `description`: what the player character can perceive about the character.
- `secrets` (optional): what only the game master knows. The Generator never sees it.
- `visible`: whether the character's sheet starts out visible to the player.

Every character starts with 20 Life Points, so the roster doesn't list them.

**Locations** each have a name, a description, and a list of exits naming the locations they connect to. Exits are the ordinary ways between locations, not the only ones: see [Game State Handler](#game-state-handler).

**Flags** are the facts about the world that can change during play. Each is true or false, with an initial value and a description of what it means. Only flags declared here exist.

### Character Sheets

When a character enters play, a live character sheet is made from its roster entry. A unique character keeps its roster id (`ferryman`); each copy of a non-unique one is numbered (`drowned_dead_1`, `drowned_dead_2`).

```json
{
  "id": "drowned_dead_1",
  "roster_id": "drowned_dead",
  "lp": 14,
  "status": "active",
  "conditions": ["grappling mira"],
  "disposition": "hostile",
  "visible": false,
  "notes": ["Lost an arm to Mira's axe."]
}
```

Fixed for the character's time in play:

- `id`: the character's id in play.
- `roster_id`: the roster entry it was made from. Its name, kind, abilities, description and secrets are read from there.

Changed during play:

- `lp`: Life Points, between 0 and 20.
- `status`: `active`, `down`, `dead` or `fled`.
- `conditions`: short tags for temporary states, such as `soaked` or `grappling mira`.
- `disposition`: `hostile`, `neutral` or `friendly` toward the player character.
- `visible`: whether the player can see this sheet.
- `notes`: a running log of what has happened to the character.

### Game State

```json
{
  "location": "flooded_nave",
  "present": ["mira", "ferryman", "drowned_dead_1"],
  "flags": {"bridge_collapsed": true, "ferryman_paid": false},
  "encounter": "g12",
  "revealed": ["The relic lies in the lower vault."],
  "moves": [
    {"from": "crypt_entrance", "to": "flooded_nave", "via": "Walked down the steps into the water."},
    {"from": "flooded_nave", "to": "lower_vault", "via": "Smashed through the rotten vault door: Strength check, success."}
  ]
}
```

- `location`: the player character's current location.
- `present`: the characters in the scene. Only their sheets are shown to the Character State Handler, and only they can be described by the Generator.
- `flags`: the current value of every declared flag.
- `encounter`: the id of the encounter in progress, in the goal tree. The encounter's progress is kept in the goal tree, not here.
- `revealed`: facts the player has learned.
- `moves`: every move the player character has made: where from, where to, and how.

The Encounter Creator adds characters to `present` when it starts an encounter. The Game State Handler adds and removes them as the story moves: someone flees, or the player character leaves a location without them.

### Changes

Neither state handler rewrites its state. Each returns a list of proposed changes; code checks every change and applies the valid ones. An invalid change is dropped and logged, and the rest still apply.

The Character State Handler returns changes like:

```json
{"changes": [
  {"character": "drowned_dead_1", "lp": -5, "reason": "Mira's axe, strong success"},
  {"character": "mira", "add_condition": "soaked"},
  {"character": "ferryman", "disposition": "friendly"},
  {"character": "drowned_dead_1", "visible": true, "reason": "Knowledge check, success"}
]}
```

and the Game State Handler returns changes like:

```json
{"changes": [
  {"move_to": "lower_vault", "via": "Smashed through the rotten vault door: Strength check, success."},
  {"set_flag": "bridge_collapsed", "value": true},
  {"reveal": "The Ferryman cannot leave the crypt."},
  {"leave": "drowned_dead_1"}
]}
```

Code enforces the rules:

- A change may only target a character in `present`.
- Fields that come from the roster can't be changed.
- Life Points stay between 0 and 20, and a character whose Life Points reach 0 becomes `down`.
- The player character can only move to a location declared in the adventure file, and every move is recorded in `moves`.
- Only declared flags can be set.

Both live states are kept in the interpreter's store as JSON, so saving, rewriting and forking a session carry them along with everything else.

## Files

[TUTORIAL.md](TUTORIAL.md) builds the scenario step by step and explains each file.

- `fictive_scenario.py`: the contract the web backend reads (main actor, actor types, entry flow, slash commands).
- `config.py`: paths, the game's constants, the actor list, and prompt lookup.
- `adventure.json`: the adventure.
- `rules.py`: rolling a check and working out its result.
- `state.py`: loading the adventure file, and the character sheets and game state kept in the store.
- `changes.py`: checking and applying the state handlers' proposed changes, and describing them to the Generator.
- `encounters.py`: encounters and their steps in the goal tree.
- `special_commands.py`: `/help`, `/save`, `/load`, `/list`, `/quit`, `/sheet`, `/where` and `/dc`.
- `flows/<actor>/`: each actor's flows. `flows/generator/` holds `play`, the entry flow; `flows/common.py` holds helpers the sub-actors share.
- `prompts/<actor>/<actor>_<key>.txt`: each actor's system prompt and task prompt templates.

## Running

Every actor but the Generator must reply in JSON, so the `mock` pipeline can't run this scenario; use a real model. From the repository root:

```bash
python -m fictive.web --scenario examples/ttrpg --pipeline-type openai --model <provider/model>
```

See `ui/README.md` for running the web UI alongside it.

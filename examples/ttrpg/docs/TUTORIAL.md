# Actors and flows: a tutorial built on the `ttrpg` scenario

A `fictive` program is made of two things: **actors**, the LLM participants, and **flows**, the Python functions you write to direct them. This tutorial explains both, then shows how the tabletop roleplaying game in this folder is built from them.

- **[Part 1](#part-1-actors-and-flows)** explains actors and flows, and ends with a two-actor toy you can run without a model.
- **[Part 2](#part-2-the-flows-of-the-ttrpg-scenario)** walks through every flow in the `ttrpg` scenario: which actor it runs as, what it gives that actor, and what it does with the answer.
- **[Part 3](#part-3-the-game-code-the-flows-call)** covers the plain-Python game code the flows call: dice, state and rule checks. No actor speaks in it, so it gets a lighter touch.
- **[Part 4](#part-4-run-it)** runs the scenario and shows where to watch the actors and flows at work.

You need the repository installed (`pip install -e .` from the repository root). If you haven't read [README.md](../README.md), read it first: it describes the game this scenario implements. Commands run from `examples/ttrpg/` unless a step says otherwise.

---

## Part 1: Actors and flows

Two words carry this whole tutorial:

- An **actor** is one LLM participant: a model with its own system prompt and its own conversation history.
- A **flow** is an ordinary Python function you write that directs actors. A **flow** works within a particular `runtime`. It sets an actor's system prompt, adds messages to its history, tells it to reply, and decides what to do with the reply.

Actors never act on their own: everything an actor does is a line in some flow.

### Actors

An **actor** is one LLM participant. Each actor, an instance of `fictive.Actor`, has:

- a **name**, such as `"adjudicator"`;
- a **system prompt**, which tells it what it is and how to answer;
- a **history**: its own conversation so far, as a list of `system`, `user` and `assistant` turns. The history is everything the model sees when the actor speaks, and it is private: no other actor can read it unless a flow copies text across;
- a **model** (its *pipeline*), which writes the actor's next `assistant` turn when asked.

An actor does nothing on its own. It speaks only when a flow tells it to, and it knows only what a flow has put in its history.

The `ttrpg` scenario splits the game master's job across seven actors. Each answers one question and sees only what it needs for that question:

- **`generator`**: what does the player hear? It replies with narration, the only text the player reads.
- **`judge`**: is the goal in focus done? It replies `{"status": "done"}`, `"failed"` or `"continue"`.
- **`adjudicator`**: is the message in character, and does it need a roll? It replies with a ruling, as JSON.
- **`character_state_handler`**: how did that change anyone's character sheet? It replies with proposed sheet changes, as JSON.
- **`game_state_handler`**: how did that change the world? It replies with proposed world changes, as JSON.
- **`encounter_creator`**: what happens next? It replies with an encounter plan, as JSON.
- **`tone_handler`**: what should this feel like? It replies with a tone, such as `{"tone": "eerie"}`.

The actors are declared in `config.py`:

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

The web backend builds one actor for each name. `None` builds a plain `Actor`. `"generator"` builds fictive's `Generator`, an actor type with a **scene**: `get_scene()` returns its whole conversation with the hidden instruction turns left out, which is the story so far as the player saw it. The other actors read the scene to know what has happened.

### The runtime and the working actor

A flow never handles an actor object directly. Every flow receives one object, the **runtime** (`fictive.Runtime`), as its first argument, and issues commands through it. Each command acts on the runtime's **working actor**: the actor that has control right now. At the start, the working actor is the **main actor**, which is `generator` in this scenario.

These are the commands this scenario uses:

- **`runtime.system(prompt)`** sets the working actor's system prompt. `prompt` is text, or a `Path` to a prompt file.
- **`runtime.refresh()`** clears the working actor's history, keeping only its system prompt.
- **`runtime.append(text)`** adds `text` to the working actor's history as a `user` turn.
- **`runtime.generate(visible=False)`** asks the working actor's model for its next `assistant` turn, and adds the reply to its history. `visible=True` marks the reply as one the player should see.
- **`runtime.raw_latest_text()`** returns the working actor's latest reply, as a string.
- **`runtime.show_reply()`** shows the player the last reply generated with `visible=True`.
- **`runtime.actor(name)`** returns any actor by name, whoever is working.
- **`runtime.store_get(key)`** and **`runtime.store_set(key, value)`** read and write the **store**: a key-value memory shared by every flow and saved with the session. It belongs to no actor.

### Flows

A **flow** is a Python function that takes the runtime as its first argument and issues commands. Flows are where the behaviour lives: which actor speaks, in what order, with what in its history, and what happens to its answer.

Here, roughly, is the Tone Handler's flow with its helpers written out, so every command shows:

```python
def pick_tone(runtime, adv, reason):
    runtime.refresh()                                                   # forget the last call
    runtime.system(config.prompt_path("tone_handler", "system"))        # what it is, how to answer
    runtime.append(config.load_prompt("tone_handler", "prompt", ...))   # this call's task
    runtime.generate()                                                  # its model replies
    return check_tone(json.loads(runtime.raw_latest_text()))            # code checks the reply
```

Nothing in `pick_tone` names an actor: it acts on whichever actor is working when it runs. The flow that calls it decides that it runs as `tone_handler`, as [Calling another actor](#calling-another-actor-call_actor) shows.

A flow can be an ordinary function, like `pick_tone`, or a **generator function**: a function with `yield` or `yield from` in it. Only a generator flow can pause, and pausing is how a flow waits for the player.

### Pausing for the player: `ask`

`ask` pauses a flow until the player sends a message:

```python
message = yield from ask(runtime, "you> ", store=config.LAST_MESSAGE_KEY)
```

Here is what happens at that line:

1. `ask` hands a request for input (an `InputRequest`) to whatever is running the flow: the web backend, or `drive_flow` in a terminal. The flow stops.
2. The host waits for the player, then sends their message back into the flow.
3. `ask` records the message as a `user` turn in the working actor's history, and in the store under the `store=` key if one is given. It then returns the message, and the flow carries on from the same line.

A message that starts with `/` runs a slash command instead, and `ask` waits again.

**A note on Python generators.** Calling a function that has `yield` in it doesn't run the function. It returns a *generator*, which runs a piece at a time: up to each `yield`, and on again when something is sent back in. `yield from other()` runs another generator inside this one and passes its pauses on. That gives one rule to remember: **a function that uses `yield from` is itself a generator, and whoever calls it must use `yield from` too.** That's how a pause deep inside a helper travels all the way up to the host. It's also why so many functions in this scenario use `yield from`, though only one of them calls `ask`: `call_actor`, below, is a generator, so every flow that calls an actor is one too.

### Calling another actor: `call_actor`

`call_actor` runs a flow *as another actor*:

```python
ruling = yield from call_actor(runtime, "adjudicator", partial(adjudicate, adv=adv))
```

It does four things:

1. It makes `adjudicator` the working actor, by pushing it onto the interpreter's callstack above `generator`.
2. It runs the flow, `adjudicate(runtime, adv=adv)`. Every command in it now acts on the Adjudicator: its system prompt, its history, its model.
3. It makes the caller, `generator`, the working actor again, however the flow ended.
4. It returns what the flow returned.

`call_actor` passes the flow only the runtime, so bind any other arguments first with `functools.partial`.

There's one trap: **if the flow returns `None`, `call_actor` returns the actor's latest text instead.** So every flow this scenario calls through `call_actor` returns something other than `None`, even when it has nothing to report: `[]` for no changes, `""` for no tone.

`call_actor` is itself a generator, because the flow it runs might pause to `ask` the player. So it's always written `yield from call_actor(...)`.

#### Helper flows and actor calls

A flow can also run another flow *without* switching actors. The helper then runs as the same working actor. The Generator's entry flow is split up this way: `take_turn`, `next_encounter` and `narrate` are helpers that all run as the Generator.

- **`yield from take_turn(runtime, ...)`** runs `take_turn` as the same actor. Use it to split a long flow into parts.
- **`narrate(runtime, ...)`** also runs as the same actor. Call a helper this way, without `yield from`, when it never pauses and never calls an actor.
- **`yield from call_actor(runtime, "adjudicator", flow)`** runs `flow` as `adjudicator`. Use it to give another actor a turn.

### How information moves between actors

Each actor's history is private, so flows carry information from one actor to another. This scenario uses four channels:

1. **Prompts.** A flow reads what an actor needs and writes it into that actor's history, usually by filling in a prompt template and appending it. This is also how an actor is kept from knowing something: the Adjudicator never learns anyone's ability modifiers because its flow never writes them into its history.
2. **Return values.** What a called flow returns comes back from `call_actor`. The Adjudicator's ruling reaches the Generator's flow this way.
3. **The store.** What one flow writes with `store_set`, any flow can read with `store_get`. The game state lives here, so every actor's flow can read it, and saving a session saves it.
4. **The scene.** `runtime.actor("generator").get_scene()` returns the story so far. Every other actor's prompt includes the end of it, so they all know what has happened.

The other actors keep nothing between calls: each of their flows starts with `runtime.refresh()`. Everything they need arrives through these four channels.

### The entry flow and the host

Every scenario has one **entry flow**, which runs as the main actor from the start of a session. Here, the entry flow is `play`, and `fictive_scenario.py` names both:

```python
MAIN_ACTOR = "generator"
flow = play
```

The **host** runs the entry flow. In a terminal, `drive_flow(play(runtime))` stops at each `ask` until someone types an answer. The web backend (`fictive/web/`) instead runs the flow up to its first `ask` and answers the web request. It keeps the paused flow until the player's next message arrives, then sends the message in and runs the flow to its next `ask`.

A paused flow can't be saved. So when you resume a saved session, or rewrite or fork a message in the web UI, the backend restores every actor's history and the store, then starts the entry flow again from the top, with `RESUMED_STORE_KEY` set in the store. That's why `play` skips its one-time setup when the key is set.

### Try it: two actors, three flows

This toy is a `ttrpg` turn in miniature: a narrator, the main actor, and an adjudicator. A `Scripted` class stands in for the models, so it runs offline. Save it anywhere as `toy.py` and run `python toy.py`:

```python
"""Two actors and three flows: the ttrpg's turn, in miniature."""

import tempfile
from functools import partial

from fictive import Actor, ActorConfig, Interpreter, Runtime, ask, call_actor, drive_flow


class Scripted:
    """A stand-in for a model: each call returns the next canned reply."""

    def __init__(self, *replies):
        self.replies = list(replies)

    def generate(self, messages):
        return {"role": "assistant", "content": self.replies.pop(0)}


# -- flows ---------------------------------------------------------------


def adjudicate(runtime, message):
    """The adjudicator's flow: one question in, one answer out."""
    runtime.refresh()
    runtime.system("Decide whether the player's action needs a dice roll. Reply yes or no.")
    runtime.append(f"The player says: {message}")
    runtime.generate()
    return runtime.raw_latest_text().strip() == "yes"


def take_turn(runtime, message):
    """A helper flow. It runs as whichever actor is working: here, the narrator."""
    needs_roll = yield from call_actor(runtime, "adjudicator", partial(adjudicate, message=message))
    return "The action needs a roll." if needs_roll else "The action needs no roll."


def play(runtime):
    """The entry flow. It runs as the narrator, the main actor."""
    runtime.system("You are the narrator of a tabletop game.")
    while True:
        message = yield from ask(runtime, "you>", store="last_message")
        if message == "quit":
            return
        note = yield from take_turn(runtime, message)
        runtime.append(note)
        runtime.generate(visible=True)
        runtime.show_reply()


# -- running it ------------------------------------------------------------

storage = tempfile.mkdtemp()
narrator = Actor(ActorConfig(name="narrator", storage_dir=storage,
                             pipeline=Scripted("The door groans and gives way.", "Cold water laps at the steps.")))
adjudicator = Actor(ActorConfig(name="adjudicator", storage_dir=storage, pipeline=Scripted("yes", "no")))
runtime = Runtime(Interpreter([narrator, adjudicator], main_actor_name="narrator"), start_actor_name="narrator")

player = iter(["I force the door", "I look around", "quit"])
drive_flow(play(runtime), input_fn=lambda request: next(player))

for name in ("narrator", "adjudicator"):
    actor = runtime.actor(name)
    print(f"\n{name}  (system prompt: {actor.system_prompt['content']})")
    for turn in actor.history.read(merged=False):
        if turn["role"] != "system":
            print(f"  {turn['role']:>9}: {turn['content']}")
```

It prints:

```
The door groans and gives way.
Cold water laps at the steps.
Flow finished.

narrator  (system prompt: You are the narrator of a tabletop game.)
       user: I force the door
       user: The action needs a roll.
  assistant: The door groans and gives way.
       user: I look around
       user: The action needs no roll.
  assistant: Cold water laps at the steps.
       user: quit

adjudicator  (system prompt: Decide whether the player's action needs a dice roll. Reply yes or no.)
       user: The player says: I look around
  assistant: no
```

What to notice:

- **Three flows, two actors.** `play` and `take_turn` run as the narrator. `adjudicate` runs as the adjudicator, because `take_turn` calls it through `call_actor`.
- **`take_turn` is a helper.** `play` calls it with a plain `yield from`, so it runs as the narrator. It's a generator only because it calls `call_actor`.
- **Each history is private.** The narrator's history holds the conversation: the player's messages, recorded by `ask`; the notes `play` appended; and its own replies. The adjudicator's "yes" and "no" never appear in it. The adjudicator's history holds only its last call, because `adjudicate` starts with `refresh()`.
- **The answer crosses by return value.** `adjudicate` returns `True` or `False`, `call_actor` hands it to `take_turn`, and `take_turn` turns it into a note for the narrator.

The `ttrpg` scenario is this toy with more actors, real models, and a game behind them.

---

## Part 2: The flows of the `ttrpg` scenario

Each actor's flows live in `flows/<actor>/__init__.py`, so a flow sits in the package of the actor it runs as. (Should a flow grow past about 30 lines, give it a file of its own in that package, such as `flows/generator/play.py`, and don't import it from the package's `__init__.py`: it imports helpers from there, so the imports would be circular.) Imports are flat, as in `import config`, because the web backend puts the scenario's folder on `sys.path` before importing it.

### The map

This is every flow, and every actor call, in a game:

```
play                                     the entry flow, running as generator
├─ begin                                 first session only
│  ├─ next_encounter
│  │  └─ ⇒ encounter_creator             create_encounter
│  ├─ choose_tone                        if an encounter started
│  │  └─ ⇒ tone_handler                  pick_tone
│  └─ narrate                            the opening
└─ each player message: ask, then
   ├─ take_turn
   │  ├─ judge_focus
   │  │  └─ ⇒ judge                      goals.judge's own flow
   │  ├─ ⇒ adjudicator                   adjudicate
   │  ├─ roll                            if the action needs a roll
   │  ├─ ⇒ character_state_handler       update_characters
   │  ├─ ⇒ game_state_handler            update_world
   │  ├─ next_encounter                  if no encounter is in progress
   │  │  ├─ judge_focus
   │  │  │  └─ ⇒ judge
   │  │  └─ ⇒ encounter_creator          create_encounter
   │  └─ choose_tone                     if an encounter started, or on a complication
   │     └─ ⇒ tone_handler               pick_tone
   └─ narrate                            the turn, or the ending
```

`⇒ actor` is a `call_actor`: the flow named on the right runs as that actor. Every other name is a flow or plain function running as the Generator.

The rest of this part goes from the bottom of the map up: first the pattern every sub-actor flow follows, then each sub-actor, then the Generator's flows that call them.

### The pattern of a sub-actor flow: `flows/common.py`

Every sub-actor flow does the same five things: forget the last call, set the system prompt, give this call's task, generate, and check the answer. `flows/__init__.py` is an empty file, and `flows/common.py` holds the shared parts:

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

- `start_actor` is the first three steps. `refresh` and `system` leave the actor with a clean history holding just its system prompt, and `append` adds this call's task: the template `prompts/<actor>/<actor>_prompt.txt`, with its `$placeholders` filled in.
- `generate_json` is the last two. It generates, parses the reply as JSON, and passes it to `validate`, a function each flow supplies that checks the fields and returns the value the flow should return. If parsing or checking fails, `runtime.actor().history.remove()` deletes the bad reply from the working actor's history, so the retry sees exactly what the first attempt saw. `goals.parse_json_object` accepts code fences and stray prose around the object.
- `scene_tail` is the scene channel: the end of the Generator's scene, read with `runtime.actor("generator")` while another actor is working.
- `describe_check` is the roll as the game-master actors see it, DC included. The player and the narrator never see the DC.

### The Tone Handler

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

This is the pattern with nothing added. `pick_tone` is an ordinary function: it never pauses and never calls an actor. The Generator's flow calls it through `call_actor`, so it runs as `tone_handler`. Its caller also supplies the `reason` it's being asked. When no reply passes, it returns `""` rather than `None`, which `call_actor` would replace with the actor's latest text.

### The Adjudicator

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

The Adjudicator is given the scene, the location, who is present, and the player's message, which its flow reads from the store, where `ask` put it. It isn't given anyone's ability modifiers. The README says it mustn't see them, and the flow is what guarantees that: it never writes them into the Adjudicator's history.

The ruling goes back to the Generator's flow as `call_actor`'s return value. If the Adjudicator never gives valid JSON, `generate_json` raises and the turn ends with an error, because without a ruling the turn can't go on. In the web UI, rewriting the message is the way out.

### The state handlers: propose, and let code apply

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

```python
"""The Game State Handler: proposes changes to the world."""

import state
from flows.common import as_json, check_changes, describe_check, generate_json, scene_tail, start_actor


def update_world(runtime, adv, turn):
    """Returns the proposed game changes; code checks and applies them."""
    character_sheets = {
        sheet_id: {"name": entry["name"], "kind": entry["kind"], "unique": entry["unique"]}
        for sheet_id, entry in adv["character_sheets"].items()
    }
    start_actor(
        runtime, "game_state_handler",
        game=as_json(state.game(runtime)),
        locations=as_json(adv["locations"]),
        flags=as_json(adv["flags"]),
        character_sheets=as_json(character_sheets),
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

`turn` is a dict the Generator's flow builds: the player's message, the ruling and the roll. Both flows return *proposed* changes and never touch the store themselves. The Generator's flow hands the proposals to `changes.py`, plain code that checks each change against the rules and applies the valid ones ([Part 3](#changespy-code-checks-what-actors-propose)). That's the scenario's main division of labour: **actors make judgements; code does the arithmetic and enforces the rules.**

A handler that fails returns `[]`, so the turn goes on without its changes.

### The Encounter Creator

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
        character_sheets=as_json(character_sheets_view(adv, state.characters(runtime))),
        scene=scene_tail(runtime),
        max_steps=config.MAX_ENCOUNTER_STEPS,
    )
    return generate_json(runtime, lambda plan: check_plan(adv, plan))


def character_sheets_view(adv, sheets):
    """Every character sheet but the player character's, marked with whether one is already in play."""
    in_play = {sheet["sheet_id"] for sheet in sheets.values()}
    return {
        sheet_id: {**entry, "in_play": sheet_id in in_play}
        for sheet_id, entry in adv["character_sheets"].items()
        if sheet_id != adv["player_character"]
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
    for sheet_id in plan["characters"]:
        if sheet_id not in adv["character_sheets"] or sheet_id == adv["player_character"]:
            raise ValueError(f"{sheet_id!r} is not a character sheet other than the player character's")
    return plan
```

The plan goes back to the Generator's flow, which adds it to the goal tree with `encounters.start` ([Part 3](#encounterspy-encounters-in-the-goal-tree)). `check_plan` makes sure the plan names only characters that exist, and fills in a turn budget where a step has none.

### The Judge: a flow that `fictive` provides

```python
"""The Judge: closes the goal in focus when the story shows it done or impossible."""

from fictive import goals

import config


def judge_focus(runtime):
    return (yield from goals.judge(runtime, "judge", system=config.prompt_path("judge", "system")))
```

`goals.judge`, in `fictive/goals.py`, is a generator flow that ships with `fictive`. It writes the Judge's task from the goal tree and the scene, runs the Judge with `call_actor`, and applies the verdict to the goal tree. Inside, it follows the same pattern as `flows/common.py`: refresh, system prompt, task, generate, retry.

Because `goals.judge` calls the actor itself, the Generator's flow uses `judge_focus` directly, as `yield from judge_focus(runtime)`. Wrapping it in another `call_actor` would call the Judge from inside itself.

### The Generator: `flows/generator/__init__.py`

The Generator is the main actor, and its flows are the ones that call all the others. The file is long, so here it is in parts. In order, the parts make up the whole file.

#### Imports

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
```

#### The entry flow: `play` and `begin`

```python
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
```

- `play` is a generator flow that pauses at `ask` on every pass of its loop. `ask` records the player's message in the Generator's history, where the narrator reads it, and in the store, where the Adjudicator's flow reads it.
- `begin` is the one-time setup, which `play` skips when resuming ([The entry flow and the host](#the-entry-flow-and-the-host)). It sets the Generator's system prompt, writes the starting state to the store, starts the goal tree, plans the first encounter, and narrates the opening.
- `play` checks for an ending after the turn and before narrating, because a turn can end the adventure. If it has ended, `play` narrates the ending instead of the turn.

#### One turn: `take_turn`

```python
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
```

This is the README's turn order, written as a flow. Read it for which actor is working at each line:

- `judge_focus` and each `call_actor` give another actor a turn and bring back its answer. On the next line, the Generator is the working actor again.
- Everything else is plain code running as the Generator: `goals.tick` counts the turn, `roll` rolls the dice, and `changes.apply_character_changes` and `apply_game_changes` apply the handlers' proposals to the store.
- An out-of-character message returns early, before anything is counted, rolled or changed.

`take_turn` doesn't narrate. It returns *notes*, sentences for the narrator, and `play` decides what gets narrated.

#### Helpers that call actors

```python
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
```

`next_encounter` and `choose_tone` are helpers: they run as the Generator and call other actors. They also show a flow deciding *whether* to call an actor. The Encounter Creator runs only when no encounter is in progress, and only after the Judge has ruled on the scene goal: if the Judge closes it, the adventure is over and there's nothing to plan. `roll` is plain code, and `show_to_player` is covered below.

#### What the narrator is told

```python
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
```

These are plain functions that write text for the narrator: how the action turned out, the opening and ending tasks, what the player character can perceive, and the goal in focus. Between them they decide what the Generator knows. They give numbers only for visible character sheets, and they use a goal's text and tone but never its criteria or secrets. Keeping secrets from the narrator works the same way as keeping modifiers from the Adjudicator: the flow never writes them into its history.

#### Speaking to the player

```python
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

`narrate` is the only place the Generator generates:

1. It appends one `user` turn wrapped by `format_instructions`, as `(INSTRUCTIONS: ...)`. The model reads it like any other turn, but `get_scene()` and the web transcript leave it out, so the player never sees it and neither do the other actors, who read the scene.
2. `generate(visible=True)` adds the narration to the Generator's history and marks it as the reply the player should see.
3. `show_reply()` shows it.

`show_to_player` shows the player text the Generator never generated: the roll line. It sets `runtime.last_visible` by hand, so the roll reaches the player as a message of its own but never enters the Generator's history, where the narrator would see the numbers.

### Wiring it up: `fictive_scenario.py`

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

The web backend imports this module (`fictive/web/scenario.py`) and reads four names from it:

- `ACTOR_TYPES`: which actors to build, and of which type.
- `MAIN_ACTOR`: the actor the entry flow runs as, whose visible replies are the conversation.
- `flow`: the entry flow.
- `register_commands`: adds the slash commands.

### Slash commands run inside `ask`

`special_commands.py` registers each command with `runtime.register_command(name, handler)`:

```python
_COMMANDS = {}


def command(name):
    def register(handler):
        _COMMANDS[name] = handler
        return handler
    return register


def register_commands(runtime):
    for name, handler in _COMMANDS.items():
        runtime.register_command(name, handler)
```

While `ask` is waiting, a message such as `/sheet ferryman` runs `handler(runtime, "ferryman")`, and `ask` waits again, so a command never counts as a turn. A handler is plain code, not a flow. Most read the store:

```python
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
```

`/load` loads a saved session and raises `CommandRestart`, which starts the entry flow again on the loaded session. `/quit` raises `CommandExit`, which ends the flow.

---

## Part 3: The game code the flows call

The rest of the scenario is ordinary Python. No actor speaks in it and no flow runs in it; the flows call into it. Read each file alongside this part: the notes here cover only what the flows rely on.

### `config.py`: prompts, constants and the actor list

- `prompt_path(actor, key)` finds a prompt from its actor and an optional key: actor `generator` with key `system` is `prompts/generator/generator_system.txt` (or `.md`). A prompt never gets a variable name of its own.
- `load_prompt(actor, key, **fields)` reads a prompt and fills in its `$name` placeholders. It uses `string.Template` rather than `str.format`, because the prompts contain JSON examples full of `{` and `}`. A placeholder the flow forgot raises `KeyError` naming it.
- The rest is the game's constants (`ABILITIES`, `DC_BY_TIER`, `TONES` and so on), the store keys, and `ACTOR_TYPES`.

Prompts reach an actor in two ways, and it matters which. A system prompt is passed to `runtime.system(...)` as a `Path`, and the interpreter reads the file. A filled-in template is a string, and goes through `runtime.append(text)`. Don't pass a template to `runtime.generate(prompt=...)`: that treats a string as a file path or a `var:` store lookup.

### The adventure files

`adventure.json`, `character_sheets.json` and `locations.json` hold the adventure; the README's "State" section describes every field. `state.load_adventure()` reads all three into one dict, `adv`, which the flows pass around.

### `rules.py`: the dice

`roll_check(ability, modifier, tier)` rolls a d20, adds the modifier, and compares the total with the tier's DC to find the result band. `roll_line(check)` is the roll as the player sees it, such as `Strength: 14 + 3 = 17`.

### `state.py`: the game state, in the store

The live character sheets and the game state are kept in the store, under `ttrpg_characters` and `ttrpg_game`. That's what lets every actor's flow read them, and what makes saving, loading, rewriting and forking carry the game along.

The flows use `characters` and `save_characters`, `game` and `save_game`, `init_state` (the starting state), `spawn` (bring a character into play), `entry` (the character sheet a live sheet was made from), `full_sheet` (everything, secrets included, for game-master actors), `perceived` (what the player character can see of someone, for the narrator), `modifier`, and `pc_out`.

One trap: the web backend's rewrite and fork checkpoints copy the store only one level deep. If a flow edited a dict from the store in place, it would edit the checkpoint's copy too, and a rewrite would keep the discarded turn's changes. So `state.py` deep-copies on every read and stores a fresh copy on every write (`_read` and `_write`), as `fictive/goals.py` does for the goal tree.

### `changes.py`: code checks what actors propose

`apply_character_changes` and `apply_game_changes` take the state handlers' proposals, check each one against the README's rules ("Changes"), apply the valid ones to the store, and print and drop the rest. `describe` turns the applied changes into sentences the narrator is allowed to see. The fields a change may set (`CHARACTER_FIELDS` and `GAME_FIELDS`) must match what the state handlers' system prompts describe.

### `encounters.py`: encounters in the goal tree

Encounters live in `fictive`'s goal tree (`fictive/goals.py`), which is also kept in the store. The adventure's scene goal is the root, each encounter is a child of the root, and each encounter step is a child of its encounter. The deepest open goal is the **focus**: it's what `judge_focus` rules on, and what `narrate` tells the narrator to work toward. When a step runs out of turns, `goals.tick` fails it, which moves the story on.

- `start` adds the Encounter Creator's plan to the tree and brings its characters into play. The plan's secrets go in the encounter's `data`, which the narrator's instructions never include.
- `current` returns the encounter in progress, or `None`.
- `set_tone` records the Tone Handler's answer on the encounter, where `focus_template` picks it up.

### The prompts

The prompt files are in `prompts/<actor>/`. A system prompt is given to its actor as it is. A task prompt is a template that a flow fills in, and each `$name` in it must match a keyword the flow passes:

- **`generator/generator_opening.txt`**, filled in by `opening_note`: `$premise`, `$goal`, `$pc`, `$location`.
- **`generator/generator_ending.txt`**, filled in by `ending_note`: `$outcome`.
- **`adjudicator/adjudicator_prompt.txt`**, filled in by `adjudicate`: `$scene`, `$location`, `$present`, `$message`.
- **`character_state_handler/character_state_handler_prompt.txt`**, filled in by `update_characters`: `$sheets`, `$message`, `$ruling`, `$check`, `$scene`.
- **`game_state_handler/game_state_handler_prompt.txt`**, filled in by `update_world`: `$game`, `$locations`, `$flags`, `$character_sheets`, `$message`, `$ruling`, `$check`, `$scene`.
- **`encounter_creator/encounter_creator_prompt.txt`**, filled in by `create_encounter`: `$premise`, `$goal`, `$criteria`, `$progress`, `$game`, `$locations`, `$flags`, `$character_sheets`, `$scene`, `$max_steps`.
- **`tone_handler/tone_handler_prompt.txt`**, filled in by `pick_tone`: `$encounter`, `$reason`, `$scene`, `$tones`.

The JSON schemas each actor must reply with are in the system prompts, which is why system prompts aren't templates: their braces never pass through `load_prompt`. `judge/judge_system.txt` is a TTRPG version of `goals.JUDGE_SYSTEM_PROMPT`, and its reply format must stay as it is, because `goals.judge` parses the reply itself. Expect to tune the prompts once you've watched a model play.

---

## Part 4: Run it

Check that every prompt the flows ask for exists (from `examples/ttrpg/`):

```bash
python -c "
import config
for actor, key in [('generator','system'),('generator','opening'),('generator','ending'),('judge','system')] + \
        [(a, k) for a in ('adjudicator','character_state_handler','game_state_handler','encounter_creator','tone_handler') for k in ('system','prompt')]:
    print(config.prompt_path(actor, key))"
```

Check that the web backend can load the scenario (from the repository root):

```bash
python -c "from fictive.web.scenario import RuntimeScenarioSpec; s = RuntimeScenarioSpec('examples/ttrpg'); print(s.name, s.actor_names)"
```

Every actor but the Generator must reply in JSON, so the `mock` pipeline can't play this scenario; use a real model. [`ui/README.md`](../../../ui/README.md) explains the web UI's setup. From the repository root:

```bash
python -m fictive.web --scenario examples/ttrpg --pipeline-type openai --model <provider/model>
```

### Watching the actors and flows

The web UI shows the structure from Part 2 as it runs:

- **`dev` view** draws every `call_actor` as an expandable bar inside the Generator's turn, nested the way the map is. Open one to see what that actor was given and what it replied.
- **The actor picker**, in the top bar, swaps the transcript for any one actor's whole history. Compare the Generator's, which is the story plus its hidden instructions, with the Adjudicator's, which holds only its last call.
- **`live` view** shows only what the player sees: the replies `show_reply` showed, and the roll lines.

Things to try:

- **The opening:** one narration. In `dev` view, the Encounter Creator and the Tone Handler run first, and the inspector's goals panel shows the scene goal, the first encounter and its steps.
- **An action that needs a roll** ("I force the door"): the roll appears as its own message, such as `Strength: 14 + 1 = 15`, and the narration has no numbers in it. `/dc` shows the hidden DC.
- **An action that needs no roll** ("I look around"): no roll message, and the Adjudicator's ruling has `"check": false`.
- **An out-of-character question** ("how do checks work?"): an answer out of character. Only the Judge and the Adjudicator run before the Generator answers: nothing is rolled or changed.
- **Moving by an unusual route** ("I smash through the wall"): the Game State Handler's bar proposes a `move_to`, and `ttrpg_game.moves` in the store gains an entry.
- **`/sheet`, `/sheet ferryman`, `/where`:** a hidden sheet answers "You don't know."
- **Rewriting an earlier message:** Life Points, moves and the goal tree roll back to that point, because they all live in the store.

If a turn fails, `dev` view shows which actor failed and what it replied. A rejected change prints `[state] rejected ...` with the reason.

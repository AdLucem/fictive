# fictive

A library for programming LLM chains-of-thought and agentic harnesses, right here in Python. `fictive` also exports a small domain-specific language for structuring interactions between LLMs as a program. 

Fictive defines LLM interactions in terms of `Actors`- LLM instances with their own context and their own conversational history- and `flows`- behaviour paths for each actor, defined as python code.

The `fictive` language defines commands for `Actor` behaviour. Examples of behaviour commands are:

- `generate` : generate a response from the `Actor`, based on current conversational history and an optional prompt
- `rag-generate` : Retrieves passages from relevant past conversations and generates the actor's next message from them
- `run-actor` : run another `Actor` and return the actor's output to the current `Actor`

## Actors

An actor is one LLM participant in a scene. It is an instance of the class `Actor` (`fictive/actors.py`), built from an `ActorConfig`, and owns:

- a string **name**
- a **system prompt** and a **conversation history**, private to that actor, detailing the actor's own conversational line through the scene
- an **pipeline**, the model backend that answers its `generate` commands (defined in `llm-utils` pipeline). An actor that only runs `agent` commands needs no pipeline;


## Flows

A flow is a series of commands- either blocks of python code, or `fictive` language commands- that define the behaviour path of an actor.

We code a flow as a python function `def my_flow(runtime):`. Every method on `runtime` is one command against the actor that currently holds control.

`fictive` commands execute within the fictive `Interpreter` class ([`fictive/interpreter.py`](fictive/interpreter.py)). The `Interpreter` allows us to use programming language abstractions like callstacks, conditionals, loops etc. to define interactions between Actors. Some example commands:

- `runtime.refresh()` clears the actor's history except its system prompt; flows call it first so each run starts clean.
- `runtime.system(PATH)` sets the system prompt. `runtime.input_from_file(PATH)` appends a prompt file as a user turn, `runtime.input_from_store(key)` appends a store value, and `runtime.store_set(key, value)` writes one.
- `runtime.generate(prompt=None, visible=False)` runs the model, `runtime.show_latest()` prints the result, and `runtime.raw_latest_text()` returns it as a string.
- `runtime.actor("generator").get_scene()` returns the scene so far, which only the generator holds.
- Prompt paths are module-level `Path` constants built from `SCENARIO_ROOT`.

### Example Flow

A small flow using the library runtime. We use python's own `while`/`if` for loops and conditionals. `ask` suspends the flow for human input, and `call_actor` runs through the called actor's control flow, and returns the called flow's return value.

```python
from pathlib import Path

from fictive import Runtime, ask, call_actor

SCENARIO_ROOT = Path(__file__).parent
WRITER_SYSTEM = SCENARIO_ROOT / "writer_system.txt"
CRITIC_SYSTEM = SCENARIO_ROOT / "critic_system.txt"


def critic_flow(runtime):
    runtime.refresh()
    runtime.system(CRITIC_SYSTEM)
    # Feed the writer's latest output to the critic as a user turn.
    runtime.input_from_actor("writer", enclosing_prompt="Critique this scene:\n{INPUT_FROM}")
    runtime.generate()
    return runtime.raw_latest_text()          # becomes call_actor's return value


def writer_flow(runtime):
    runtime.refresh()                         # start from a clean history
    runtime.system(WRITER_SYSTEM)             # set the system prompt
    runtime.store_set("round", 0)             # write to the store

    # `ask` suspends the flow until a human answers, then records the answer
    # in the actor's history and in the store under "premise".
    yield from ask(runtime, "Premise>", store="premise")
    runtime.input_from_store("premise", enclosing_prompt="Write a scene about: {INPUT_FROM}")
    runtime.generate(visible=True)            # run the model
    runtime.show_latest()                     # print the result

    # A loop: keep revising until the critic is satisfied (or three rounds pass).
    while runtime.store_get("round") < 3:
        critique = yield from call_actor(runtime, "critic", critic_flow)   # run-actor
        if "APPROVED" in critique:            # a cond
            break
        runtime.append(f"Revise the scene. Feedback: {critique}")
        runtime.generate(visible=True)
        runtime.show_latest()
        runtime.store_set("round", runtime.store_get("round") + 1)
```

## Special Commands Framework

The `fictive` library includes a framework for special commands that can be executed during gameplay by typing `/command` (e.g., `/save`, `/load`, `/help`).

### Command Framework Components

1. **Command Registry**: `Runtime.register_command(name, handler)` registers a command handler.
2. **Command Handlers**: Functions taking `(runtime: Runtime, args: str)` that execute the command.
3. **Flow Control**: Commands can raise `CommandRestart` to restart the flow or `CommandExit` to exit.
4. **Integration**: Commands are detected in the `ask()` function transparently to the flow.

### Example: Save/Load Commands

The INFT scenario implements save/load functionality:

- **`/save`**: Saves the current game session with auto-generated session ID.
- **`/load [id]`**: Loads a saved game (most recent or partial ID match).
- **`/list`**: Lists all saved game sessions.
- **`/help`**: Shows available commands.
- **`/quit`**: Exits the game.

### Usage in Scenarios

Scenarios can define their own commands in a `special_commands.py` module:

```python
# special_commands.py
from fictive import CommandRestart, CommandExit

_COMMANDS = {}

def command(name):
    def decorator(func):
        _COMMANDS[name] = func
        return func
    return decorator

@command("save")
def handle_save(runtime, args):
    session_id = runtime.save_session()
    print(f"Game saved as {session_id}")

def register_commands(runtime):
    for name, handler in _COMMANDS.items():
        runtime.register_command(name, handler)
```

Then in `main.py`:
```python
import special_commands
special_commands.register_commands(runtime)

# Restart loop for commands like /load
while True:
    try:
        drive_flow(play(runtime))
        break
    except CommandRestart:
        continue  # Restart with loaded session
```

### Session Storage

Saved sessions are stored in `~/.local_chatlogs/conversations/<session_id>.json` by default, where session IDs follow the format `YYYYMMDDTHHMMSSZ-random8`. The session file contains the complete interpreter state (actors, store, callstack, etc.).

### Backward Compatibility

Scenarios without registered commands work unchanged. Inputs starting with `/` are treated as normal conversation when no commands are registered.


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

## Scenario Directories

This is the JSON scenario format, run by `run_chat`, `run_debug` and
`run_single_actor`. The web UI does not use it -- it runs a Python flow, and
`--scenario` there names a scenario module instead (see [Web UI](#web-ui)).

To be loadable by `load_scenario_config`, a scenario directory must satisfy the
following rules:

1. **`schema.json` is the only required file.** It must sit at the root of
   the scenario directory. Every other file is named *from* it.
   - `actors` (required): the list of actor names in the scene.
   - `main_actor` (optional): the chat actor; defaults to `actors[0]`.
   - `actor_types` (optional): `"generator"`, `"scorer"`, or omitted for a
     plain `Actor`, per actor name.
   - `actor_definitions` (optional): overrides the default per-actor file
     path (`<scenario_dir>/<actor>.json`).
   - `names`, `author_intent`, `actor_output_formats`: loaded, but never
     applied at runtime.

2. **One JSON file per actor.** For each name in `actors`, there must be a
   matching `<scenario_dir>/<name>.json` — a JSON array of command objects.
   A missing file raises an error. Field names accept `-` or `_`
   interchangeably (`actor-name` = `actor_name`); see
   `SCENE_CONFIG_LANGUAGE.md` for the full field reference.

3. **Prompt files can live anywhere.** Any relative string in an actor
   definition that resolves to an existing file — relative to that actor's
   own definition file — is rewritten to an absolute path.
   - Silent failure mode: an unresolvable path is left as-is and used as
     literal prompt text, not an error.
   - Exceptions: `workspace` on an `agent` command is never path-resolved;
     `"var:key"` strings are store lookups, not paths.

4. **Display name**: the directory's own name, unless it is literally named
   `scenario`, in which case the parent directory's name is used
   (`examples/ui_demo/scenario` → `ui_demo`).

5. **Session files live outside the scenario**, under `--storage-dir` — a
   scenario directory is read-only at runtime.

6. A `"scorer"` actor type always enforces the default `SCORE: [1-5]` output
   regex; `actor_output_formats` never reaches it, so a weak/mock model is
   guaranteed to fail as a scorer. Use a plain actor (as `ui_demo` does for
   its critic) unless a real model backs it.

Example layout:

```
examples/ui_demo/scenario/
├── schema.json              # required, this exact name
├── narrator.json            # one per name in schema["actors"]
├── scene_critic.json
└── prompts/                 # any layout; referenced relatively
    ├── narrator_system.txt
    └── scene_critic_task.txt
```

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

### Commands over HTTP

Commands are dispatched inside `ask`, so they work the same in the web UI as in a terminal: a message beginning with `/` is consumed by its handler and the flow is asked for the reader's answer again. What a handler prints is captured and
shown in the transcript as a step rather than going only to the server's terminal. `CommandRestart` (what `/load` raises) rebuilds the flow generator against the restored state, and `CommandExit` finishes the session.

## Web UI

A browser front end for playing a scenario as a conversation. The main actor's visible generations are the chat:


```python
runtime.generate(prompt="sample_prompt_file.txt", visible=True)
```

Every actor a flow calls appears inline as an
expandable bar- i.e: every `call_actor` function opens an expandable bar within the parent chat.

```python
yield from call_actor(runtime, "actor_name")
```

Note that the called actors in the UI nest only five levels deep. You can nest `call_actor` statements deeper and it'll run, it just won't show in the UI.


The backend (`fictive/web/`) runs a flow. A flow suspends when it needs a human answer. `next(flow)` runs the flow up to the first `InputRequest`. In the web interface, instead of waiting on a `yield from ask(...)` statement, the flow waits to receive a `POST` request from the UI.


Two things that are required within a `flow` function for the Web UI to work:
- `generate(visible=True)` marks the one generation the reader should see
- `ask(..., content=False)` marks a prompt as a human input cue -- a terminal prints it, the web UI shows its own input box instead.

### Writing a scenario for the web UI

`--scenario` takes a Python module: a `.py` file, or a directory containing `fictive_scenario.py`. The module answers a small contract, and the backend builds the actors itself so one pipeline chosen on the command line serves the
whole scenario:

```python
NAME = "evil_AI"                      # optional; defaults to the directory name
MAIN_ACTOR = "generator"              # required: whose generations are the chat
ACTOR_TYPES = {"generator": "generator", "helper": None}   # or ACTOR_NAMES
def flow(runtime): ...                # required: the entry flow
def resume_flow(runtime): ...         # optional; used instead of `flow` on a resume
def register_commands(runtime): ...   # optional; see Special Commands, below
```

`examples/evil_AI` is laid out this way: `config.py` owns the paths and the argument parser, `flows.py` the flows, `fictive_scenario.py` the contract above, and `main.py` remains the terminal entry point driving the same `flow` through `drive_flow`. The module's own directory goes on `sys.path` before it is imported, so a scenario package can keep importing its siblings flat (`from config import ...`). One consequence: those flat names are global, so one
process serves one scenario.

**Resuming.** A session file holds actor histories, the store and the callstack, but not a flow's position -- that lives in a Python generator. So resuming restores the state and starts the flow again against it. The backend sets the
store variable `RESUMED_STORE_KEY` (`"_fictive_resumed"`) first, so a flow can
skip its own prologue rather than narrating the opening a second time:

```python
if not runtime.store_get(RESUMED_STORE_KEY):
    runtime.generate(OPENING, visible=True)
```

A scenario that needs more than a branch can define `resume_flow(runtime)`
instead. Either way the transcript is rebuilt from the main actor's history, and
says plainly that frames from before the save are not in the file.

### Rewriting a message, and forking a conversation

Hovering a reader message in the transcript reveals **Rewrite** and **Fork**.
Both open the message for editing; they differ in what becomes of the turns
after it.

- **Rewrite** runs the same conversation on from that message. Everything the
  original message led to is discarded, later turns included, and a fresh
  generation follows the new text. The editor says how many turns will go.
- **Fork** leaves the session exactly as it is and starts a second one that
  shares the conversation up to that message. This is the one to use when the
  later turns are worth keeping. With no replacement text, the fork simply parks
  where the original was asked for that message.

Neither can rewind a flow, because a flow's position lives in a parked Python
generator. What they do instead is the mechanism resuming already uses: the
backend takes a *checkpoint* each time a flow parks to ask the main actor's
reader for a message -- the same state a session file holds, kept in memory --
and going back means restoring one, cutting the transcript at the same point,
throwing the old generator away and starting a fresh flow against the restored
state. `RESUMED_STORE_KEY` is what keeps the prologue from running again, so a
scenario that already resumes correctly rewrites and forks correctly too.

Two consequences worth knowing. Only messages the backend still holds a
checkpoint for can be branched at -- reported to the UI as `branch_points`, and
which is why a session resumed from a file has real messages with nothing to
rewind to until it takes a turn of its own, and why only the 50 most recent are
kept. And a rewrite works on a session whose flow has finished or failed, which
makes it the way out of a turn that broke: the flow is replaced either way.

**Two guard rails.** A turn that issues 400 commands without asking for input
is stopped and reported as an error, because a generator that never yields would
otherwise hold the request open forever. And an `input-from` command carrying a
`human_prompt` fails with a message pointing at `ask`, rather than blocking on a
terminal that isn't there.

### Running it

Two processes in development. From the repository root:

```bash
uv pip install --python .venv/bin/python fastapi "uvicorn[standard]"
.venv/bin/python -m fictive.web --scenario examples/evil_AI --pipeline-type mock
```

Those two packages are the `ui-server` extra, installed directly because the
repository's `.venv` is uv-managed and has no `pip` of its own.

Then, from `ui/`:

```bash
npm install
npm run dev          # http://localhost:5173
```

`--pipeline-type mock` needs no model and no credentials. For a real model,
pass any pipeline `llm-utils` builds -- `--pipeline-type openai --model
deepseek/deepseek-v3.2` for an OpenAI-compatible endpoint such as OpenRouter,
or `--pipeline-type anthropic --model claude-sonnet-5`. Each pipeline resolves
its own provider's key from the environment or a `.env` in the working
directory, so no key need appear on the command line.

To serve both from one process, run `npm run build` in `ui/`; the backend
mounts the built `ui/dist` at `/`.

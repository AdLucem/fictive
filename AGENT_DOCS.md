# Fictive Agent Docs

This file is the condensed architecture reference for the repository.

Before reading a Python source file to understand what a class, module, or
runtime path is doing, first consult `AGENT_DOCS.md`. Only open the underlying
implementation file if `AGENT_DOCS.md` does not provide enough clarity for the
task at hand.

## Scenario Command Flow

### 1. Scenario Layout

At the scenario level, a directory such as `examples/evil_AI/scenario/`
contains:

- `schema.json`
  Declares the actor names and optional metadata such as output regexes.

- `<actor>.json`
  A JSON array of command objects. Each object has a `cmd` field and
  command-specific parameters.

- Prompt files such as `generator_prompt.txt`
  These are referenced by command params and resolved relative to the scenario
  directory by `load_scenario_config(...)`.

### 2. Scenario Loading

`fictive/parse_scenario_config.py` is the first stage.

- `load_scenario_config(scenario_dir)` reads `schema.json`.
- It loads each actor definition file named in `schema["actors"]`.
- It recursively resolves relative paths inside those actor JSON structures.
- It compiles `actor_output_formats` regexes when present.
- It returns:
  - `schema`
  - `actor_definitions`
  - `author_intent`

At this point, actor definitions are still plain Python data loaded from JSON.
Commands have not yet been turned into typed runtime objects.

### 3. Actor Construction

Actors are built from `ActorConfig` in `fictive/actors.py`.

Important fields:

- `name`
- `instructions`
- `pipeline` or `pipeline_config`
- `actor_type`

When an `Actor` is initialized:

- It stores config and history.
- It normalizes instructions with `Actor.normalize_instructions(...)`.
- Any raw command dict is converted into a command dataclass object.
- It initializes the LLM pipeline if one was not passed directly.

Special actor subclasses live in `fictive/custom_actors.py`:

- `Generator`
  Returns the whole rendered scene as its latest output.

- `Scorer`
  Runs a normal generation, then extracts a numeric score from the assistant
  output and stores that score in `self.scores`.

### 4. Command Parsing

Command parsing lives in `fictive/parser/commands.py`.

The key pieces are:

- `Cmd`
  Enum mapping command names such as `system`, `generate`, `input-from`,
  `write`, and `cond` to their dataclass implementations.

- Command dataclasses
  Each command has a dataclass like `SYSTEM`, `GENERATE`, `INPUT_FROM`,
  `RUN_ACTOR`, `ASSIGN`, `WRITE`, `PRINT`, `PRINT_LATEST`, and `COND`.

- `parse_command_dict(instr)`
  Shared helper that:
  - reads `instr["cmd"]`
  - maps the name through `Cmd`
  - normalizes parameter names
  - instantiates the matching dataclass

Parameter normalization matters because scenario JSON can use hyphenated names
like `actor-name`, while Python dataclasses expect `actor_name`.

For `cond`, parsing is recursive:

- the outer command is parsed into `COND`
- each branch in `conditions` is inspected
- nested `commands` blocks are themselves parsed into command dataclass objects

So by the time the interpreter sees a command, it is already working with typed
objects rather than raw dicts.

### 5. Actor Instruction State

Each actor has two layers of instruction state:

- `instructions`
  The actor's base instruction list loaded from scenario JSON.

- `pending_instructions`
  A queue used for dynamically inserted commands, currently needed by `cond`
  branch execution.

`Actor.get_current_instr()` prefers `pending_instructions` when present.
That lets a conditional branch inject a temporary block without rewriting the
base instruction list.

### 6. Interpreter Structure

Runtime execution lives in `fictive/interpreter.py`.

The interpreter owns:

- `actors`
  Mapping from actor name to actor instance.

- `store`
  Shared variable memory used by commands such as `assign`, `input-from`, and
  `cond`.

- `waiting_store`
  Deferred captures of another actor's final output after `run-actor`.

- `callstack`
  Tracks which actor currently has control.

- `exec_map`
  Maps command names to concrete handler methods like `exec_SYSTEM`,
  `exec_GENERATE`, `exec_INPUT_FROM`, `exec_WRITE`, and `exec_COND`.

### 7. Step Execution

The main runtime entry is `Interpreter.exec_current()`.

Its flow is:

1. Read the current actor from the top of the callstack.
2. Fetch the current instruction from that actor.
3. Dispatch the instruction through `Interpreter.exec(...)`.
4. Advance either:
   - the actor's base `cur_step`, or
   - the `pending_instructions` queue if a dynamic block is running.
5. If an actor just finished:
   - pop the callstack
   - copy deferred outputs from `waiting_store` into `store`
6. Return the actor now at the top of the stack, or `-1` if execution ended.

This means the interpreter is effectively a tiny command VM with:

- per-actor program counters
- a shared store
- a callstack
- dynamically queued sub-blocks

### 8. What Each Command Does

The main command handlers are:

- `system`
  Loads prompt text and sets the actor's system prompt.

- `generate`
  Sends the current merged history, optionally with an extra prompt, through
  the actor's pipeline.

- `input-from`
  Pulls input from:
  - a human
  - another actor's latest output
  - a store variable
  Then optionally wraps it in an enclosing prompt and either stores it or
  appends it to history.

- `run-actor`
  Pushes another actor onto the callstack and transfers control to it.
  If `store` is provided, the called actor's eventual output is captured later
  into the shared store.

- `assign`
  Writes a value directly into the shared store.

- `write`
  Writes either the current actor's latest output, parsed prompt-like input,
  or another actor's serialized history to a file under the scenario storage
  directory.

- `print` / `print-latest`
  Debug/inspection helpers.

- `loop`
  Rewinds the actor's instruction pointer to an earlier step.

- `refresh`
  Clears actor history except for the system prompt.

- `cond`
  Evaluates ordered branch conditions against the shared store and queues the
  first matching branch's nested commands into `pending_instructions`.

### 9. Condition Evaluation

`cond` uses `Interpreter.evaluate_condition(...)`.

That function:

- builds an evaluation context from `self.store.store`
- parses the condition string with Python `ast`
- whitelists safe expression node types
- rejects unknown variable names
- evaluates the expression without Python builtins

So a condition such as:

    (fear > 2.0) and (trust < 3.0)

reads `fear` and `trust` directly from the shared store.

An `else` branch is represented by:

- `condition: "else"`
- or a missing/empty condition

### 10. Prompt Resolution

Prompt-like parameters are interpreted by
`Interpreter.parse_prompt_object(...)`.

It supports:

- raw strings
- file paths
- store references like `var:full-instr`
- message dicts with `role` and `content`

This is why actor JSON can freely mix literal text, prompt files, and store
variables in command params.

### 11. Pipelines

Actual model calls are not done in the interpreter itself.

- Actors delegate to `self.pipeline.generate(...)`
- Pipeline implementations live in `llm-utils/llm_utils/pipelines.py`

The important boundary is:

- scenario language decides what to ask and when
- actor history packages the conversation
- pipeline backend performs the actual model request

### 12. Mental Model

A useful way to think about the architecture is:

- `parse_scenario_config.py`
  Loads scenario files from disk.

- `parser/commands.py`
  Converts JSON command dicts into typed command objects.

- `actors.py`
  Holds instruction state, history, and pipeline access.

- `interpreter.py`
  Executes one command at a time, manages control flow, and mutates store and
  history.

- `custom_actors.py`
  Specializes how some actors interpret or expose outputs.

In short:

scenario JSON -> parsed command objects -> actor instruction lists ->
interpreter dispatch -> history/store mutation -> pipeline calls when needed

### 13. Why `cond` Fits Cleanly

`cond` works well in this architecture because the system already has:

- typed commands
- a shared variable store
- per-actor instruction stepping

The missing piece was only a way to insert a temporary block of commands into
execution. `pending_instructions` provides that mechanism without forcing the
interpreter to rewrite the actor's underlying instruction list.

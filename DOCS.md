# Repository Docs

## Overview

This repository contains `fictive`, a Python package for building LLM-driven
interactive fiction systems. The core runtime centers on actors that follow
instruction sequences, an interpreter that executes those instructions, and a
pipeline layer that sends prompts to an LLM backend.

The repository depends on the `llm-utils/` git submodule for shared LLM request
helpers and SGLang integration.

## Repository Structure

### Top Level

- `DOCS.md`
  This file. It documents the repository structure and the main runtime flow.

- `AGENTS.md`
  Repository maintenance rule for keeping `DOCS.md` current when the project
  structure or usage changes.

- `AGENT_DOCS.txt`
  Internal architecture notes describing how scenario commands are loaded,
  parsed into runtime command objects, and executed by the interpreter.

- `AGENT_DOCS.md`
  Condensed architecture reference intended to be read before opening source
  files when a future agent needs to understand how a class or module works.

- `README.md`
  Minimal project description.

- `pyproject.toml`
  Standard Python packaging metadata for the repository. It defines the
  installable project, runtime dependencies, editable-install support, and
  package discovery for `fictive` and its subpackages.

- `__init__.py`
  Compatibility package shim for vendored/submodule usage. If another
  repository checks this repo out as `fictive/`, importing `fictive` from the
  parent project root re-exports the inner `fictive/` package API and aliases
  the main submodules such as `fictive.actors` and `fictive.parser`.

- `SCENE_CONFIG_LANGUAGE.md`
  Reference for the scene command language interpreted by `fictive`.

- `requirements.txt`
  Main Python dependency set for the project.

- `sglang-requirements.txt`
  Narrower dependency set for SGLang-focused environments.

- `setenv`
  Example shell environment bootstrap for local or cluster usage. It extends
  `PYTHONPATH`, sets `HF_HOME`, and loads CUDA/GCC modules.

- `llm-utils/`
  Git submodule containing shared LLM request utilities, SGLang helpers, and
  its own repository-level documentation.

- `test/`
  Unit-style coverage for the `fictive` package and compatibility coverage for
  `llm-utils` integration points used by this repository.

### Package: `fictive/`

- `fictive/__init__.py`
  Re-exports the main public entry points, including actors, the interpreter,
  scenario loading helpers, and runtime helpers from `run.py`. It also defines
  the explicit public export list used by the repo-root compatibility shim.

- `fictive/actors.py`
  Defines `ActorConfig` and the base `Actor` class. Actors own instruction
  lists, conversation history, optional storage, and a shared LLM pipeline.

- `fictive/custom_actors.py`
  Defines actor subclasses with specialized output behavior, including
  `Generator` and `Scorer`, plus the registration map used to build actor types
  from configuration.

- `fictive/data_structures.py`
  Defines the in-memory containers used at runtime:
  - `History` for chat transcripts
  - `Scene` for rendered scene views
  - `Store` for interpreter variables

- `fictive/interpreter.py`
  Implements the instruction executor. It manages actor dispatch, the call
  stack, variable passing, and the concrete command handlers such as
  `system`, `generate`, `input-from`, `run-actor`, `assign`, `cond`, and
  `print`. Conditional branches queue nested command blocks and evaluate
  expressions against the shared interpreter store.

- `fictive/parse_scenario_config.py`
  Loads a scenario directory from disk. It reads `schema.json`, loads per-actor
  JSON definitions, resolves relative file references inside those definitions,
  and compiles actor output-format regexes.

- `fictive/run.py`
  Runtime entry points for executing scenarios. It provides:
  - `run_debug` for step-by-step interpreter debugging
  - `run_chat` for interactive execution flow
  - `run_single_actor` for single-actor testing that replaces inter-actor
    dependencies with user prompts where needed

### Package: `fictive/parser/`

- `fictive/parser/__init__.py`
  Marks `parser/` as an explicit Python subpackage and re-exports the main
  parser helpers used by the rest of the package.

- `fictive/parser/commands.py`
  Defines the command enum and the dataclass-backed command objects consumed by
  actors and the interpreter.

- `fictive/parser/expressions.py`
  Expression helpers for the scenario language.

## How The Pieces Fit Together

The normal runtime flow is:

1. Create or point to a scenario directory with a `schema.json` file and one
   JSON file per actor.
2. Start or configure an LLM backend. Today that usually means an SGLang server
   reachable by the `llm-utils` request helpers, or the local `mock` pipeline
   for tests.
3. Build an `llm_utils.PipelineConfig`, then initialize a shared pipeline with
   `llm_utils.pipeline_from_config(...)`.
4. Load scenario metadata with `load_scenario_config(...)`.
5. Build `Actor` instances from the loaded actor definitions.
6. Pass the actors into `Interpreter`, then execute the interpreter with one of
   the helpers in `fictive.run`.

At runtime, each actor advances through a list of instruction objects. The
interpreter evaluates the current command, updates actor history or shared
store state, and hands control across actors through the call stack when a
`run-actor` instruction executes.

The concrete LLM backend classes are provided by
`llm-utils/llm_utils/pipelines.py`. The `fictive` package uses those shared
pipeline definitions directly.

For standard package installation, use:

```bash
pip install -e .
```

The package metadata in `pyproject.toml` declares the runtime dependencies,
including the direct `llm-utils` dependency used by the actor and runtime
modules. The repo-root compatibility shim remains for vendored/submodule use,
but normal installation no longer depends on a sibling `llm-utils/` checkout.

If this repository is included in another project as a git submodule at
`fictive/`, code in the parent project can import the public API directly from
the parent root:

```python
from fictive import Actor, ActorConfig, Interpreter
from fictive.data_structures import Store
```

The repo-root `__init__.py` forwards those imports to the inner
`fictive/` package so parent projects do not need to import from
`fictive.fictive`.

## Scenario Configuration

Scenario loading expects a directory with this general shape:

```text
my_scenario/
  schema.json
  generator.json
  scorer.json
  prompts/
    intro.txt
```

`schema.json` names the actors and can define actor output-format regexes.
Each actor JSON file contains that actor's instruction sequence in the command
language documented in `SCENE_CONFIG_LANGUAGE.md`. The scene language supports
ordered conditional branches through the `cond` command, which evaluates
store-backed expressions and queues nested command blocks for the first
matching branch.

When actor definitions contain relative paths, `load_scenario_config(...)`
resolves them relative to the scenario directory if the target exists there.

## Example: Build And Run A Scenario Interpreter

```python
from fictive import Actor, ActorConfig, Interpreter, load_scenario_config
from llm_utils import PipelineConfig, pipeline_from_config

schema, actor_definitions, author_intent = load_scenario_config("path/to/scenario")

pipeline_cfg = PipelineConfig(
    model="meta-llama/Llama-3.1-8B-Instruct",
    pipeline_type="mock",
)
pipeline = pipeline_from_config(pipeline_cfg)

actors = []
for actor_name, instructions in actor_definitions.items():
    actors.append(
        Actor(
            ActorConfig(
                name=actor_name,
                storage_dir="path/to/scenario",
                instructions=instructions,
                pipeline=pipeline,
            )
        )
    )

interpreter = Interpreter(actors, main_actor_name="generator")
```

## Testing

The repository test suite lives in `test/`.

- `test/data_structures_test.py`
  Covers `History`, `Scene`, and `Store`.

- `test/parse_scenario_config_tests.py`
  Covers scenario loading and relative-path resolution.

- `test/pipelines_tests.py`
  Covers pipeline config helpers and prompt parsing behavior.

- `test/run_tests.py`
  Covers top-level scenario-loading behavior used by runtime entry points.

- `test/request_sglang_tests.py`
  Covers the SGLang request CLI and prompt parsing behavior provided through
  `llm-utils`.

- `test/llm_utils_tests.py`
  Covers `llm-utils` config conversion behavior relied on by this repository.

Run the full suite with:

```bash
python3 -m pytest test
```

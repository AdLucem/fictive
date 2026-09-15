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

- `AGENT_HARNESS_INTEGRATION_PLAN.md`
  Design and delivery record for the independent, workspace-scoped `agent`
  instruction backed by Pydantic AI Harness. It covers the package boundary,
  custom model APIs, filesystem permissions, Fictive integration, testing,
  and phased delivery work. Phases 1 through 4 are implemented.

- `MINIMAX_AGENT_SETUP.md`
  Operator guide for opt-in MiniMax execution through the
  Anthropic-compatible endpoint. It documents environment variables, `.env`
  loading, live verification, and Docker credential injection separately from
  scenarios and examples.

- `README.md`
  Project installation guide, including `uv` and Docker commands for the
  Phase 1 agent-harness compatibility environment.

- `Dockerfile`
  Container environment for Fictive dependencies and compatibility checks. Its
  entrypoint exports `/app/.env` when present before running the requested
  command.

- `.dockerignore`
  Prevents local `.env` credentials from being copied into container images;
  pass them with `--env-file` or mount `/app/.env` at runtime instead.

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
  Main Python dependency set for the project. It installs the standalone local
  `agent-harness` package, which owns the pinned Pydantic AI Harness,
  Pydantic AI Anthropic provider, and Anthropic SDK compatibility stack.

- `sglang-requirements.txt`
  Narrower dependency set for SGLang-focused environments.

- `setenv`
  Example shell environment bootstrap for local or cluster usage. When sourced,
  it exports variables from the parent Centaurus `.env`, extends `PYTHONPATH`,
  and retains examples for configuring `HF_HOME` and loading CUDA/GCC modules.

- `compatibility/agent_harness_spike.py`
  Reproducible Phase 1 check for the proposed independent agent harness. Its
  default mode verifies pinned imports, custom Anthropic endpoint/model
  construction, and a complete local filesystem tool-call loop without
  network access. `--live` performs an opt-in MiniMax tool-call check using
  environment credentials.

- `agent-harness/`
  Independent Python distribution implementing the Phase 2 agent wrapper. It
  has its own `pyproject.toml`, dependency lock, README, public
  `agent_harness` package, and deterministic tests. It does not import Fictive
  or `llm-utils` and can later move to a dedicated repository/submodule without
  changing its package API.

  - `agent_harness/config.py`
    Loads trusted profiles, validates permission ceilings, and defines the
    filesystem tool sets and protected path defaults.
  - `agent_harness/providers.py`
    Builds Anthropic or Anthropic-compatible models and accepts host-registered
    custom model builders.
  - `agent_harness/history.py`
    Converts provider-neutral system, user, and assistant history into Pydantic
    AI messages.
  - `agent_harness/workspace.py`
    Resolves requested workspaces beneath the trusted host root, builds a fresh
    filtered filesystem toolset, and records normalized changed paths.
  - `agent_harness/results.py`
    Defines the stable request/result protocol, removes SDK types from traces,
    and redacts credentials.
  - `agent_harness/executor.py`
    Runs bounded synchronous agents and normalizes success or provider failure.
  - `agent_harness/errors.py`
    Defines public configuration and workspace-policy exceptions.
  - `tests/test_agent_harness.py`
    Deterministic fake-model coverage for history, permissions, containment,
    tool calls, limits, failures, redaction, changes, and workspace isolation.

- `llm-utils/`
  Git submodule containing shared LLM request utilities, SGLang helpers, and
  its own repository-level documentation.

- `test/`
  Unit-style coverage for the `fictive` package and compatibility coverage for
  `llm-utils` integration points used by this repository.

  - `test/agent_integration_tests.py`
    Deterministic coverage for `agent` parsing, prompt and history transfer,
    output/trace storage, optional actor pipelines, workspace containment,
    failure state, and interpreter call-stack behavior.

- `examples/agent_filesystem_demo/`
  Runnable agent-command example. Its scenario uses only `read_file` and
  `write_file`; `main.py` injects a workspace-scoped standalone executor and
  uses a deterministic Pydantic AI function model by default. It can optionally
  use MiniMax after the environment is explicitly configured.

  - `main.py`
    Creates or accepts the host workspace, constructs the trusted profile and
    executor, builds pipeline-free actors, executes the interpreter, and prints
    final output plus changed-path trace data.
  - `scenario/filesystem_worker.json`
    Demonstrates all core `agent` fields in scenario JSON.
  - `scenario/filesystem_worker_system.txt`
    Supplies the actor's initial system history.

### Package: `fictive/`

- `fictive/__init__.py`
  Re-exports the main public entry points, including actors, the interpreter,
  provider-neutral agent contracts, scenario loading helpers, and runtime
  helpers from `run.py`. It also defines the explicit public export list used
  by the repo-root compatibility shim.

- `fictive/agent_api.py`
  Defines Fictive's provider-neutral `AgentRequest`, structural
  `AgentExecutor`/`AgentResult` protocols, and `AgentRunFailed`. It has no
  dependency on the standalone harness, Pydantic AI, or `llm-utils`.

- `fictive/agent_integration.py`
  Bridges actor state to the agent API. It proves each requested relative
  workspace is beneath the canonical host root, snapshots actor history into
  a request, and converts structured executor results into ordinary store
  values.

- `fictive/actors.py`
  Defines `ActorConfig` and the base `Actor` class. Actors own instruction
  lists, conversation history, optional storage, and an optional LLM pipeline.
  Agent-only actors may omit the generation pipeline; executing `generate`
  without one raises a clear runtime error. `Actor.generate(prompt=None,
  on_delta=None)` accepts an optional `on_delta` callback: when given, the
  call goes through `self._run_pipeline`, which drives the pipeline's
  `generate_stream(messages)` (from `llm_utils`) instead of `generate(messages)`,
  invoking `on_delta` with each non-final event; the resulting history entry
  is identical either way, and `on_delta=None` (the default) behaves exactly
  as before. `_run_pipeline` is the shared helper both `generate` and any
  subclass that calls the pipeline directly (e.g. custom actors defined in
  `centaurus/src/`) should use, so streaming support does not need
  reimplementing per subclass.

- `fictive/custom_actors.py`
  Defines actor subclasses with specialized output behavior, including
  `Generator` and `Scorer`, plus the registration map used to build actor types
  from configuration. `Scorer.generate` accepts and forwards `on_delta` to
  every `super().generate(...)` call it makes, including its regeneration
  retries, since it calls the pipeline only through the base `Actor.generate`.

- `fictive/data_structures.py`
  Defines the in-memory containers used at runtime:
  - `History` for chat transcripts
  - `Scene` for rendered scene views
  - `Store` for interpreter variables

- `fictive/interpreter.py`
  Implements the instruction executor. It manages actor dispatch, the call
  stack, variable passing, and the concrete command handlers such as
  `system`, `generate`, `agent`, `input-from`, `run-actor`, `assign`, `write`,
  `cond`, and `print`. Conditional branches queue nested command blocks,
  evaluate expressions against the shared interpreter store, and `write` can
  persist latest outputs, prompt-like inputs, or actor histories to files.
  Agent execution uses only a host-injected executor and canonical root; the
  interpreter never constructs a provider or reads provider credentials.
  `Interpreter.on_generate_delta` is an optional `(actor_name, event) ->
  None` hook, `None` by default. When set, `exec_GENERATE` passes it through
  to the acting actor's `generate(on_delta=...)` for streaming display,
  wrapped to bind the current `actor_name`; every other instruction handler
  is unaffected. A host embedding the interpreter (such as `centaurus/src/api.py`'s
  SSE console endpoint) sets this once per exchange to receive token-level
  events as they occur, rather than only once each `generate` instruction
  finishes.

- `fictive/parse_scenario_config.py`
  Loads a scenario directory from disk. It reads `schema.json`, loads per-actor
  JSON definitions, resolves relative file references inside those definitions,
  and compiles actor output-format regexes. The `workspace` field of an
  `agent` command is deliberately left relative because it is resolved later
  against the runtime host root, not the scenario directory.

- `fictive/run.py`
  Runtime entry points for executing scenarios. It provides:
  - `run_debug` for step-by-step interpreter debugging
  - `run_chat` for interactive execution flow
  - `run_single_actor` for single-actor testing that replaces inter-actor
    dependencies with user prompts where needed

- `fictive/library_runtime.py`
  The other way to run a scenario: instead of a JSON instruction list, import
  the library and call interpreter commands from Python, letting Python's own
  `if`, `while` and function calls supply the control flow. It provides:
  - `Runtime`, a typed facade where each method (`system`, `generate`,
    `input_from_store`, `write`, `enter_actor`, ...) is one interpreter command
    executed against whichever actor currently holds control. It records every
    command in `trace`, exposes the one generation a host should display via
    `visible_generate`/`last_visible`, and with `mode="debug"` stops at a
    `debug> ` prompt before each command.
  - `InputRequest` plus `ask`, so a scenario written as a generator suspends at
    exactly the points that need a human answer and resumes through
    `generator.send(...)`. A blocking terminal driver (`drive_flow`) and a host
    that resumes the scenario once per HTTP request drive the same generator.
  - `call_actor`, which is `run-actor` plus the callee's own steps plus the
    callstack unwind, as a single Python call.

### Package: `fictive/parser/`

- `fictive/parser/__init__.py`
  Marks `parser/` as an explicit Python subpackage and re-exports the main
  parser helpers used by the rest of the package.

- `fictive/parser/commands.py`
  Defines the command enum and the dataclass-backed command objects consumed by
  actors and the interpreter, including the scene-language `write` command for
  file output and the bounded `agent` command.

- `fictive/parser/expressions.py`
  Expression helpers for the scenario language.

## How The Pieces Fit Together

The ordinary `generate` runtime flow is:

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

The `agent` path is separate from ordinary generation:

1. Trusted host code constructs a standalone `PydanticAgentExecutor` with
   profiles, credentials supplied through the environment, and a maximum
   workspace root.
2. The host passes that executor and the same root to `Interpreter` as
   `agent_executor` and `agent_root`.
3. An actor executes an `agent` command. The interpreter resolves its optional
   prompt, validates the relative requested workspace, and snapshots the full
   unmerged actor history.
4. The standalone harness repeats containment and permission checks, runs the
   bounded model/tool loop, and returns normalized output and trace data.
5. On success, Fictive appends exactly one assistant message and optionally
   stores the final text and trace. On failure, it preserves a requested trace,
   raises `AgentRunFailed`, and does not advance the interpreter step.

The interpreter requires `agent_root` to resolve to exactly the executor's
public `workspace_root`. Requested workspaces must be existing relative
directories beneath that root. This prevents a scenario from widening host
permissions and gives both Fictive and the standalone harness an independent
containment check.

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
matching branch, file output through the `write` command, and bounded agentic
filesystem work through the `agent` command.

When actor definitions contain relative paths, `load_scenario_config(...)`
resolves them relative to the scenario directory if the target exists there.
The exception is `agent.workspace`: it must remain relative until interpreter
execution so it can be checked against the host-provided agent root.

## Example: Workspace-Scoped Agent

The offline example exercises the complete scenario-to-harness path:

```bash
../.venv/bin/python examples/agent_filesystem_demo/main.py
```

It uses a temporary maximum workspace root, seeds `notes.txt`, and lets a
deterministic fake provider call `read_file` and `write_file`. It prints the
created `summary.txt` and the normalized changed paths, then cleans up the
temporary directory. No network or credentials are needed.

To retain the output, supply an existing directory containing `notes.txt`:

```bash
../.venv/bin/python examples/agent_filesystem_demo/main.py \
  --workspace /tmp/fictive-agent-demo
```

The example's `main.py` shows the required host construction: the same
canonical directory is supplied to `PydanticAgentExecutor(workspace_root=...)`
and `Interpreter(agent_root=...)`. See `MINIMAX_AGENT_SETUP.md` for the
separate opt-in MiniMax configuration.

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

- `test/agent_integration_tests.py`
  Covers command parsing, scenario workspace preservation, history and prompt
  transfer, the real standalone-executor seam, output/trace storage,
  containment rejection, pipeline-free actors, and interpreter state after
  successful and failed nested runs.

Run the full suite with:

```bash
../.venv/bin/python -m unittest discover -s test -p '*test*.py' -v
```

## Agent Harness Compatibility Environment

From the `fictive/` repository root, install the complete command-line
environment into the caller-provided virtual environment with `uv`:

```bash
uv pip install --python ../.venv/bin/python -r requirements.txt
../.venv/bin/python compatibility/agent_harness_spike.py
```

The compatibility command is offline by default. Real MiniMax environment
variables and the explicit live command are documented separately in
`MINIMAX_AGENT_SETUP.md` so credentials stay out of scenarios and examples.

Run the standalone wrapper suite without network credentials:

```bash
../.venv/bin/python -m unittest discover -s agent-harness/tests -v
```

Build and run the same offline check in Docker from the `fictive/` repository
root:

```bash
docker build -t fictive-agent-spike .
docker run --rm fictive-agent-spike \
  python3 compatibility/agent_harness_spike.py
```

The Docker build itself also runs the offline check. Live credentials must be
provided only at container runtime. The image entrypoint automatically exports
variables from `/app/.env` when that file is present; alternatively, Docker can
inject the same variables directly with `--env-file`:

```bash
docker run --rm --env-file ../.env \
  fictive-agent-spike \
  python3 compatibility/agent_harness_spike.py --live
```

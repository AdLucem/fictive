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
  package discovery for `fictive` and its subpackages. The optional extras
  `rag-local` (LlamaIndex and Hugging Face embeddings) and `rag-bedrock`
  (boto3) install the two `rag-generate` backends, `bedrock` installs the
  Bedrock pipeline and `web-search` the AgentCore gateway backend;
  `requirements-optional.txt` lists the same packages. The AWS extras include
  `botocore[crt]`, which profiles using the `login_session` credential provider
  need; without it credential resolution fails in a way that does not look like
  a missing dependency.

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
    executor, builds a pipeline-free actor, drives the `system` and `agent`
    commands through the library runtime (`fictive.Runtime`), and prints final
    output plus changed-path trace data.
  - `scenario/filesystem_worker.json`
    Demonstrates all core `agent` fields in scenario JSON. Kept as the JSON
    runtime's version of the same flow; `main.py` does not read it.
  - `scenario/filesystem_worker_system.txt`
    Supplies the actor's initial system history.

### Package: `fictive/`

- `fictive/__init__.py`
  Re-exports the main public entry points, including actors, the interpreter,
  the RAG backends and their passage/result types, provider-neutral agent
  contracts, scenario loading helpers, and runtime
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
  `Actor.state_dict()` / `load_state_dict(state)` capture and restore the
  resumable runtime state that session files hold: unmerged history, system
  prompt, `cur_step`, pending instructions, and `return_after_pending`.
  `load_state_dict` rejects a step outside the actor's instruction list. A
  subclass with runtime state of its own extends both methods.

- `fictive/custom_actors.py`
  Defines actor subclasses with specialized output behavior, including
  `Generator` and `Scorer`, plus the registration map used to build actor types
  from configuration. `Scorer.generate` accepts and forwards `on_delta` to
  every `super().generate(...)` call it makes, including its regeneration
  retries, since it calls the pipeline only through the base `Actor.generate`.
  `Scorer` extends `state_dict` / `load_state_dict` with its `scores`.

- `fictive/data_structures.py`
  Defines the in-memory containers used at runtime:
  - `History` for chat transcripts
  - `Scene` for rendered scene views
  - `Store` for interpreter variables

  Three behaviours callers depend on:
  - `History.read` returns fresh dicts. Reading never edits stored messages,
    so a structured `content` -- a dict, from a function-calling model or a
    parsed route -- stays structured for every later reader, while the caller
    that asked still gets it rendered as text. Before this, one read flattened
    it permanently, which meant merely inspecting a session (a history
    endpoint, a debugger view) changed the conversation it was inspecting.
  - `History.get_merged` copies every message it appends, including the first.
    Appending the stored dict and then merging into it edited the caller's
    history in place whenever the second message shared the first one's role.
    Merged content is joined with an f-string rather than `+=`, so a
    non-string content concatenates instead of raising `TypeError`.
  - `Store.has(var_name)` reports whether a variable was ever assigned. `get`
    cannot answer that: an unassigned variable and one deliberately assigned
    `None` both read back as `None`.

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
  `Interpreter.store_fetch` resolves a variable by presence rather than by
  truthiness, through `Store.has`, so a variable deliberately assigned `None`
  -- an optional argument a router left out, say -- returns `None` instead of
  raising "not in memory store", which is a different and misleading
  complaint.
  Session commands: `save-conversation` and `load-conversation`, plus
  `Interpreter.save_session(path=None, session_id=None)` and
  `load_session(path=None, session_id=None)` for hosts. Paths resolve against
  the acting actor's storage directory for commands, and the main actor's for
  the methods. Every interpreter starts with a fresh `session_id`, so
  repeated saves update one file. `exec_current` is a thin wrapper around
  `_exec_current_step`: a `save-conversation` executed in the step is written
  only after the step's bookkeeping, so the file resumes on the next
  instruction, and a `load-conversation` makes the step skip the bookkeeping
  it computed for the state that was just replaced.
  `rag-generate` resolves a backend with `fictive.rag.backend_kind`, cached per
  `(kind, storage_dir)` in `rag_backends`. A Bedrock backend retrieves and
  generates, reusing the per-actor `rag_sessions` id. With the local backend,
  the interpreter wraps the retrieved passages into the pipeline's copy of the
  last user message and generates through `_run_pipeline`, streaming through
  `on_generate_delta` like `generate`. The command's prompt joins history
  only after the backend call succeeds.
  `Interpreter(rag_backend=..., conversations_dir=...)` lets a host supply the
  backend, used whenever a command names no `backend`, and one directory for
  every session file and the local index (`conversations_root`). A
  `rag-generate` `query` retrieves on something other than the prompt,
  `fallback-on-retrieval-error` answers without context when retrieval raises,
  and nothing retrieved sends the conversation unwrapped.
  `web-search-and-generate` works the same way through
  `resolve_web_search_backend` and `fictive.websearch.backend_kind`, cached by
  kind in `web_search_backends`, with `Interpreter(web_search_backend=...)` as
  the host hook. It always generates with the actor's pipeline: the results are
  wrapped into the pipeline's copy of the last user message and never stored in
  history, the prompt joins history only after the search returns, and
  `fallback-on-search-error` answers without web results when the search
  raises. Both handlers locate the last user message by index list rather than
  `max(...)`, which raises when a history holds no user turn at all.
  `resolve_prompt_path` treats a string too long to be a path as literal text
  instead of raising `OSError`.

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

<<<<<<< HEAD
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
=======
  This module and `fictive/library_runtime.py` both import `transformers`
  inside a `try/except ImportError`, because they use it for nothing but
  quietening its own logger. `transformers` stays in `requirements.txt` --
  `TransformersPipeline` needs it for local inference -- but an API-only
  install can now import either entry module without it.
>>>>>>> e1b976bef1c88233bf489f3b44eafeca5a49ac08

- `fictive/library_runtime.py`
  `Runtime`, for hosts that drive the interpreter one command at a time with
  `cmd_exec(command, **kwargs)` instead of stepping scenario JSON.
  `cmd_exec` accepts `_` for `-` in command names. `save_session(...)` and
  `load_session(...)` delegate to the interpreter; after a load,
  `working_actor` becomes the top of the restored callstack. `main_actor_name`
  is taken from the interpreter and `main_actor` is a property, so the debugger
  commands and `get_exit_message()` that read them resolve.

- `fictive/bedrock_runtime.py`
  `BedrockRuntime`, a `Runtime` subclass that installs a Bedrock-backed
  pipeline on the interpreter's actors and exposes every scenario command as a
  named Python method. `pipeline=` takes a pre-built pipeline, so a host or a
  test can supply its own and never reach AWS; otherwise it builds a
  `BedrockPipeline`, which itself makes no network call until first used.
  `install_pipeline` sets both `actor.pipeline` and `actor.cfg.pipeline`,
  because `Actor.__init__` prefers `cfg.pipeline` and an actor rebuilt from its
  config would otherwise lose the backend. Four commands are not `cmd_exec`
  wrappers, because driving them that way is silently wrong: `exit` performs
  the unwind itself (`exec_EXIT` is a no-op in the interpreter), `cond` only
  queues so `drain_pending()` runs what it queued and `evaluate(condition)` is
  the imperative alternative, and `loop` rewinds a step pointer that nothing
  increments on this path. Every parameter is a dataclass field name with
  underscores, since `cmd_exec` bypasses `Cmd.normalize_params`.

- `fictive/session.py`
  Saves and restores a whole interpreter session as one JSON file
  (`"format": "fictive-session"`, `"version": 1`).
  - What a file holds: every actor's `Actor.state_dict()` (unmerged history,
    system prompt, `cur_step`, pending `cond` block, `return_after_pending`,
    plus subclass state such as `Scorer.scores`). It also holds the shared
    store, the waiting store, the callstack, and `Interpreter.rag_sessions`.
  - What it leaves out: instructions and pipelines, which come from the
    scenario. `restore_interpreter` requires the file's actor names to equal
    the interpreter's. It restores all or nothing, putting the previous state
    back if any actor rejects its saved state.
  - `command_to_dict` is the inverse of `parse_command_dict`, including the
    commands nested in `cond` branches, so pending blocks survive a round trip.
  - `write_session_file` writes atomically and has no `default=str`: a store
    value that is not JSON-serializable raises `TypeError` naming the variable,
    rather than loading back as its string form.
  - Default location: `<storage_dir>/conversations/<session_id>.json`. A session
    id must be one plain path segment (`validate_session_id`).
  - `render_transcript` turns a saved history into the plain text the local RAG
    backend indexes.

- `fictive/rag/`
  Backends for the `rag-generate` command. Neither backend module is imported
  until one is built, so importing `fictive` never imports `boto3` or
  `llama_index`. The package reads `os.environ` but never loads a `.env` file.
  - `rag/__init__.py`: `RetrievedPassage`, `RagResult`, and the `RagBackend`
    protocol (`generates_natively`, `retrieve`, `retrieve_and_generate`). Also
    backend selection: `backend_kind(override)` returns `bedrock` when
    `KNOWLEDGE_BASE_ID` is set and `local` otherwise, and `build_rag_backend`
    builds one. It also holds the helpers that format passages into the
    default enclosing prompt.
  - `rag/bedrock.py`: `BedrockKnowledgeBaseBackend`, over boto3's
    `bedrock-agent-runtime` client. `retrieve_and_generate` calls
    `RetrieveAndGenerate` with `KNOWLEDGE_BASE_ID` and `BEDROCK_MODEL_ARN` (or
    the command's `model-arn`), passes the actor's system prompt as the
    generation prompt template, reuses a per-actor `sessionId`, and maps
    citations to passages. It only queries the Knowledge Base; loading data
    into it happens outside fictive. `native_generation=False` makes it
    retrieve-only, through `Retrieve`, with the actor's pipeline generating.
  - `rag/local.py`: `LlamaIndexConversationBackend`. It holds one LlamaIndex
    document per (session file, actor) transcript, plus one per
    host-supplied `document_paths` file, persisted in
    `<conversations dir>/.rag_index/`. `actors` limits which transcripts are
    indexed, `transcript_renderer` replaces
    `fictive.session.render_transcript`, and `max_reference_passages` caps how
    many results come from reference documents, leaving the rest to
    conversations. `sync()` runs before every retrieval: it
    re-embeds changed documents through `refresh_ref_docs` and deletes those
    whose file is gone. Embeddings come from the Hugging Face model
    `FICTIVE_RAG_EMBED_MODEL` (default `BAAI/bge-small-en-v1.5`). The current
    session is excluded with a metadata filter.

`fictive/pipelines/` holds model backends that plug into an actor as its
pipeline. The backend module is imported lazily, so importing `fictive` never
imports the SDK's Bedrock client.

- `pipelines/__init__.py`: the env-var names, the defaults, and
  `build_bedrock_pipeline(...)`. `BEDROCK_MODEL_ID` (default
  `us.anthropic.claude-sonnet-4-6`), `BEDROCK_REGION`, `BEDROCK_PROFILE`,
  `BEDROCK_MAX_TOKENS` (default 16384) and `BEDROCK_THINKING_BUDGET`.
- `pipelines/bedrock.py`: `BedrockPipeline`, Claude on Amazon Bedrock through
  `anthropic.AnthropicBedrock`, shaped like an `llm_utils` pipeline
  (`model_name`, `generate`, `generate_stream`) without subclassing
  `LLMPipeline` -- `PipelineConfig` has no field for a region, a profile or an
  inference profile id. `bedrock_request_messages` splits `role: "system"`
  history entries into the Messages API's `system` field, drops empty turns,
  and adds a `Continue.` user turn when a history ends on an assistant message,
  which current Claude models reject; an actor reaches that shape whenever
  `input-from` writes only to the store between two `generate`s. Both methods
  stream, so a long answer does not run into an HTTP timeout. The AWS client is
  a lazy property, so the class imports and constructs with no credentials. The
  model id must be an inference profile (`us.anthropic.claude-sonnet-4-6`), not
  a bare model id, and the geography prefix is region-family specific.

`fictive/websearch/` holds the `web-search-and-generate` backends, imported
lazily for the same reason.

- `websearch/__init__.py`: the `WebSearchBackend` protocol (`search(query,
  max_results, filters)`), `backend_kind` / `build_web_search_backend`, the
  default enclosing prompt, and the connector's limits (200-character queries,
  1 to 25 results). Results are `fictive.rag.RetrievedPassage`, so this command
  and `rag-generate` share one result shape, one `sources-store` shape and one
  context-wrapping path.
- `websearch/agentcore.py`: `AgentCoreGatewayBackend`, a minimal SigV4-signed
  MCP client for a Bedrock AgentCore Gateway fronting the AWS-managed Web
  Search connector. The gateway URL comes from `WEBSEARCH_GATEWAY_URL` or the
  `GatewayUrl` output of the stack named by `WEBSEARCH_GATEWAY_STACK`; region
  and credentials from `WEBSEARCH_REGION` / `WEBSEARCH_PROFILE`, else boto3's
  chain. The endpoint is the gateway URL plus `/mcp`: posting to the bare host
  answers HTTP 200 with an `UnknownOperationException` body, so `_rpc` also
  rejects any 200 whose body is not JSON-RPC. `connect()` runs the handshake
  and discovers the `<target>___WebSearch` tool; `search()` connects on first
  use, so building a backend does no network I/O. One instance holds an MCP
  session id and a request counter and is not thread-safe.

- `fictive/library_runtime.py`
  The library runtime: `Runtime` wraps an `Interpreter` so host Python code can
  issue scene-language commands one at a time with
  `Runtime.cmd_exec("<command>", **fields)` instead of handing the interpreter
  a JSON instruction list. Keyword arguments are the command dataclass fields
  from `fictive/parser/commands.py`, spelled with underscores (`var_name`,
  `request_limit`, `input_from_actor`), and paths are taken as given rather
  than resolved against a scenario directory, so pass full paths for prompt
  files.

  Control flow that `loop` and `cond` express in JSON is ordinary Python here.
  Control flow *between* actors still goes through the interpreter: a
  `run-actor` command pushes the callee and makes it the working actor, and the
  matching `exit` pops it again and fills that `run-actor`'s `store` variable
  with the callee's last output. Actors built for this runtime are created
  without `instructions` or `source_file`, so their instruction list is empty.

  Every example under `examples/` is driven this way.

### Package: `fictive/parser/`

- `fictive/parser/__init__.py`
  Marks `parser/` as an explicit Python subpackage and re-exports the main
  parser helpers used by the rest of the package.

- `fictive/parser/commands.py`
  Defines the command enum and the dataclass-backed command objects consumed by
  actors and the interpreter, including the scene-language `write` command for
  file output and the bounded `agent` command, plus `save-conversation`,
  `load-conversation`, `rag-generate` and `web-search-and-generate`.
  `Cmd.from_name`, used by `parse_command_dict` and `Runtime.cmd_exec`, accepts
  `_` for `-` in command names, so `rag_generate` is `rag-generate`, and a
  `Cmd._missing_` hook resolves any remaining separator style or case, so
  `webSearchAndGenerate` is `web-search-and-generate` and `printLatest` is
  `print-latest`. Resolution only: the member's value, and so the `name` on its
  dataclass, stays canonical, which is what `exec_map` and saved sessions use.
  `_missing_` runs only after an exact-value match fails, so the canonical path
  is unaffected.

- `fictive/parser/expressions.py`
  Expression helpers for the scenario language.

## How The Pieces Fit Together

There are two ways to run a scene. The JSON runtime reads a scenario directory
and walks each actor's instruction list; the library runtime
(`fictive/library_runtime.py`) lets host Python code issue the same commands
directly. The examples under `examples/` use the library runtime; the scenario
JSON they ship alongside it is the same flow written for the JSON runtime.

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

The library-runtime flow replaces steps 1, 4 and 6:

1. Build a pipeline as above.
2. Build `Actor` instances directly, with neither `instructions` nor
   `source_file`. No `schema.json` or per-actor JSON is needed; prompt files
   are referenced by full path.
3. Pass the actors into `Interpreter`, wrap it in
   `Runtime(interpreter, start_actor_name=...)`, and issue commands with
   `runtime.cmd_exec(...)`. Loops and conditions are written in Python;
   `run-actor`/`exit` still move control between actors through the
   interpreter's call stack.

`Runtime(..., mode="debug")` stops for a debugger command before each
`cmd_exec` step, using the same command set `fictive/debugger.py` exposes for
the JSON runtime.

The concrete LLM backend classes are provided by
`llm-utils/llm_utils/pipelines.py`. The `fictive` package uses those shared
pipeline definitions directly. `fictive/pipelines/` adds backends of its own
that answer the same duck-typed contract without subclassing `LLMPipeline`;
`BedrockRuntime` builds one and installs it on the actors, so steps 2 and 3
above are replaced by constructing the runtime.

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

Sessions and retrieval-augmented generation:

1. `save-conversation` (or `Interpreter.save_session`) writes the whole session
   to `<storage_dir>/conversations/<session_id>.json`.
2. `load-conversation` (or `Interpreter.load_session`) restores one into an
   interpreter built from the same scenario.
3. `rag-generate` picks a backend. With `KNOWLEDGE_BASE_ID` set, it calls
   Bedrock's `RetrieveAndGenerate` against that Knowledge Base, using
   `BEDROCK_MODEL_ARN`. Otherwise the local LlamaIndex backend brings
   `conversations/.rag_index/` up to date with the saved session files,
   retrieves from sessions other than the current one, and the actor's
   pipeline generates.

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
filesystem work through the `agent` command. It can also save and reload a
whole session with `save-conversation` / `load-conversation`, and generate
from relevant past conversations with `rag-generate`.

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

### Checking the AWS backends by hand

The Bedrock pipeline and the AgentCore web search backend need live AWS, so
they are not part of `unittest discover`. Both are built lazily, so everything
except the calls themselves can be exercised offline by passing a fake:
`BedrockRuntime(interpreter, name, pipeline=<fake>)` and
`Interpreter(web_search_backend=<fake>)` reach no AWS at all.

For a live check, set the environment and exercise the pieces in order, so a
failure names the layer it came from:

```bash
export AWS_PROFILE=... AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
export WEBSEARCH_GATEWAY_STACK=<the gateway's CloudFormation stack>
```

1. `BedrockPipeline().generate([...])` with a system turn, then
   `generate_stream(...)` -- expect delta events and exactly one `done`. A
   `ValidationException` on the model id means the inference-profile prefix is
   wrong for the region.
2. `AgentCoreGatewayBackend().connect()` then `.search(...)`. "Gateway exposed
   no tools" means the web-search target is not `READY`; a 403 means SigV4 or
   the gateway's IAM authorizer; an `UnknownOperationException` under HTTP 200
   means the `/mcp` suffix was lost.
3. A `BedrockRuntime` end to end, then assert the history invariant:
   `actor.history.read(merged=False)` must hold the prompt unwrapped and no
   search text. If the enclosing prompt appears in stored history, the handler
   mutated the stored messages instead of the `read()` copy.

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

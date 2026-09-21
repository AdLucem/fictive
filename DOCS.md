# fictive
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

- `ui/`
  React (Vite + TypeScript) chat front end for a scenario, served by
  `fictive/web/`. The main actor's generations are the conversation; every
  actor a scenario calls appears inline as an expandable bar, one per
  `run-actor` frame on the interpreter callstack, nested to five levels and
  counted by name below that. `ui/README.md` documents the two-process
  development setup and the endpoints the app calls. `npm run build` writes
  `ui/dist`, which the backend serves at `/` when it exists, so one process can
  serve both. Node dependencies are not part of the Python install.

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

  This module and `fictive/library_runtime.py` both import `transformers`
  inside a `try/except ImportError`, because they use it for nothing but
  quietening its own logger. `transformers` stays in `requirements.txt` --
  `TransformersPipeline` needs it for local inference -- but an API-only
  install can now import either entry module without it.

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

`fictive/web/` is the optional HTTP backend behind `ui/`. It is imported only
when the server runs, so it adds no import cost to the library, and its
dependencies (`fastapi`, `uvicorn`) live in the `ui-server` extra rather than
in `requirements.txt`.

- `web/chat.py`
  `ScenarioSpec` loads a scenario directory once and reads `main_actor` and
  `actor_types` out of `schema.json` -- the loader returns the schema as-is, so
  the host still decides which `Actor` subclass each name is built with.
  `ChatSession` is `run.run_chat` with two changes and no others: it advances
  the same `DebuggerSession` with `Interpreter.exec_current()` until the same
  exit checks fire, and because an HTTP request cannot block on stdin, it stops
  *before* an `input-from` that wants a human answer instead of blocking inside
  `Actor.prompt_user`. The answer arrives later through `send_input`, and
  `prompt_user` -- overridden per instance, so a `Scorer` stays a `Scorer` --
  reads it from the session.

  While stepping, it records each step into the nested tree the UI draws: a
  `run-actor` opens a `FlowNode` at its callstack depth, the callstack
  shrinking closes it and reads the callee's return value out of the store, and
  a `generate` by the main actor becomes a message rather than a step.
  Generated text is read off raw history, not `get_latest_output()`, because a
  `Generator` returns its whole scene from that and a `Scorer` returns a
  number. Streaming would go through `Interpreter.on_generate_delta`, which
  reaches the pipeline's `generate_stream`; the `llm_utils` pipelines do not
  define one, so the hook is set only for a pipeline that has it.

- `web/app.py`
  `create_app(...)` builds the FastAPI app around one scenario and one
  pipeline, and `main()` runs it under uvicorn
  (`python -m fictive.web --scenario ... --pipeline-type mock`). Routes:
  `GET /api/health`, `GET /api/scenario`, `GET /api/sessions` (live runs plus
  session files found in the storage directory), `POST /api/sessions` (start a
  run, or resume one with `load_session_id`), `GET /api/sessions/{id}`,
  `POST /api/sessions/{id}/messages` (one reader turn, run to the next input
  request), and `POST /api/sessions/{id}/save`. A turn is synchronous: the
  response carries the whole updated tree, nested callees included. A built
  `ui/dist` is mounted at `/` when present.

  `--pipeline-type` takes any type `llm_utils.pipeline_from_config` builds,
  `openai` included, so an OpenAI-compatible endpoint such as OpenRouter is
  reached with `--pipeline-type openai --model <provider/model>`. `--token` and
  `--base-url` are unset by default and exist only to override: each pipeline
  resolves its own credentials, so a key meant for one provider is never handed
  to another. The anthropic SDK reads `ANTHROPIC_API_KEY`, and the
  openai-compatible path reads `OPENAI_API_KEY` or `OPENROUTER_API_KEY` (with
  `OPENAI_BASE_URL` / `OPENROUTER_BASE_URL`) from the environment or a `.env`
  in the working directory, which is why no key need appear on the command
  line.

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

  `Runtime` also carries the pieces a non-terminal host needs: `cmd_exec`
  accepts `_` for `-` in command names, `save_session(...)` / `load_session(...)`
  delegate to the interpreter (after a load, `working_actor` becomes the top of
  the restored callstack), `main_actor_name` comes from the interpreter and
  `main_actor` is a property, so the debugger commands and `get_exit_message()`
  that read them resolve. `InputRequest` plus `ask` let a scenario written as a
  generator suspend at exactly the points that need a human answer and resume
  through `generator.send(...)`, and `call_actor` is `run-actor` plus the
  callee's steps plus the callstack unwind as one Python call.

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

Chat mode over HTTP (`fictive/web/`, driving `ui/`) is the same flow as
`run_chat` with the human turn moved off stdin:

1. The host builds one pipeline and one `ScenarioSpec`, and each session builds
   its own actors and `Interpreter` from that spec.
2. `ChatSession.advance()` steps `exec_current()` until `DebuggerSession`
   reports an exit or the next instruction is an `input-from` wanting a human
   answer, and the request returns at that point.
3. `POST /api/sessions/{id}/messages` queues the answer and advances again, so
   one request runs the reader's turn plus every actor that turn calls.
4. Each step is recorded at its callstack depth, which is what makes a called
   actor's flow drawable inside the caller's.

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


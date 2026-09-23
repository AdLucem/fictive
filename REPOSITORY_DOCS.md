# `fictive` Repository Docs

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
  `fictive/web/`. The main actor's visible generations are the conversation;
  every actor a flow calls appears inline as an expandable bar, one per
  `run-actor` frame on the interpreter callstack, nested to five levels and
  counted by name below that. Hovering a reader message reveals `Rewrite` and
  `Fork` (`ui/src/components/ReaderMessage.tsx`), offered on the messages named
  in the session's `branch_points`. Each row in the session rail carries a
  delete control that asks once in the row itself
  (`ui/src/components/SessionsRail.tsx`). `ui/src/components/WaitTimer.tsx` is
  the top bar's countdown for `wait` mode, with a clock symbol that hides and
  re-shows it; it ticks client-side off the seconds-remaining reading each
  response carries, because the front end neither polls nor streams. `ui/README.md` documents the two-process
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
  `cond`, `wait`, and `print`. Conditional branches queue nested command blocks,
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
  Wait mode: `wait_until` (a `time.monotonic()` deadline) and `wait_seconds`,
  with `start_wait` / `clear_wait` and the computed `wait_remaining` /
  `wait_active`. `exec_WAIT` only records the deadline, so the command does not
  block and the next instruction runs at once. Nothing has to end a wait:
  `wait_active` is derived from the clock on every read, which is why there is
  no timer thread, no callback and no expiry bookkeeping anywhere. `monotonic`
  rather than `time()` so a system clock adjustment cannot cut a wait short or
  extend it. They are named `wait_*` rather than `waiting` because
  `waiting_store` sits beside them and is unrelated. Nothing persists it: see
  `fictive/session.py`, which holds no wait state.

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

It runs *library-runtime* scenarios: Python flows, not JSON instruction lists.
A flow is already suspendable at exactly the points that need a human answer,
which is what an HTTP host needs, so there is no stepping loop here and no
`DebuggerSession`: the backend parks the flow generator between requests, the
way `drive_flow`'s docstring describes for a host that must not block.

- `web/scenario.py`
  `RuntimeScenarioSpec` imports one scenario module and validates its contract.
  `--scenario` resolves to a `.py` file, or to `fictive_scenario.py` inside a
  directory. Required: `MAIN_ACTOR`, `flow(runtime)`, and either `ACTOR_TYPES`
  (name -> type, `None` for a plain `Actor`) or `ACTOR_NAMES`. Optional: `NAME`,
  `register_commands(runtime)`, `resume_flow(runtime)`. `build_actors` builds
  each actor with `actor_from_config` and no `instructions`, which is a
  library-runtime actor's correct starting state, so `schema.json` and
  `parse_scenario_config` are not involved at all.

  The module's own directory goes on `sys.path` before `exec_module`, because
  scenario packages in this repository import their siblings flat (`from config
  import ...`) -- they are run as scripts, not installed. The cost is that those
  flat names land in the global `sys.modules`, so one process serves one
  scenario: two would collide on `config`. That is why `create_app` builds a
  single spec at startup and never swaps it.

- `web/tree.py`
  The transcript: `FlowNode` (one called actor, an expandable bar), `StepNode`
  (one command), `MessageNode` (a turn in the chat), and `TranscriptRecorder`,
  which owns the tree, the open-frame stack and a per-actor command count. It
  imports no `Interpreter` -- `close_flow` reads a frame's store variable
  through an injected callable -- so `WebRuntime` can own one and the session can
  read it without a cycle. Every mutation and `to_json()` hold one `RLock`, so a
  `GET` cannot serialize a half-built node list, and the lock is never held
  across a model call.

  A `StepNode` carries `detail` (a one-line label) and `detail_text` (the whole
  text the command was handed, capped at `DETAIL_TEXT_LIMIT`). The second is
  filled only for `DETAILED_COMMANDS` -- `system` and `input-from` -- where a
  file name says nothing about what the actor got. `new_history_text` reads it
  back off history and is deliberately role-agnostic where `new_assistant_text`
  is not: `input-from` appends its resolved input as a user turn, but an actor's
  latest output arrives as a dict carrying its own role, which
  `append_to_history` keeps.

  `new_assistant_text(actor, history_before)` is the one correct reader for a
  command's output: it diffs unmerged history around the command, so it returns
  `None` when the command generated nothing (a `system` is never mislabelled as
  the previous generation's text) and it survives `Scorer.generate`'s
  remove-and-regenerate loop. `get_latest_output()` would be wrong -- a
  `Generator` returns its whole scene from it and a `Scorer` a number.

  Branching: `mark()` reads the length of the top-level turn list (plus the
  per-actor counts) as one pair, `truncate` cuts back to a mark for a rewrite in
  place, and `prefix`/`adopt` hand a deep copy of a transcript prefix to a second
  recorder for a fork. A length rather than a node's `seq` is the only reading of
  "before this turn" that stays correct when the turn that followed recorded
  nothing at all. `truncate` deliberately does not rewind the seq counter, and
  `adopt` moves the counter past everything it inherited, so no UI keyed on `seq`
  can confuse a replayed turn with the one it replaced.

  `_TeeStdout` / `install_tee()` capture what a command printed. Several
  commands report what they did by printing (`exec_PRINT`, `exec_PRINT_LATEST`),
  as does `ask`'s slash-command error path and any plain Python a scenario runs
  between commands. `contextlib.redirect_stdout` cannot be used: it swaps the
  global `sys.stdout`, and FastAPI runs `def` handlers in a threadpool, so two
  sessions would cross-capture and restore out of order. One tee with a
  thread-local sink gives each thread its own buffer and still writes through,
  so uvicorn's logging is unaffected. stderr is deliberately not teed --
  `Interpreter.exec`'s `traceback.print_exc()` belongs in the terminal.

- `web/chat.py`
  `WebRuntime` is a `Runtime` that records every command into a
  `TranscriptRecorder`. The hook is **`cmd_exec`, not `cmd`**: `cmd` is only
  trace bookkeeping in front of `cmd_exec`, and a scenario may call `cmd_exec`
  directly (the `examples/evil_AI` flows do). `Runtime.trace_hook` is no use
  either -- it fires *before* the command runs, so it cannot carry what the
  command produced. `mode` is hardcoded to `"chat"`, since `debug_pause` holds
  at a `debug> ` prompt on stdin before every command.

  Four `Runtime` methods reach past the interpreter and so have hooks of their
  own. `deliver` records the reader's turn, carrying the raw answer rather than
  the `enclosing_prompt`-wrapped text, and needs a hook because a human answer
  never passes through `cmd_exec` at all. `return_from` closes the frame; it
  runs inside `call_actor`'s `finally`, so it also sees an exception on its way
  out and marks the frame `failed`, naming the exception actually propagating
  (a pure-Python failure never reached `cmd_exec`, so this is the only place its
  cause is visible). It also has to swallow one specific follow-on error:
  `unwind_actor` calls `fill_variable`, and `Actor.get_latest_output` *raises*
  for a callee that produced no assistant or system message, which inside that
  `finally` would replace the real exception. `append` and `load_session` have
  hooks too; `store_set` deliberately does not, because the store is re-read
  whole on every response.

  Depth comes off the recorder's open-frame stack, not the callstack, because
  `Interpreter.unwind_actor` silently no-ops when the name it is given is not on
  top, so the two can drift; `reconcile` puts them back in step after every
  unwind. A `run-actor` opens a frame and is never also a step. A `generate`
  marked `visible=True` by the main actor at depth 0 becomes a `MessageNode`;
  everything else is a `StepNode`. A scenario that shows its replies with
  `show_latest()` and never marks one visible still gets a conversation, through
  a narrow `print-latest` fallback guarded on `last_visible` so it can never
  double up; conversely, output that merely repeats the visible generation --
  what a flow prints for the benefit of a terminal reader -- is dropped rather
  than shown twice.

  `RuntimeChatSession` holds the parked generator. `start()` runs `next(flow)`,
  `send_input` runs `flow.send(text)`, and `_pump` is the one place a flow is
  resumed, so every way a flow can end is handled once: a yielded
  `InputRequest` parks it, `StopIteration` and `CommandExit` finish it,
  `CommandRestart` (what a `/load` handler raises, and which `ask` re-raises
  rather than swallowing) replaces the generator, and anything else is an error
  that kills it -- a generator that has raised out cannot be resumed.
  `MAX_COMMANDS_PER_TURN` (400) is checked in `cmd_exec` before dispatch and
  raises `TurnBudgetExceeded`, because a generator has no equivalent of the JSON
  path's step cap and a flow that never yields would hold the request open
  forever. It does not cover a single hung pipeline call, nor a pure-Python
  `while True` that issues no commands. Each actor's `prompt_user` is rebound
  per instance (so a `Scorer` stays a `Scorer`) to *raise*, naming `ask`: the
  only way to reach it is an `input-from` carrying a `human_prompt`, which
  belongs to the JSON runtime. A non-blocking per-session turn lock answers a
  concurrent turn with `SessionBusy` rather than queueing it, since a queued
  turn would deliver the reader's message into a request the UI never made.

  Rewriting and forking are built on `Checkpoint`: the state
  `snapshot_interpreter` produces, held in memory rather than written to a file,
  paired with a `TranscriptRecorder.mark()` read at the same moment. One is taken
  each time the flow parks at a request the main actor makes at depth 0 -- the
  only request whose answer becomes a `MessageNode`, and so the only one a
  rewrite could name; a mid-frame `ask` is a sub-flow's own question with a
  half-built frame and no boundary in the tree to cut at. It is committed only
  once the turn has produced the message it stands in front of, which is what
  keeps a slash command (`ask` runs the handler and loops back to the same
  `yield`, delivering nothing) from leaving a checkpoint pointing at nothing.
  `snapshot_interpreter`'s actor states are deep copies and `load_state_dict`
  deep-copies on the way back in, so one checkpoint restores any number of times
  -- which is what lets the same message be rewritten repeatedly.

  `rewrite(message_seq, text)` restores in place and drops that checkpoint and
  every later one; `fork_from(source, message_seq, text)` restores a *second*
  session from another's checkpoint and adopts a copy of its transcript prefix,
  leaving the source untouched. Both then go through `_start_replayed_flow`,
  which is `resume`'s move: a flow cannot be rewound, so the old generator is
  discarded and a fresh one is run up to its own `ask` against the restored
  state. `reset_for_replay` is the state normalization all three paths share
  (callstack back to the main actor, waiting store cleared, `RESUMED_STORE_KEY`
  set) -- factored out of `load_session`, which now also rebuilds the transcript.
  A rewrite is allowed whatever the session's status, because rewriting the
  message that broke a flow is the way out of a failed session and the flow is
  replaced either way; both take the same non-blocking turn lock as
  `send_input`, so neither can interleave with a running turn.
  `MAX_CHECKPOINTS` (50) bounds the memory, since a checkpoint per message
  otherwise grows with the square of the conversation; past it the oldest
  messages simply stop being rewritable, which `branch_points` reports.

  `cmd_exec` drops a `system` step that changed neither the system prompt nor
  the history. Replaying a flow -- what resuming, rewriting and forking all do --
  re-issues the flow's opening `system` against an actor that already holds that
  prompt, and `set_system_prompt` leaves a non-empty history alone, so nothing
  happened; recorded, it would show as a stray `system` in mid-conversation.

  `_detail_text` reads what a `system` or an `input-from` was given off the
  actor *after* the command ran -- `actor.system_prompt` for the one, the
  message appended to history (or the store variable that took it instead) for
  the other -- rather than resolving the path a second time here. That is both
  shorter than reimplementing `parse_prompt_object` and more honest: it shows
  the enclosing prompt applied and the store lookup resolved, and a literal
  string needs no special case. Like `_detail`, it never raises.

  `discard()` tears a session down under the same non-blocking turn lock every
  other way of running a turn takes, so a session cannot be deleted out from
  under a request that is mid-generation; it drops the parked generator, the
  checkpoints (a deep copy of every actor's history each, and so the bulk of a
  session's memory) and the transcript, and leaves `status` at `"discarded"`.

  `to_json` reports wait mode as seconds *remaining* rather than as a deadline:
  the browser's clock need not agree with the host's, so the page counts down
  from the reading it was handed instead of from a shared instant.
  `reset_for_replay` clears the wait, because loading, rewriting and forking all
  discard the generator that started it; a replayed flow issues its own.

  Two fields the UI reads are computed rather than passed through.
  `awaiting_input` comes from the pending request, not from the prompt: a
  request marked `content=False` yields `waiting_prompt: null` while the session
  is still waiting, and deriving one from the other would park a session behind
  a disabled composer. `step_pointers` is the per-actor count of commands
  issued, because a library-runtime actor has no instruction list and so no step
  pointer to report.

  Resuming: `WebRuntime.load_session` restores the session, then makes it a
  state a fresh flow can start on -- callstack back to just the main actor, and
  the waiting store cleared, since a save taken inside a called actor would
  otherwise run the new flow against the wrong working actor with every depth
  off by one. It then rebuilds the transcript from the main actor's history,
  filtering `(INSTRUCTIONS: ...)` turns with `data_structures.INSTRUCTIONS_RE`
  the way `History.to_scene` does, and sets `RESUMED_STORE_KEY` so the flow can
  skip its prologue.

  Streaming would go through `Interpreter.on_generate_delta`, which reaches the
  pipeline's `generate_stream`; the `llm_utils` pipelines do not define one, so
  the hook is set only for a pipeline that has it.

- `web/app.py`
  `create_app(...)` builds the FastAPI app around one scenario module and one
  pipeline, and `main()` runs it under uvicorn
  (`python -m fictive.web --scenario examples/evil_AI --pipeline-type mock`).
  Routes are unchanged: `GET /api/health`, `GET /api/scenario`,
  `GET /api/sessions` (live runs plus session files found in the storage
  directory), `POST /api/sessions` (start a run, or resume one with
  `load_session_id`), `GET /api/sessions/{id}`,
  `POST /api/sessions/{id}/messages` (one reader turn, run to the next input
  request, `409` when the session is not waiting or is already running a turn),
  `POST /api/sessions/{id}/rewrite` (`{message_seq, text}`: replace one reader
  message and run on from it, discarding the turns after),
  `POST /api/sessions/{id}/fork` (`{message_seq, text?}`: branch a new session at
  one reader message, leaving the source untouched),
  `POST /api/sessions/{id}/save`, and `DELETE /api/sessions/{id}` (forget a
  session: the live run, its session file, or both -- one route for both because
  the rail shows one row per id, and a file is named for the session that wrote
  it, so no id could name one session's run and another's file). The id is put
  through `validate_session_id` before it is joined to a path, since it arrives
  from the URL and would otherwise follow `..` out of the storage directory; a
  delete answers `409` while a turn is running and `404` when neither a run nor
  a file exists. A turn is synchronous: the response
  carries the whole updated tree, nested callees included. Both branching routes
  answer `404` for a `message_seq` the session holds no checkpoint for and `409`
  while a turn is running; `fork` checks the branch point before it builds a
  session, so a bad request leaves no empty session in the index. A built `ui/dist` is
  mounted at `/` when present. `--scenario` now names a scenario module;
  `DEFAULT_SCENARIO` is `examples/evil_AI`.

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

  `wait(seconds=...)` issues the `wait` command -- named for the command, like
  every other method here -- while `waiting`, `wait_remaining` and
  `wait_seconds` are properties that read *through* to the interpreter rather
  than caching it, so there is one source of truth and `WebRuntime` and
  `BedrockRuntime` inherit the behaviour without an override of their own.

  `Runtime` also carries the pieces a non-terminal host needs: `cmd_exec`
  accepts `_` for `-` in command names, `RESUMED_STORE_KEY` names the store
  variable a host sets before restarting a flow on a restored session (a
  session file holds no flow position), `save_session(...)` / `load_session(...)`
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
  `load-conversation`, `rag-generate`, `web-search-and-generate` and the
  non-blocking `wait`. `WAIT.__post_init__` rejects a `bool` before the range
  check, as `RAG_GENERATE` and `WEB_SEARCH_AND_GENERATE` do, since `True` is an
  `int`.
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

## Scenario Loading Requirements

Rules a scenario directory must satisfy for `fictive/parse_scenario_config.py`
to load it via `--scenario`. These are the *JSON runtime's* rules, used by
`fictive/run.py`'s `run_chat` / `run_debug` / `run_single_actor`. The web
backend does not use them: it loads a Python scenario module instead, whose
contract is described under `fictive/web/scenario.py` above.

1. **Required file: `schema.json`.** The directory must contain exactly this
   file, at its root. It is the only required file at a fixed name/location;
   everything else is named *from* it.
   - `actors` (required): list of actor names; drives per-actor
     definition-file lookup.
   - `main_actor` (optional): the chat actor; defaults to `actors[0]` when
     omitted.
   - `actor_types` (optional): maps an actor name to `"generator"`,
     `"scorer"`, or omits it for a plain `Actor`.
   - `actor_definitions` (optional): overrides the default per-actor file
     path, which is otherwise `<scenario_dir>/<actor>.json`.
   - `names`, `author_intent`, `actor_output_formats`: loaded, but never
     applied by the backend.
   - `main_actor` and `actor_types` are read by the host, not the loader —
     `parse_scenario_config` returns the schema untouched, and the host chooses
     the `Actor` subclass for each name (a map in Python, as
     `examples/evil_AI/config.py` keeps one).

2. **One JSON file per actor.** For each name in `actors`, the loader requires
   `<scenario_dir>/<name>.json` (unless `actor_definitions` overrides the
   path) — a JSON array of command objects. A missing file raises. Field
   names accept `-` or `_` interchangeably (`actor-name` = `actor_name`); see
   `SCENE_CONFIG_LANGUAGE.md` for the full field set.

3. **Prompt file resolution is layout-free.** Any relative string in an actor
   definition that resolves to an existing file — resolved relative to that
   actor's own definition file, not the scenario root — is rewritten to an
   absolute path, so prompt files can live in any subdirectory layout.
   - Silent failure mode: if the resolved path does not exist, the string is
     left unchanged and used as literal prompt text instead of raising.
   - Exceptions: `workspace` on an `agent` command is never path-resolved
     (it is resolved later against the runtime host root); a string shaped
     like `"var:key"` is a store lookup, not a path.

4. **Two extra rules for JSON chat mode** (`run_chat`; the web backend runs
   flows and is not subject to either):
   - The main actor's instruction list must eventually reach an `input-from`
     command with `human_prompt` set (`""` counts, `null` does not) — this is
     where control passes to the human reader. Without one, a turn runs to
     completion or is stopped by the 400-step cap.
   - An actor's instruction list must never end on `run-actor`; end it with
     `exit` instead. The interpreter decides "is this the last instruction?"
     *before* dispatch, so ending on `run-actor` wraps the caller's step
     pointer to 0 and fills its waiting variable early — when the callee
     returns, the caller restarts from step 0 instead of continuing. This is
     why every nested actor in `examples/ui_demo` ends on `exit`.

5. **Display name.** A scenario's display name is its directory's name,
   unless that directory is literally named `scenario`, in which case the
   parent directory's name is used (`examples/ui_demo/scenario` displays as
   `ui_demo`).

6. **Session files live outside the scenario.** Saved/loaded session files
   are written under `--storage-dir`, never inside the scenario directory —
   a scenario directory can be treated as read-only at runtime.

7. **`actor_types: "scorer"` gotcha.** A scorer actor always enforces the
   default `SCORE: [1-5]` output regex, regenerating up to 10 times and then
   raising if the model never matches. `actor_output_formats` in
   `schema.json` is compiled but never reaches the scorer, because
   `actor_from_config` builds `Scorer(cfg)` without passing `output_format`.
   A weak or mock model is thus guaranteed to raise as a scorer — this is why
   `examples/ui_demo` uses a plain `Actor`, not `"scorer"`, for its critic.

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

Chat mode over HTTP (`fictive/web/`, driving `ui/`) is the library-runtime flow
with the driver replaced: `drive_flow` blocks for each answer, and the backend
parks the generator instead.

1. The host builds one pipeline and one `RuntimeScenarioSpec` -- an imported
   scenario module, not a scenario directory. Each session builds its own actors,
   `Interpreter` and `WebRuntime` from that spec, and registers the scenario's
   slash commands.
2. `RuntimeChatSession.start()` calls `next(flow)`, which runs the flow's
   prologue and every command after it until the flow yields an `InputRequest`.
   The request returns at that point.
3. `POST /api/sessions/{id}/messages` calls `flow.send(answer)`, so one request
   runs the reader's turn plus every actor that turn calls, and returns at the
   next `InputRequest`.
4. `WebRuntime` records each command at its open-frame depth, which is what
   makes a called actor's flow drawable inside the caller's. `call_actor`'s
   `run-actor` opens a frame and its unwind closes it.
5. Resuming restores a session and starts the flow again against it, because a
   session file holds no flow position; `RESUMED_STORE_KEY` lets the flow skip
   its prologue.

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
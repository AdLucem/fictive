# Fictive Agent Docs

This file is the condensed architecture reference for the repository.

Before reading a Python source file to understand what a class, module, or
runtime path is doing, first consult `AGENT_DOCS.md`. Only open the underlying
implementation file if `AGENT_DOCS.md` does not provide enough clarity for the
task at hand.

## Standalone Agent Harness

The provider/tool loop lives in the independent `agent-harness/` Python
distribution. It has no imports from Fictive or `llm-utils`. Phase 3 connects
it to Fictive through the provider-neutral contracts in
`fictive/agent_api.py` and the request/trace bridge in
`fictive/agent_integration.py`.

The public `agent_harness` API consists of:

- `AgentProfile` and `AgentPermissions` for trusted provider and policy setup;
- `AgentRequest`, `AgentResult`, and `AgentExecutor` for provider-neutral host
  integration;
- `PydanticAgentExecutor` for bounded synchronous execution;
- `resolve_workspace` for defense-in-depth workspace containment; and
- `ModelBuilder` for custom Pydantic AI providers.

For each run, `PydanticAgentExecutor` resolves the request's relative workspace
beneath its constructor-supplied host root, narrows requested tools against the
profile ceiling, creates a fresh Pydantic AI Harness filesystem toolset, and
passes converted actor history plus the immediate task to the model. Results
contain only ordinary Python values: final text, normalized messages/events,
usage, changed relative paths, status, and a stable run ID. Known credential
values and credential-shaped text are redacted from outputs and traces.

Shell access is rejected in Phase 2. The filesystem capability rejects
traversal and escaping symlinks; profile defaults also deny `.env`, `.git`, key,
credential, and secret paths. Workspace snapshots use metadata rather than file
contents to report side effects.

The Phase 3 interpreter boundary is deliberately structural: Fictive does not
import `agent_harness`. A trusted host constructs an executor and injects it
along with `agent_root`. The interpreter canonicalizes the root and requires it
to equal `executor.workspace_root`; each command can then narrow that grant
with an existing relative `workspace`. The standalone executor independently
resolves that workspace again.

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
- It preserves `workspace` inside an `agent` command as a runtime-relative
  value, even if a same-named path exists beside the scenario. The interpreter
  must resolve this field against its host-provided root.
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
- It initializes the LLM pipeline if a pipeline configuration was supplied.
- It permits no pipeline for agent-only actors; only `generate` requires one
  and raises a clear error if it is absent.

`Actor.generate(prompt=None, on_delta=None)` takes an optional streaming
callback. With `on_delta=None` (the default) it calls `self.pipeline.generate(...)`
exactly as before. When given, it calls `self._run_pipeline(messages, on_delta)`,
which drives `self.pipeline.generate_stream(messages)` instead and invokes
`on_delta(event)` for every non-final event; the final `{"type": "done",
"message": {...}}` event's message is what gets appended to history, so the
resulting history entry is identical either way. A subclass that calls the
pipeline directly instead of going through `generate` (as `RoutingActor` and
`FileLookupActor` do in `centaurus/src/`) should call `self._run_pipeline(...)`
too rather than `self.pipeline.generate(...)`, so it participates in
streaming automatically instead of breaking when a caller passes `on_delta`.

Special actor subclasses live in `fictive/custom_actors.py`:

- `Generator`
  Returns the whole rendered scene as its latest output.

- `Scorer`
  Runs a normal generation, then extracts a numeric score from the assistant
  output and stores that score in `self.scores`. Its `generate(prompt=None,
  on_delta=None)` forwards `on_delta` to every `super().generate(...)` call,
  including regeneration retries when the output doesn't match the expected
  score pattern.

### 4. Command Parsing

Command parsing lives in `fictive/parser/commands.py`.

The key pieces are:

- `Cmd`
  Enum mapping command names such as `system`, `generate`, `input-from`,
  `agent`, `write`, and `cond` to their dataclass implementations.

- Command dataclasses
  Each command has a dataclass like `SYSTEM`, `GENERATE`, `INPUT_FROM`,
  `AGENT`, `RUN_ACTOR`, `ASSIGN`, `WRITE`, `PRINT`, `PRINT_LATEST`, and `COND`.

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
  `exec_GENERATE`, `exec_AGENT`, `exec_INPUT_FROM`, `exec_WRITE`, and
  `exec_COND`.

- `agent_executor` / `agent_root`
  Optional host-injected agent execution boundary. They must be supplied
  together, and their canonical roots must match exactly.

- `on_generate_delta`
  Optional `(actor_name, event) -> None` hook, `None` by default. When set,
  `exec_GENERATE` wraps it to bind the current `actor_name` and passes it as
  `on_delta` to the acting actor's `generate(...)`, so a host embedding the
  interpreter can receive streamed tokens as a `generate` instruction runs
  instead of only once it finishes. No other instruction handler reads this
  attribute.

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

`exec_current` itself is a wrapper around `_exec_current_step`, which does the
steps above, for the two session commands. A `save-conversation` executed in
the step is queued and written after step 4-5's bookkeeping, so the file
resumes on the next instruction. A `load-conversation` sets `_state_restored`,
and the step then returns the restored top of the callstack without advancing
or unwinding anything. Outside `exec_current` (`Runtime.cmd_exec`) a save
writes immediately.

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

- `agent`
  Resolves an optional immediate task, snapshots the actor's full unmerged
  history, and invokes the injected executor with a host-registered profile,
  relative workspace, requested tool subset, and request/tool limits. On
  success it appends the final text exactly once as an assistant message.
  `store` receives final text and `trace-store` receives normalized messages,
  events, usage, changed paths, status, and run ID. A failed result stores its
  requested trace and raises `AgentRunFailed` before the step advances.

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

- `save-conversation`
  Writes the whole session (see "Sessions and RAG" below) to `path`, or by
  default to `conversations/<session-id>.json` under the acting actor's
  storage directory. It optionally stores the path. Inside `exec_current` the
  write waits until the step's bookkeeping is done, so the file resumes after
  this command.

- `load-conversation`
  Replaces the whole session with a saved one, taking a `path` or a
  `session-id`. `exec_current` then skips its step bookkeeping, because the
  step pointers and callstack it would advance were just replaced.

- `rag-generate`
  Retrieves passages from past conversations and appends one assistant
  message. With `KNOWLEDGE_BASE_ID` set, Bedrock's `RetrieveAndGenerate` does
  both retrieval and generation. Otherwise a local LlamaIndex index over saved
  sessions retrieves, and the actor's pipeline generates. In that case the
  passages are wrapped into the pipeline's copy of the last user message only,
  never into history. `store` receives the text and `sources-store` the
  passages.

- `web-search-and-generate`
  Searches the web through a `WebSearchBackend` and appends one assistant
  message generated from the results. The default `agentcore` backend speaks
  MCP to a Bedrock AgentCore Gateway fronting the AWS-managed Web Search
  connector, SigV4-signed for `bedrock-agentcore`; Bedrock has no server-side
  `web_search` tool, which is why the gateway exists. Results are wrapped into
  the pipeline's copy of the last user message only, never into history, the
  same mechanism the retrieval-only `rag-generate` path uses. `store` receives
  the text and `sources-store` the results. `fallback-on-search-error` turns an
  unreachable gateway into a warning and a search-free reply. Also accepted as
  `webSearchAndGenerate`: `Cmd._missing_` resolves any separator style or case,
  so `ragGenerate` and `printLatest` resolve too, while the canonical
  hyphenated name is what `exec_map` and saved sessions use.

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

- Actors delegate to `self.pipeline.generate(...)` (or, via `self._run_pipeline(...)`,
  to `self.pipeline.generate_stream(...)` when a caller wants streamed output)
- Pipeline implementations live in `llm-utils/llm_utils/pipelines.py`
- Agent commands delegate to the injected `AgentExecutor`; its implementation
  lives in the independent `agent-harness/` distribution

The important boundary is:

- scenario language decides what to ask and when
- actor history packages the conversation
- the generation pipeline or injected agent executor performs the model request

### 12. Mental Model

A useful way to think about the architecture is:

- `parse_scenario_config.py`
  Loads scenario files from disk.

- `parser/commands.py`
  Converts JSON command dicts into typed command objects.

- `actors.py`
  Holds instruction state, history, and optional generation-pipeline access.

- `agent_api.py` / `agent_integration.py`
  Define the dependency-free executor boundary and convert between actor state
  and provider-neutral requests/results.

- `interpreter.py`
  Executes one command at a time, manages control flow, and mutates store and
  history.

- `custom_actors.py`
  Specializes how some actors interpret or expose outputs.

- `session.py`
  Serializes and restores whole interpreter sessions.

- `rag/`
  Retrieval backends for `rag-generate`: Bedrock Knowledge Bases, or a local
  LlamaIndex index over saved sessions.

In short:

scenario JSON -> parsed command objects -> actor instruction lists ->
interpreter dispatch -> history/store mutation -> pipeline or agent-executor
calls when needed

### 13. Why `cond` Fits Cleanly

`cond` works well in this architecture because the system already has:

- typed commands
- a shared variable store
- per-actor instruction stepping

The missing piece was only a way to insert a temporary block of commands into
execution. `pending_instructions` provides that mechanism without forcing the
interpreter to rewrite the actor's underlying instruction list.

## Sessions and RAG

`fictive/session.py` owns the session file format (`fictive-session`, version
1):

- A file holds `callstack`, `waiting_store`, `store`, `rag_sessions`, and per
  actor `Actor.state_dict()`: unmerged `history`, `system_prompt`,
  `cur_step`, `pending_instructions` as command dicts, and
  `return_after_pending`, plus subclass extras such as `Scorer.scores`.
- It holds no instructions or pipelines. `restore_interpreter` demands
  identical actor names and restores all or nothing.
- Store values must be JSON-serializable. There is no `default=str`, so a
  value never silently loads back as a string.
- `command_to_dict` inverts `parse_command_dict`, including `cond`'s nested
  commands.
- The default path is `<storage_dir>/conversations/<session_id>.json`.
  `Interpreter.session_id` is generated per interpreter and replaced by
  `load_session`, so repeated saves update one file.

`fictive/rag/` holds the `rag-generate` backends. Both are imported lazily, so
`import fictive` never pulls in `boto3` or `llama_index`. The package reads
`os.environ` only; loading `.env` stays an entry point's job.

- `backend_kind(override)`: the command's `backend` if given, else `bedrock`
  when `KNOWLEDGE_BASE_ID` is set, else `local`.
- `Interpreter(rag_backend=..., conversations_dir=...)`: a host-supplied backend
  wins whenever a command names no `backend`, and `conversations_dir` replaces
  `<storage_dir>/conversations` for session files and the local index
  (`conversations_root`). `rag-generate`'s `query` (literal text, a message
  dict, or `var:`, never a path) and `fallback-on-retrieval-error` are what a
  host builds on; with nothing retrieved, the pipeline gets the conversation
  unwrapped.
- `BedrockKnowledgeBaseBackend` (`generates_natively = True`): one
  `RetrieveAndGenerate` call with `KNOWLEDGE_BASE_ID`, `BEDROCK_MODEL_ARN` or
  `model-arn`, `numberOfResults = top-k`, an `actor` equals-filter when
  `actor-filter` is set, the actor's system prompt as `textPromptTemplate`
  (with `$search_results$`, `$output_format_instructions$` and `$query$`),
  and the actor's saved `sessionId`. Citations become passages. It does not
  see the actor's history and does not stream. Built with
  `native_generation=False` it only retrieves, and the actor's pipeline
  generates, as for the local backend.
- `LlamaIndexConversationBackend` (`generates_natively = False`): one document
  per (session file, actor) transcript, with id `"<session_id>:<actor>"`.
  `document_paths` adds one document per reference file, `actors` limits which
  transcripts are indexed, and `transcript_renderer` replaces
  `render_transcript`, and `max_reference_passages` caps how many results
  come from reference documents. `sync()` refreshes changed documents and deletes
  vanished ones in `<conversations dir>/.rag_index/` before each retrieval. It uses Hugging Face
  embeddings (`FICTIVE_RAG_EMBED_MODEL`), and a `session_id != current`
  metadata filter keeps the running session out.

## Agent Example and Operator Configuration

`examples/agent_filesystem_demo/` is the reference Phase 4 integration:

- `scenario/filesystem_worker.json` contains a normal `agent` command with a
  profile, immediate task, relative workspace, narrowed tools, request/tool
  limits, final-output store key, and trace-store key. It is the JSON runtime's
  version of the flow, kept for reference.
- `main.py` is trusted host code. It selects the provider profile, constructs
  `PydanticAgentExecutor`, injects exactly the same canonical root into the
  interpreter, and creates the actor without a generation pipeline. It drives
  the flow with the library runtime (`fictive.Runtime.cmd_exec`), passing the
  same `agent` fields as keyword arguments (`request_limit`, `tool_call_limit`,
  `store`, `trace_store`), so the executor, workspace containment and trace
  behavior below are exercised identically either way.
- The default provider is a deterministic Pydantic AI `FunctionModel`. It reads
  `notes.txt`, writes `summary.txt`, uses no shell, makes no network request,
  and needs no credentials.
- `--workspace` retains output in a caller-provided existing directory;
  otherwise a temporary workspace is removed after its contents and trace are
  printed.
- `--provider minimax` is opt-in. Required environment variables, `.env`
  handling, live verification, and Docker injection live in
  `MINIMAX_AGENT_SETUP.md`; no credentials belong in scenario JSON.

`SCENE_CONFIG_LANGUAGE.md` is the canonical reference for the scene-facing
command contract. `agent-harness/README.md` is the standalone package API
reference. `AGENT_HARNESS_INTEGRATION_PLAN.md` records design rationale and
phase completion status.

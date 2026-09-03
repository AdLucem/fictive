# Agent Harness Integration Plan

## Goal

Add an `agent` instruction to Fictive that can use an actor's conversation
history to perform bounded agentic work such as reading, searching, editing,
and writing files.

The agent implementation must:

- remain independent of `llm-utils`
- support custom model APIs, including MiniMax through its
  Anthropic-compatible API
- use an established open-source agent harness where practical
- allow the host application to constrain each run to a configured workspace
- keep provider credentials and permission policy outside scenario files
- integrate with Fictive through a small, stable interface

## Recommended Foundation

Use Pydantic AI and Pydantic AI Harness as the implementation foundation.

Pydantic AI supplies:

- the model/tool execution loop
- structured model messages and tool calls
- request and tool-call usage limits
- custom tools and MCP integration
- model-provider abstractions
- synchronous and asynchronous run APIs

Pydantic AI Harness supplies:

- filesystem tools with root containment and symlink checks
- file read, write, edit, list, search, find, create, and inspect operations
- optional shell execution with command and environment controls
- capabilities for approvals, guardrails, context management, planning, and
  longer-running agents

The libraries are MIT-licensed. Pydantic AI Harness is currently versioned as
`0.x`, so its compatible version should be pinned and all direct usage should
be isolated behind the standalone wrapper described below. Phase 1 verified
`pydantic-ai-harness==0.28.1` with
`pydantic-ai-slim[anthropic]==2.37.0` and `anthropic==1.3.0` on Python 3.12.

Alternatives considered:

- OpenHands Software Agent SDK provides a more complete software-engineering
  environment, including persistence and remote sandbox execution. It is a
  better candidate if Fictive later needs a full autonomous coding environment,
  but it is heavier and more opinionated than the embedded instruction needed
  here.
- Hugging Face `smolagents` is lightweight and model-extensible, but its API is
  described as experimental and it does not provide the same ready-made,
  containment-aware filesystem policy.
- MiniMax Mini-Agent has relevant file, shell, skill, and MCP functionality,
  but it is more MiniMax- and CLI-oriented than the reusable embedded API
  required by Fictive.

References:

- [Pydantic AI Harness overview](https://pydantic.dev/docs/ai/harness/)
- [Pydantic AI Harness filesystem capability](https://pydantic.dev/docs/ai/harness/filesystem/)
- [Pydantic AI Harness shell capability](https://pydantic.dev/docs/ai/harness/shell/)
- [Pydantic AI Anthropic provider](https://pydantic.dev/docs/ai/models/anthropic/)
- [Pydantic AI message history](https://pydantic.dev/docs/ai/core-concepts/message-history/)

## Architecture

The dependency direction should remain one-way:

```text
fictive
   |
   | generic AgentExecutor interface
   v
standalone agent-harness library/submodule
   |
   +-- Pydantic AI
   +-- Pydantic AI Harness

llm-utils remains unrelated to the agent path
```

The standalone wrapper should be maintained as its own Python package and Git
repository. During Fictive development, it can be checked out as a nested Git
submodule:

```text
fictive/
  agent-harness/                  # separate Git repository/submodule
    pyproject.toml
    README.md
    agent_harness/
      __init__.py
      config.py
      errors.py
      executor.py
      history.py
      providers.py
      results.py
      workspace.py
    tests/

  fictive/
    agent_api.py                  # stable integration types/protocol
    agent_integration.py          # actor/interpreter bridge
    interpreter.py
    parser/commands.py
```

The upstream Pydantic packages should be installed as pinned Python
dependencies rather than vendored or added as source submodules.

## Responsibility Boundaries

### Standalone agent harness

The standalone package owns:

- construction of Pydantic AI models and agents
- conversion of generic chat messages to Pydantic AI messages
- the Pydantic AI Harness capabilities attached to each run
- model profiles and provider configuration
- workspace policy enforcement
- request and tool-call limits
- structured execution traces and usage reporting
- normalization of Pydantic results into the stable result type used by
  Fictive

It must not import or invoke `llm_utils`.

It should also avoid importing Fictive. Its public API should use its own
dataclasses and ordinary chat-message dictionaries so it remains usable by
other applications.

### Fictive

Fictive owns:

- parsing the `agent` instruction
- resolving instruction prompts through the existing prompt mechanisms
- passing actor history into the harness
- resolving the requested workspace beneath the host-configured root
- selecting a host-registered model profile
- appending the final assistant response to actor history
- placing requested outputs and traces into the interpreter store
- reporting agent execution failures in the context of the acting actor and
  instruction

Fictive must not contain provider-specific response handling or an agent tool
loop.

### Host application

The host application owns:

- the maximum workspace root available to an actor or interpreter
- model profiles, endpoints, credentials, and model names
- the maximum tools and permissions available under each profile
- whether shell access or other high-risk capabilities are allowed
- approval and sandbox policy

Scenario files may select or narrow these settings but may not broaden them.

## Stable Harness API

The wrapper should expose a small provider-neutral interface similar to:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentRequest:
    history: list[dict[str, Any]]
    task: str | None
    workspace: Path
    profile: str
    requested_tools: tuple[str, ...] = ()
    request_limit: int = 20
    tool_call_limit: int = 50
    run_id: str | None = None


@dataclass(frozen=True)
class AgentResult:
    output: str
    status: str
    messages: list[dict[str, Any]]
    events: list[dict[str, Any]]
    usage: dict[str, Any]
    changed_paths: tuple[str, ...]
    run_id: str


class AgentExecutor(Protocol):
    def run(self, request: AgentRequest) -> AgentResult:
        ...
```

The interface intentionally excludes SDK response objects and Pydantic-specific
types. That protects Fictive from provider changes and upstream harness API
changes.

## Model Profiles and Custom APIs

Profiles should be registered in trusted application code rather than scenario
JSON:

```python
profiles = {
    "minimax": AgentProfile(
        provider="anthropic",
        model=os.environ["MINIMAX_MODEL"],
        api_key_env="MINIMAX_API_KEY",
        base_url="https://api.minimax.io/anthropic",
        permissions=AgentPermissions(
            filesystem="workspace-write",
            shell=False,
        ),
    ),
}
```

The wrapper can construct a MiniMax-backed model through Pydantic AI's
Anthropic provider:

```python
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

provider = AnthropicProvider(
    api_key=api_key,
    base_url=profile.base_url,
)

model = AnthropicModel(
    profile.model,
    provider=provider,
)
```

Pydantic AI also accepts a preconstructed Anthropic client when custom headers,
authentication, transport behavior, or retries are required.

The model identifier must remain configuration rather than being hard-coded.
The same wrapper should support Anthropic, MiniMax, OpenAI-compatible services,
or a custom Pydantic AI model without changing the Fictive interpreter.

API keys must never appear in actor definitions, interpreter store values,
agent prompts, execution traces, or scenario files.

## Workspace Model

The host configures the maximum allowed root for agent activity. An `agent`
instruction may request a relative workspace beneath that root.

For example:

```text
host root:           /srv/story-session
requested workspace: .chatlogs
effective workspace: /srv/story-session/.chatlogs
```

The effective workspace must be resolved before creating any tools:

1. Canonicalize the host root to an absolute path.
2. Reject a missing root or a root that is not a directory.
3. Require the instruction's workspace to be relative.
4. Resolve the requested workspace against the host root.
5. Reject it if the resolved path is not the root or one of its descendants.
6. Construct a fresh filesystem capability for that effective workspace and
   run.

The instruction can therefore narrow the accessible area but cannot expand it.

The agent must not be allowed to choose:

- an absolute workspace
- a workspace containing traversal outside the host root
- a different host root
- an endpoint or profile that grants a broader workspace

The default requested workspace should be `.`. In Fictive, the default host
root will normally be `actor.storage_dir`, although the application should be
able to inject a stricter root.

## Filesystem Capability

The initial agent should use Pydantic AI Harness's `FileSystem` capability:

```python
filesystem = FileSystem(
    root_dir=effective_workspace,
    allowed_patterns=["**"],
    denied_patterns=[
        ".env",
        ".env.*",
        ".git/**",
        "**/*.pem",
        "**/*credentials*",
    ],
    max_read_lines=2_000,
    max_list_results=1_000,
    max_search_results=1_000,
    max_find_results=1_000,
)
```

The capability supplies:

- `read_file`
- `write_file`
- `edit_file`
- `list_directory`
- `search_files`
- `find_files`
- `create_directory`
- `file_info`

Its path resolution and containment checks, including symlink handling, should
be the primary filesystem boundary. The wrapper should additionally normalize
all reported changed paths relative to the effective workspace and reject any
out-of-bound path reported by an extension.

Tool output sizes and aggregate model/tool activity must remain bounded.

## Optional Shell and Other Capabilities

Shell access should be disabled by default. A profile may enable it only when
the host application deliberately grants that permission:

```python
Shell(
    cwd=effective_workspace,
    allowed_commands=["rg", "git", "pytest"],
    denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
)
```

A working directory, command allowlist, and environment filtering are useful
controls, but they are not an operating-system security boundary. A process
can potentially address files outside its working directory. Profiles that
permit shell or host code execution should therefore use a container or other
OS-level sandbox with an appropriate mount policy.

The same review applies before enabling:

- code execution
- browser access
- web access
- MCP servers
- Git or source-control mutation tools
- user-defined tools that accept paths

Each capability must be configured against the effective workspace or shown
not to provide filesystem access.

## Permission Narrowing

Each profile defines the maximum tools and permissions available. An `agent`
instruction may request only a subset:

```python
enabled_tools = profile.allowed_tools.intersection(request.requested_tools)
```

Unknown or prohibited tool names should cause a configuration error before a
model request is made. They should not be silently ignored.

In particular:

- a read-only profile cannot be promoted to workspace-write by a scenario
- a filesystem-only profile cannot acquire shell access through `tools`
- a requested subdirectory cannot expand to its parent
- a scenario-selected profile must already be registered and allowed for that
  actor or interpreter

## Actor History Conversion

Fictive's history currently contains simple `role` and `content` dictionaries.
The wrapper's history adapter should convert them to Pydantic AI messages:

- `system` becomes a system prompt part
- `user` becomes a model request containing a user prompt part
- `assistant` becomes a model response containing a text part

System-prompt behavior must be tested explicitly. Pydantic AI treats supplied
message history as an existing conversation and may assume that it already
contains the appropriate system context. The actor's system prompt and harness
safety instructions must be present exactly once.

After execution:

- append only `AgentResult.output` to the actor's normal history
- retain the structured harness transcript separately
- do not insert tool-call and tool-result content blocks into the existing
  Fictive `History`, which currently assumes string content
- make the structured transcript available through `trace-store` or another
  explicit persistence option

## Scene Instruction

The proposed instruction is:

```json
{
  "cmd": "agent",
  "prompt": "Inspect this workspace and update its documentation.",
  "profile": "minimax",
  "workspace": ".chatlogs",
  "tools": [
    "read_file",
    "search_files",
    "find_files",
    "write_file",
    "edit_file"
  ],
  "request-limit": 20,
  "tool-call-limit": 50,
  "store": "agent-result",
  "trace-store": "agent-trace"
}
```

Fields:

- `prompt`: optional immediate task, resolved with the existing Fictive prompt
  rules
- `profile`: name of a host-registered model and permission profile
- `workspace`: optional relative workspace beneath the configured root;
  defaults to `.`
- `tools`: optional subset of the profile's permitted tools
- `request-limit`: maximum model requests for this instruction
- `tool-call-limit`: maximum successfully executed tool calls
- `store`: optional interpreter-store key for the final text
- `trace-store`: optional interpreter-store key for the normalized run trace

The actor's history is always supplied; it does not need a command flag.

## Fictive Integration

### Command parsing

Add an `AGENT` dataclass and `Cmd.AGENT = "agent"` mapping in
`fictive/parser/commands.py`. Hyphenated JSON fields should use the parser's
existing parameter normalization.

### Interpreter construction

Add an optional injected executor and root policy:

```python
Interpreter(
    actors,
    main_actor_name="generator",
    agent_executor=agent_executor,
    agent_root=runtime_root,
)
```

Neither object should be constructed implicitly by the interpreter. Executing
`agent` without a configured executor should raise a clear configuration error.

### Command execution

`exec_AGENT` should:

1. Fetch the acting actor.
2. Resolve the optional prompt.
3. Determine the host root from interpreter configuration, falling back to the
   actor's storage directory only when that fallback is explicitly supported.
4. Resolve and validate the requested relative workspace beneath that root.
5. Build an `AgentRequest` using a snapshot of actor history.
6. Invoke the injected executor.
7. Append the final text as one assistant message.
8. Populate `store` and `trace-store` if requested.
9. Log the run ID, status, usage, and changed relative paths without logging
   credentials or unredacted secrets.

The entire harness run remains one Fictive interpreter instruction, even when
it performs several model/tool iterations internally.

### Actor construction

Agent-only actors should not need a dummy `LLMPipeline`. The current actor
constructor requires a pipeline unconditionally. It should be relaxed so that:

- an actor may be constructed with no generation pipeline
- `generate` continues to raise a clear error when called without one
- `agent` depends only on the interpreter's injected agent executor

For stronger installation independence, imports of `llm_utils` used only for
ordinary generation should eventually be made lazy or isolated behind a
generation adapter. That is a separate compatibility change from the agent
harness itself.

## Error, Retry, and Side-Effect Semantics

The implementation must distinguish model-request retries from whole-run
retries:

- retrying a failed provider request before any tool call is generally safe
- automatically replaying a whole run after writes is not safe
- write and edit tools should use content hashes where possible to detect stale
  state
- every run should have a stable run ID and a structured trace
- failures after side effects must report the paths already changed

The interpreter should not blindly rerun a failed `agent` instruction. The
chosen failure policy should be explicit, for example:

- `raise`: stop interpreter execution and preserve the failure trace
- `continue`: store a failed result and advance to the next instruction

`raise` should be the default during initial implementation.

## Testing Strategy

Prefer extending existing relevant test modules unless a dedicated new test
module is specifically requested.

The standalone wrapper should be tested with Pydantic AI's test model or a
deterministic fake model. Tests should cover:

- history conversion for system, user, and assistant messages
- a no-tool final response
- one and multiple filesystem tool calls
- request and tool-call limits
- provider errors and malformed tool arguments
- read-only and workspace-write profiles
- unknown or prohibited tools
- traversal using `..`
- absolute paths outside the workspace
- symlinked files and directories that escape the workspace
- requested workspace resolution beneath the host root
- rejection of workspace attempts that resolve outside the host root
- isolation between two simultaneous actors with different workspaces
- secret and credential redaction in traces
- changed-path reporting

Fictive integration tests should cover:

- parsing the `agent` command
- prompt resolution
- actor history passed to the executor
- final output appended exactly once
- `store` and `trace-store` behavior
- missing executor and invalid-profile errors
- agent-only actors without a generation pipeline
- interpreter stepping and call-stack behavior after success and failure

A live MiniMax test should be optional and skipped without credentials. The
main suite must not require network access.

## Packaging and Versioning

The standalone package should declare only the dependencies needed for its
agent implementation. The dependency versions verified by the Phase 1 spike
are:

```toml
[project]
name = "agent-harness"
requires-python = ">=3.10"
dependencies = [
    "anthropic==1.3.0",
    "pydantic-ai-harness==0.28.1",
    "pydantic-ai-slim[anthropic]==2.37.0",
]
```

The exact compatible bounds must be validated at implementation time and
recorded in a lockfile. Do not track an unpinned upstream branch in production.

Fictive should either:

- expose agent support as an optional dependency, or
- document installing the standalone package separately

Normal scenarios that never use `agent` should continue to work without
constructing an agent executor.

## Delivery Phases

### Phase 1: Compatibility spike

- Use the caller-provided virtual environment without recreating or clearing
  it.
- Pin and verify the Pydantic AI and Pydantic AI Harness versions.
- Run `compatibility/agent_harness_spike.py` without flags to verify imports,
  arbitrary MiniMax model identifiers, a custom Anthropic `base_url`, and a
  complete local filesystem tool-call loop without network access.
- Run the same script with `--live` to confirm MiniMax text generation and
  client-side tool calling through the Anthropic-compatible endpoint.
- Record any unsupported Anthropic features and disable them in the profile.

Phase 1 implementation status:

- The Python 3.12 compatibility environment resolves and imports the pinned
  stack successfully.
- Offline construction and tool-loop verification is automated.
- Live verification is opt-in because credentials are not available during
  ordinary installation or container builds.

### Phase 2: Standalone wrapper

- Create the independent package repository.
- Implement profile loading and provider construction.
- Implement history conversion.
- Wrap `FileSystem` with workspace resolution and permission narrowing.
- Normalize results, traces, usage, and changed paths.
- Add deterministic fake-model coverage.

Phase 2 implementation status:

- `agent-harness/` is an independent installable distribution with no Fictive
  or `llm-utils` imports. It remains in-tree until a dedicated remote exists,
  at which point it can be converted to a Git submodule without changing its
  public package API.
- Trusted profiles support the built-in Anthropic adapter, Anthropic-compatible
  custom base URLs such as MiniMax, and host-registered model builders.
- History conversion, workspace containment, permission narrowing, bounded
  execution, normalized traces/usage, secret redaction, and changed-path
  reporting are implemented.
- Deterministic fake-model coverage exercises successful and failed runs,
  filesystem boundaries, permissions, limits, and isolated workspaces without
  requiring network credentials.

### Phase 3: Fictive command integration

- Add the `agent` command object and parser registration.
- Inject the executor and host root into the interpreter.
- Implement `exec_AGENT`.
- Relax the unconditional actor pipeline requirement.
- Add store and trace handling.
- Verify interpreter step and call-stack behavior.

Phase 3 implementation status:

- `agent` is registered as a typed command, including hyphenated limit and
  trace fields and nested `cond` parsing.
- `Interpreter` accepts a host-injected executor and canonical root, requires
  their roots to match, and dispatches bounded agent requests without importing
  the standalone harness.
- `exec_AGENT` snapshots unmerged actor history, resolves optional prompts and
  relative workspaces, stores normalized traces, appends successful final text
  exactly once, and raises `AgentRunFailed` for failed results.
- Actors may omit generation pipelines; `generate` reports a clear runtime
  error when no pipeline is configured.
- Deterministic Fictive integration tests cover parsing, prompt/history
  transfer, result storage, workspace escape rejection, invalid profiles,
  missing executors, and step/call-stack state on success and failure.

### Phase 4: Documentation and example

- Document the command in `SCENE_CONFIG_LANGUAGE.md`.
- Update `DOCS.md` and `AGENT_DOCS.md` with the new runtime flow and module
  responsibilities.
- Add a filesystem-only example that uses a fake provider by default.
- Document MiniMax environment variables separately without committing
  credentials.

Phase 4 implementation status:

- `SCENE_CONFIG_LANGUAGE.md` documents every `agent` field, host-controlled
  permission boundaries, workspace containment, history/trace behavior, and
  failure semantics.
- `examples/agent_filesystem_demo/` provides an offline-by-default scenario
  that uses a deterministic Pydantic AI function model to read and write only
  inside the injected workspace. A caller-provided workspace can retain the
  output, and MiniMax remains an explicit opt-in provider.
- `MINIMAX_AGENT_SETUP.md` documents credential, model, endpoint, `.env`, live
  compatibility, and Docker configuration without containing real secrets.
- `DOCS.md`, `AGENT_DOCS.md`, the top-level README, and the standalone harness
  README describe the implemented runtime and operator flow.

### Phase 5: Optional capabilities

- Add human approvals if required by the host interface.
- Evaluate context compaction for long actor histories.
- Add MCP capabilities only with explicit workspace and security review.
- Add shell execution only after choosing an OS-level sandbox strategy.
- Consider durable execution if agent instructions need restart recovery.

## Acceptance Criteria

The initial integration is complete when:

- Fictive parses and executes an `agent` instruction.
- The full actor history is passed into the harness.
- A scenario can request a relative workspace but cannot escape the configured
  host root.
- The agent can read, search, edit, and write within its effective workspace.
- Filesystem traversal and escaping symlinks are rejected.
- MiniMax works through its Anthropic-compatible endpoint without using
  `llm-utils`.
- Provider credentials and endpoints are configured outside scenario files.
- Tools requested by a scenario can only narrow host-granted permissions.
- The final answer is appended to actor history and optionally placed in the
  interpreter store.
- Structured tool history is kept separate from Fictive's string-oriented
  history.
- Agent-only actors do not require a dummy generation pipeline.
- Existing `generate` behavior remains compatible.
- Unit tests run without network credentials.
- Fictive and standalone-package documentation accurately describe the final
  architecture, permissions, limitations, and configuration.

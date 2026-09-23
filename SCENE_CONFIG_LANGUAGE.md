# Scene Config Language

The JSON scenario format: the commands and fields an actor's instruction list
may hold, as walked by `Interpreter.exec_current` under `fictive/run.py`'s
`run_chat`, `run_debug` and `run_single_actor`.

The same commands are available to a library-runtime flow, one method per
command, but the control-flow constructs here (`cond`, `loop`, `exit`) have no
counterpart there -- Python's own `if`, `while` and `return` do that work. The
web backend runs flows only, so nothing on this page describes it; see
`DOCS.md` for the flow API and the scenario-module contract.


## Expressions

```
Atomic -> var:<varname>
        | output:<actorname>
        | file:<filepath>


MathOp -> + |
Expr -> Atomic
      | Expr MathOp Expr
      | Expr BoolOp Expr
      | (Expr)
```

## Commands

### Command: `system`

Set system prompt.

```
Params:
    - prompt: str | Path = "The prompt, either as a prompt string or as a file containing the prompt string."
```

### Command: `generate`

Pass history to pipeline to get text-generation output.

```
Params:
    - prompt: Optional[str | Path] = "If specified, append this prompt to existing history before sending to generator. If not specified, only the history is sent to generator."
```

### Command: `agent`

Run one bounded agent harness invocation using the actor's complete conversation history. The provider, credentials, maximum filesystem permissions, and maximum workspace root are registered by trusted host code; they cannot be configured or widened by a scenario.

```
Parameters:

- `profile`: required string naming a host-registered model and permission profile.
- `prompt`: optional immediate task. It accepts the same literal string, prompt file, message object, and `var:<store-name>` forms as other prompt fields.
- `workspace`: optional existing relative directory beneath the host's configured root. It defaults to `.`. Absolute paths, traversal outside the root, and escaping symlinks are rejected.
- `tools`: optional list that narrows the tools permitted by the selected profile. It cannot enable a tool the host profile did not grant. The current filesystem tools are `read_file`, `list_directory`, `search_files`, `find_files`, `file_info`, `write_file`, `edit_file`, and `create_directory`. Shell access is not supported.
- `request-limit`: optional positive integer limiting model requests. The default is `20`.
- `tool-call-limit`: optional positive integer limiting successful tool calls. The default is `50`.
- `store`: optional shared-store key for the final assistant text.
- `trace-store`: optional shared-store key for the normalized run record,
  including status, messages, tool events, usage, changed relative paths, and
  run ID.

Example:

```json
{
  "cmd": "agent",
  "profile": "workspace-editor",
  "prompt": "Read notes.txt and update summary.txt.",
  "workspace": ".chatlogs",
  "tools": [
    "read_file",
    "write_file"
  ],
  "request-limit": 10,
  "tool-call-limit": 20,
  "store": "agent-answer",
  "trace-store": "agent-trace"
}
```

The actor's history is always supplied as a snapshot and does not need a
command flag. On success, only the final text is appended to actor history, as
one assistant message; structured tool activity remains in the optional trace.
On a failed result, the interpreter stores the requested failure trace, raises
`AgentRunFailed`, and does not advance the instruction or unwind the actor.

The host must construct `Interpreter` with both `agent_executor` and
`agent_root`. Their canonical roots must match exactly. Agent-only actors may
omit an ordinary generation pipeline, but executing `generate` on such an
actor is an error.

See `examples/agent_filesystem_demo/` for an offline runnable configuration.

### Command: `input-from`

Take input from a source: an actor's latest output, a human user, a file, or a
value in the shared interpreter store.


```
Params:

- enclosing_prompt: Optional[str | Path] = "If specified: prompt/prompt variable in store/prompt file to enclose the input within. i.e: the input will either be appended after the prompt, or if `{INPUT_FROM}` placeholder is in the prompt, will be put in place of placeholder.
- store: Optional[str] = "Name of variable inside the shared store in which to store input. If not specified, input will be appended to actor history."
- history: Optional[Bool] = "Input is appended to actor history by default. If `store` argument is given, use this argument to both store the input and also append it to history."

[Input Type: human]
- human-prompt: Optional[str | Path] = "If specified: prompt/prompt variable in store/prompt file to prompt human user with. Note that this takes precedence over `input_from_agent`.

[Input Type: agent]
- input-from-actor: Optional[str] = "Name of the actor to take input from. If not defined, we go to next input type."

[Input Type: file]
- input-from-file: Optional[str | Path] = "Path to the file from which to read input."

[Input Type: store]
- input-from-store: Optional[str] = "Name of the variable in the store from which to read input from."
```

### Command: `run-actor`

Run a single cycle of the given actor (NO LOOPING), and get the output at the end of the cycle.

```
Params:
- `actor-name` : str = "Name of actor for which to run cycle. This raises an exception if the named actor does not exist."
- `start-step` : Optional[int] = 0 ::= "Step number on which to begin actor cycle. By default, begins at the first step i.e: 0."


- store: Optional[str] = "Name of variable inside the shared store in which to store the given actor's output (i.e: last assistant message in actor history). If not specified, output will simply remain in the called actor's history."
```

### Command: `refresh`

Refresh the actor's history i.e: delete everything except (if applicable) system prompt.

### Command: `loop`

Loop around to the beginning of the actor's instructions (or, optionally, loop to given step.)

```
Params:

- step : Optional[int] = 0 ::= "Loop to given step [STEPS START AT 0]. By default, loop around to first step i.e: 0."
```

### Command: `assign`

Assign a variable <var_name> some value <value>.

### Command: `print`

Print some text (or text read from a file) to screen.

```
Params:

- prompt : str | Path = "Text/variable in store/file to read text from, and print the text.
```

### Command: `print-latest`

Print the latest assistant message in an actor's history. If `n` is specified, then print the n'th previous assistant message.

```
Params:

- actor-name: Optional[str] = "Name of actor whose history to print. If not specified, print for calling actor."
- n: Optional[int] = "If specified, print n'th previous message"
```

### Command: `wait`

Enter wait mode for a given number of seconds.

The command does **not** block. It records a deadline and returns, so the very
next command runs immediately while the clock counts down in the background --
there is no sleep, no timer thread and no callback when it ends. Wait mode is
something a flow *reads*, not something that interrupts it.

Wait mode expires on its own: "is a wait still running?" is computed from the
clock each time it is asked, so nothing has to clear it. Issuing a second
`wait` replaces the first, and `seconds: 0` cancels an active wait.

The state is deliberately ephemeral -- it is wall-clock state, not conversation
state, so it is not written to a session file and a restored session starts
with no wait running.

```
Params:

- seconds: float = "Required. How long wait mode lasts. Must be a non-negative number; 0 cancels an active wait."
```

Example:

```json
{
  "cmd": "wait",
  "seconds": 90
}
```

From a library-runtime flow the same command is `runtime.wait(seconds=90)`, and
the state is read back with `runtime.waiting`, `runtime.wait_remaining` and
`runtime.wait_seconds`. See `DOCS.md`.

### Command: `cond`

Conditional i.e: if/else. (works more like a switch/case in practice). Define conditions (including an optional `else` condition), with a block of statements to be executed for each condition.

```
Params:

- `conditions`: List[dict] = "List of branches, listed in order of evaluation. Each branch may define:
    - `condition`: str = Python-style boolean expression evaluated against values in the shared store.
      - Store values are referenced directly by variable name, e.g. `fear > 2 and trust < 3`.
      - A branch with `condition: "else"` (or with no `condition`) acts as the fallback branch.
    - `commands`: List[Command] = Block of commands to queue and execute when the branch matches."
```

Example:

```json
{
  "cmd": "cond",
  "conditions": [
    {
      "condition": "(fear > 2.0) and (trust < 3.0)",
      "commands": [
        {
          "cmd": "assign",
          "name": "next-instructions",
          "value": "Back off the topic for a while to stop scaring the user."
        }
      ]
    },
    {
      "condition": "else",
      "commands": [
        {
          "cmd": "assign",
          "name": "next-instructions",
          "value": "Continue."
        }
      ]
    }
  ]
}
```

### Command: `write`

Write given output to a file. By default, writes the calling actor's latest output to file.


```
Params:

- path : str = "Path of file to write to. If a relative filepath, then it is assumed to be relative to the top-level directory"

- read_from : Optional[str | Path] = "If specified, read input from text/variable in store/file to read text from (refer to earlier implementations of `prompt` to see the types of input you can give), and write the text to the given write path."
- overwrite : Bool = False := specifies whether to overwrite the file with given contents, or append the contents to the existing file

- write_history : Optional[str] = "If specified, write the entire history of the given actor. Use `actor.history.read()` to get the history."
```

### Command: `exit`

Exits the current actor and returns execution to the previous actor in the stack. Takes no commands.

### Command: `save-conversation`

Also accepted as `save_conversation`. Saves the whole interpreter session to
one JSON file:

- every actor's full, unmerged history and system prompt;
- each actor's instruction step and any pending `cond` block;
- the shared store, the deferred `run-actor` captures, and the callstack;
- the Bedrock session id each actor's `rag-generate` calls are using.

Instructions and pipelines are not saved. A session loads only into an
interpreter built from the same scenario, with exactly the same actor names.

When this runs as a scenario step, the file is written once the step has
finished. Loading it therefore resumes at the instruction after the
`save-conversation`, not on it.

```
Params:

- path: Optional[str | Path] = "File to write. A relative path is resolved against the acting actor's storage directory. If omitted, writes `conversations/<session-id>.json` there, or into the interpreter's `conversations_dir` when the host set one."
- session-id: Optional[str] = "Session id recorded in the file and used for the default file name. Defaults to the interpreter's session id, so repeated saves during one run update one file. Letters, digits, `.`, `_` and `-` only."
- store: Optional[str] = "Name of a store variable to receive the path of the written file."
```

Every store value must be JSON-serializable. Otherwise the save raises
`TypeError` naming the variable, rather than writing a value that would load
back as something else.

Example:

```json
{
  "cmd": "save-conversation",
  "store": "session-file"
}
```

From Python, `Interpreter.save_session(path=None, session_id=None)` and
`Runtime.save_session(...)` do the same thing immediately, resolving paths
against the main actor's storage directory.

### Command: `load-conversation`

Also accepted as `load_conversation`. Replaces the whole interpreter session
with one written by `save-conversation`.

```
Params: (exactly one of)

- path: Optional[str | Path] = "Session file to read, resolved like `save-conversation`'s path."
- session-id: Optional[str] = "Load `<session-id>.json` from the interpreter's `conversations_dir`, else from `conversations/` in the acting actor's storage directory."
```

After a load, execution continues from the restored callstack and instruction
steps, not from the instruction after `load-conversation`. Later saves default
to the loaded session id. If the file's actor names do not match the
interpreter's, or an actor rejects its saved state, the load raises and leaves
the session as it was.

Example:

```json
{
  "cmd": "load-conversation",
  "session-id": "20260915T101500Z-3fa9c2d1"
}
```

From Python, use `Interpreter.load_session(path=None, session_id=None)` or
`Runtime.load_session(...)`.

### Command: `rag-generate`

Also accepted as `rag_generate`. Retrieves passages from relevant past
conversations and generates the acting actor's next message from them.

The backend is chosen when the command runs. A host can hand the interpreter a
backend of its own, `Interpreter(rag_backend=...)`, which is used whenever the
command names no `backend`. Otherwise:

- **`bedrock`** is used when `KNOWLEDGE_BASE_ID` is set. It queries that
  Amazon Bedrock Knowledge Base and generates with Bedrock's
  `RetrieveAndGenerate`, using `BEDROCK_MODEL_ARN` or `model-arn`. Region and
  credentials come from boto3's standard chain (`AWS_REGION`, `AWS_PROFILE`,
  ...). fictive only queries the Knowledge Base; loading conversations into its
  data source and syncing it happens outside fictive. Requires
  `pip install 'fictive[rag-bedrock]'`. A host that builds
  `BedrockKnowledgeBaseBackend(native_generation=False)` gets retrieval only,
  and the actor's pipeline generates, as with the local backend.
- **`local`** is used otherwise. It searches a LlamaIndex vector index over the
  session files in the conversations directory (`Interpreter(conversations_dir=...)`,
  else `conversations/` under the acting actor's storage directory), plus any
  reference documents a host-built backend adds,
  then generates with the actor's own pipeline. The index lives in
  `conversations/.rag_index/` and is updated before every retrieval, so a saved
  session is searchable from the next `rag-generate` on. The current session is
  never retrieved from. Embeddings use the Hugging Face model named by
  `FICTIVE_RAG_EMBED_MODEL` (default `BAAI/bge-small-en-v1.5`), downloaded on
  first use. Requires `pip install 'fictive[rag-local]'`.

```
Params:

- prompt: Optional[str | Path | dict] = "Literal text, a prompt file, a message object, or `var:<store-name>`, appended to history as a user message like `generate`'s prompt. It is also the query, unless `query` is given."
- query: Optional[str | dict] = "What to retrieve on: literal text, a message object, or `var:<store-name>`, never read as a file path. Defaults to the prompt, else the latest user message in history."
- top-k: Optional[int] = 4 ::= "Maximum number of passages to retrieve."
- actor-filter: Optional[str] = "Retrieve only from this actor's past transcripts. For Bedrock this is an `equals` metadata filter on `actor`, so the Knowledge Base's documents must carry that metadata."
- enclosing-prompt: Optional[str | Path] = "Local backend only. Wraps the passages (`{CONTEXT}`, required) and the conversation's last user message (`{INPUT}`, or appended after the prompt when absent) for the model. A default is built in."
- backend: Optional[str] = "`bedrock` or `local`, overriding the environment's choice."
- model-arn: Optional[str] = "Bedrock only. Model or inference profile ARN, overriding `BEDROCK_MODEL_ARN`."
- store: Optional[str] = "Name of a store variable to receive the generated text."
- sources-store: Optional[str] = "Name of a store variable to receive the passages, as a list of `{text, score, source, metadata}`."
- fallback-on-retrieval-error: Optional[bool] = false ::= "When retrieval raises -- an index that cannot load, a Knowledge Base that cannot be reached -- log a warning and generate without retrieved context instead of failing. Applies to backends that only retrieve."
```

Both backends append exactly one assistant message to the actor's history.
Retrieved passages are never stored in history. The local backend adds them only
to the copy of the conversation it sends to the pipeline, so history does not
grow with retrieved text on every turn. When nothing is retrieved, that copy is
sent unwrapped, exactly as `generate` would send it.

The backends differ in what the model sees:

- **Local:** the model sees the actor's whole conversation, and the output
  streams through `Interpreter.on_generate_delta` like `generate`.
- **Bedrock:** the model sees the query, the actor's system prompt (sent as the
  generation prompt template) and Bedrock's own session for that actor. It does
  not see the rest of the actor's history, and the output does not stream.

Example:

```json
{
  "cmd": "rag-generate",
  "prompt": "var:teacher-question",
  "top-k": 5,
  "actor-filter": "generator",
  "store": "answer",
  "sources-store": "answer-sources"
}
```

### Command: `web-search-and-generate`

Also accepted as `web_search_and_generate` and `webSearchAndGenerate`. Searches
the web and generates the acting actor's next message from the results.

Command names resolve in any separator style or case, so this is a general rule
rather than a special case for this command: `rag_generate`, `ragGenerate`,
`print-latest` and `printLatest` all resolve too. The canonical name, the one
saved sessions record, stays the hyphenated spelling.

The backend is chosen when the command runs. A host can hand the interpreter a
backend of its own, `Interpreter(web_search_backend=...)`, which is used
whenever the command names no `backend`. Otherwise:

- **`agentcore`** is the default and only built-in backend. It calls an Amazon
  Bedrock AgentCore Gateway fronting the AWS-managed Web Search Tool connector,
  over MCP, signing each request with SigV4 for the `bedrock-agentcore`
  service. The gateway URL comes from `WEBSEARCH_GATEWAY_URL`, or from the
  `GatewayUrl` output of the CloudFormation stack named by
  `WEBSEARCH_GATEWAY_STACK`. Region and credentials come from
  `WEBSEARCH_REGION` and `WEBSEARCH_PROFILE`, else boto3's standard chain
  (`AWS_REGION`, `AWS_PROFILE`, ...). Requires
  `pip install 'fictive[web-search]'`. Creating and deploying the gateway
  happens outside fictive.

Bedrock has no server-side `web_search` tool: it serves Anthropic's client
tools, such as bash and the text editor, but not the server tools that run on
Anthropic's own infrastructure. The gateway is what stands in for one. Note
that this command runs the search itself and puts the results in the prompt; it
does not hand the model a tool to call.

```
Params:

- prompt: Optional[str | Path | dict] = "Literal text, a prompt file, a message object, or `var:<store-name>`, appended to history as a user message like `generate`'s prompt. It is also the search query, unless `query` is given."
- query: Optional[str | dict] = "What to search for: literal text, a message object, or `var:<store-name>`, never read as a file path. Defaults to the prompt, else the latest user message in history. Truncated to 200 characters, the connector's limit, with a warning."
- max-results: Optional[int] = 5 ::= "How many results to ask for, between 1 and 25."
- enclosing-prompt: Optional[str | Path] = "Wraps the results (`{CONTEXT}`, required) and the conversation's last user message (`{INPUT}`, or appended after the prompt when absent) for the model. A default is built in."
- backend: Optional[str] = "`agentcore`, overriding the environment's choice."
- filters: Optional[dict] = "Passed to the connector as its `filters` argument, for per-request domain and published-date filtering."
- store: Optional[str] = "Name of a store variable to receive the generated text."
- sources-store: Optional[str] = "Name of a store variable to receive the results, as a list of `{text, score, source, metadata}`, where `source` is the result URL."
- fallback-on-search-error: Optional[bool] = false ::= "When the search raises -- an unreachable gateway, a missing dependency -- log a warning and generate without web results instead of failing."
```

Exactly one assistant message is appended to the actor's history. Results are
never stored in history: they are added only to the copy of the conversation
sent to the pipeline, so history does not grow with search text on every turn.
The prompt joins history only once the search has returned, so a failed search
leaves the conversation as it was. When nothing is found, the copy is sent
unwrapped, exactly as `generate` would send it. The model sees the actor's whole
conversation, and the output streams through `Interpreter.on_generate_delta`
like `generate`.

Example:

```json
{
  "cmd": "web-search-and-generate",
  "prompt": "var:teacher-question",
  "max-results": 5,
  "store": "answer",
  "sources-store": "answer-sources",
  "fallback-on-search-error": true
}
```

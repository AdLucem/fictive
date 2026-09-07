# Scene Config Language


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

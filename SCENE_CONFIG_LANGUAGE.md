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

### Command: `input-from`

Take input from a source- either an agent (agent.current_output), from user (get user's input) or from an assigned variable in the agent's memory.


```
Params:

- enclosing_prompt: Optional[str | Path] = "If specified: prompt/prompt variable in store/prompt file to enclose the input within. i.e: the input will either be appended after the prompt, or if `{INPUT_FROM}` placeholder is in the prompt, will be put in place of placeholder.
- store: Optional[str] = "Name of variable inside the agent memory in which to store input. If not specified, input will be appended to agent history."
- history: Optional[Bool] = "Input is appended to agent history by default. If `store` argument is given, use this argument to both store the input and also append it to history." 

[Input Type: human]
- human-prompt: Optional[str | Path] = "If specified: prompt/prompt variable in store/prompt file to prompt human user with. Note that this takes precedence over `input_from_agent`.

[Input Type: agent]
- input_from_actor: Optional[str] = "Name of the actor to take input from. If not defined, we go to next input type."

[Input Type: store]
- input_from_store: Optional[str] = "Name of the variable in the store from which to read input from."
```

### Command: `run-agent`

Run a single cycle of the given agent (NO LOOPING), and get the output at the end of the cycle.

```
Params:
- `agent-name` : str = "Name of agent for which to run cycle. This raises an exception if the named agent does not exist."
- `start_step` : Optional[int] = 0 ::= "Step number on which to begin agent cycle. By default, begins at the first step i.e: 0."


- store: Optional[str] = "Name of variable inside the agent memory in which to store given agent's output (i.e: last message in agent history). If not specified, output will simply remain in the called agent's history."
```

### Command: `refresh`

Refresh the agent's history i.e: delete everything except (if applicable) system prompt. 

### Command: `loop`

Loop around to the beginning of the agent's instructions (or, optionally, loop to given step.)

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

Print the last message in the agent's history. If `n` is specified, then print the n'th previous message.

```
Params:

- agent-name: Optional[str] = "Name of agent whose history to print. If not specified, print for calling agent."
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

- write_history : Optional[str] = "If specified, write the entire history of the given actor. Use `actor.history.read()` to get the history."
```

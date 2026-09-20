# Agent Filesystem Demo

This example runs Fictive's `agent` instruction through the standalone agent
harness. By default it uses Pydantic AI's deterministic `FunctionModel`, makes
no network requests, and needs no credentials.

The flow is driven by the library runtime: `main.py` builds the
`filesystem_worker` actor with no instruction list and issues its `system` and
`agent` commands from Python through `fictive.Runtime.cmd_exec`. The equivalent
JSON definition is kept in `scenario/filesystem_worker.json` as a reference for
the JSON runtime; the demo no longer reads it.

From the `fictive/` repository root:

```bash
../.venv/bin/python examples/agent_filesystem_demo/main.py
```

The demo creates a temporary host workspace, seeds `notes.txt`, lets the agent
read it and write `summary.txt`, prints the result and changed-path trace, then
removes the temporary directory. Only the `read_file` and `write_file` tools
are granted; shell access is disabled.

To retain the result, provide an existing directory that contains `notes.txt`:

```bash
mkdir -p /tmp/fictive-agent-demo
printf 'Review owner: Ada\nReview date: Friday\n' > /tmp/fictive-agent-demo/notes.txt
../.venv/bin/python examples/agent_filesystem_demo/main.py \
  --workspace /tmp/fictive-agent-demo
```

The supplied directory becomes both the interpreter's `agent_root` and the
executor's `workspace_root`. The scenario can narrow that root with its
relative `workspace` field but cannot expand it.

For an opt-in live MiniMax run, follow
[`MINIMAX_AGENT_SETUP.md`](../../MINIMAX_AGENT_SETUP.md). The offline fake
provider remains the default.

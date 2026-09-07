# Agent Harness

`agent-harness` is a standalone, provider-neutral wrapper around Pydantic AI
and Pydantic AI Harness. It provides bounded agent execution with a filesystem
workspace rooted by trusted host configuration.

It does not import Fictive or `llm-utils`.

## Install

From the parent `fictive/` directory:

```bash
uv pip install --python ../.venv/bin/python -e ./agent-harness
```

## Core API

```python
import os
from pathlib import Path

from agent_harness import (
    AgentPermissions,
    AgentProfile,
    AgentRequest,
    PydanticAgentExecutor,
)

executor = PydanticAgentExecutor(
    workspace_root=Path("/srv/story-session"),
    profiles={
        "minimax": AgentProfile(
            provider="anthropic",
            model=os.environ["MINIMAX_MODEL"],
            api_key_env="MINIMAX_API_KEY",
            base_url="https://api.minimax.io/anthropic",
            permissions=AgentPermissions(filesystem="workspace-write"),
        )
    },
)

result = executor.run(
    AgentRequest(
        history=[{"role": "user", "content": "Review the workspace."}],
        task="Update the notes.",
        workspace=Path(".chatlogs"),
        profile="minimax",
        requested_tools=("read_file", "write_file"),
    )
)
```

The requested workspace must be relative and resolve beneath
`workspace_root`. Shell execution is intentionally unsupported in this phase.
Custom providers can be supplied through `model_builders` without changing the
executor or exposing SDK objects in results.

MiniMax credentials, model selection, local `.env` loading, live verification,
and Docker injection are documented separately in
[`../MINIMAX_AGENT_SETUP.md`](../MINIMAX_AGENT_SETUP.md). Do not place provider
credentials in profiles committed to source control or in scenario files.

## Test

```bash
../.venv/bin/python -m unittest discover -s agent-harness/tests -v
```

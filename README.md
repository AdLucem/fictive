# fictive

A library for programming LLM chains-of-thought and agentic harnesses, right here in Python.

## Installation and Requirements

Install the package in editable mode from the repository root with:

```bash
pip install -e .
```

This uses the package metadata in `pyproject.toml`, including the direct
dependency on `llm-utils`.

For a requirements-file install of the core package dependencies:

```bash
$ uv pip install -r requirements.txt
```

To include optional serving/runtime backends such as `vllm` and `sglang`, install
the optional requirements file. Some of those packages may require prereleases
on current Python/CUDA stacks:

```bash
$ uv pip install -r requirements-optional.txt --prerelease allow
```

Make sure your `gcc` compiler is up to date! 

If you want to run models from the `Qwen3.5` series, `qwen3_requirements.txt` has a set of instructions that work.

## Web UI

Run a scenario in the browser. From the repository root:

```bash
uv pip install --python .venv/bin/python fastapi "uvicorn[standard]"
.venv/bin/python -m fictive.web --scenario examples/ui_demo/scenario --pipeline-type mock
```

Those two packages are the `ui-server` extra, installed directly because the
repository's `.venv` is uv-managed and has no `pip` of its own.

Then, from `ui/`:

```bash
npm install
npm run dev
```

The app is served at `http://localhost:5173`.

`mock` needs no model or credentials. For a real model, pass any pipeline
`llm-utils` builds:

```bash
python -m fictive.web --scenario examples/ui_demo/scenario \
  --pipeline-type openai --model deepseek/deepseek-v3.2
```

Each pipeline reads its own provider's key and base URL from the environment or
a `.env` in the working directory (`OPENROUTER_API_KEY` /
`OPENROUTER_BASE_URL`, `ANTHROPIC_API_KEY`, and so on).

To serve the app from the backend instead of the dev server, run
`npm run build` in `ui/`; the backend mounts `ui/dist` at `/`.

## Agent Harness Compatibility Spike

The independent `agent-harness/` package owns the pinned Pydantic AI Harness
stack. From this repository directory, install it and the existing project
requirements into a caller-provided virtual environment:

```bash
uv pip install --python ../.venv/bin/python -r requirements.txt
../.venv/bin/python compatibility/agent_harness_spike.py
```

The check is offline by default. A live MiniMax tool-call check can be enabled
with `--live` after setting `MINIMAX_API_KEY`, `MINIMAX_MODEL`, and optionally
`MINIMAX_BASE_URL`.

Run the standalone wrapper's deterministic suite with:

```bash
../.venv/bin/python -m unittest discover -s agent-harness/tests -v
```

The Docker image runs the same offline check while building:

```bash
docker build -t fictive-agent-spike .
docker run --rm fictive-agent-spike \
  python3 compatibility/agent_harness_spike.py
```

## Agent Instruction

Fictive scenarios can invoke the standalone harness with the `agent` command:

```json
{
  "cmd": "agent",
  "profile": "workspace-editor",
  "prompt": "Read notes.txt and update summary.txt.",
  "workspace": ".",
  "tools": ["read_file", "write_file"],
  "request-limit": 10,
  "tool-call-limit": 20,
  "store": "agent-answer",
  "trace-store": "agent-trace"
}
```

Trusted host code supplies the executor, provider profiles, and maximum
workspace root. Scenario fields can narrow those permissions but cannot widen
them. The agent path is independent of `llm-utils`, and an agent-only actor
does not need an ordinary generation pipeline.

Run the deterministic filesystem example without network access or
credentials:

```bash
../.venv/bin/python examples/agent_filesystem_demo/main.py
```

See [the scene language reference](SCENE_CONFIG_LANGUAGE.md) for all command
fields, [the example guide](examples/agent_filesystem_demo/README.md) for
workspace usage, and [the MiniMax setup guide](MINIMAX_AGENT_SETUP.md) for the
separate opt-in environment configuration.

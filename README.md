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

## Scenario Directories

A scenario passed to `--scenario` only strictly needs one file: `schema.json`,
naming its `actors` (plus optional `main_actor` and `actor_types`). Each actor
listed needs a matching `<name>.json` command file alongside it, and prompt
files can live anywhere under the directory, referenced by relative path.

JSON chat mode (`run_chat`, `run_debug`) adds two rules: the main actor must
reach an `input-from` with a `human_prompt` (even `""`) so control can hand off
to a human reader, and an actor's command list must end on `exit`, never on
`run-actor`. Neither applies to the web UI, which runs Python flows instead --
see below.

See [`SCENE_CONFIG_LANGUAGE.md`](SCENE_CONFIG_LANGUAGE.md) for the full
command/field reference, and [`DOCS.md`](DOCS.md#scenario-directories) /
[`REPOSITORY_DOCS.md`](REPOSITORY_DOCS.md#scenario-loading-requirements) for
the complete rules, including the `"scorer"` output-format gotcha.

## Web UI

Run a scenario in the browser. The web backend runs a scenario written as a `fictive.Runtime` flow, so `--scenario` should be a `.py` file, or a directory containing `fictive_scenario.py`. See
[`DOCS.md`](DOCS.md#writing-a-scenario-for-the-web-ui) for the module contract.

From the repository root: (if you just want to test the UI without using a real backend, use `--pipeline-type mock`)

```bash
uv pip install --python .venv/bin/python fastapi "uvicorn[standard]"
python -m fictive.web --scenario examples/evil_AI/fictive_scenario.py --pipeline-type openai --model deepseek/deepseek-v3.2
```

Those two packages are the `ui-server` extra.

Then, from `ui/`:

```bash
npm install
npm run dev
```

The app is served at `http://localhost:5173`.

Each pipeline reads its own provider's key and base URL from the environment or a `.env` in the working directory (`OPENROUTER_API_KEY` /
`OPENROUTER_BASE_URL`, `ANTHROPIC_API_KEY`, and so on).

To serve the app from the backend instead of the dev server, run `npm run build` in `ui/`; the backend mounts `ui/dist` at `/`.

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

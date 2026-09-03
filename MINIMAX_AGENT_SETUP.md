# MiniMax Agent Setup

MiniMax is an opt-in provider for the standalone agent harness. The default
filesystem example uses a local fake model and does not need these variables.

## Environment variables

- `MINIMAX_API_KEY` — required secret API credential.
- `MINIMAX_MODEL` — required MiniMax model identifier exposed by the
  Anthropic-compatible API.
- `MINIMAX_BASE_URL` — optional endpoint override. It defaults to
  `https://api.minimax.io/anthropic`.

Keep credentials outside scenario JSON, actor prompts, interpreter store
values, command-line arguments, and version-controlled files. The repository's
`.gitignore` and `.dockerignore` exclude `.env` files.

For local development, place the values in the parent Centaurus `.env` file:

```dotenv
MINIMAX_API_KEY=replace_with_your_secret
MINIMAX_MODEL=replace_with_your_model_id
MINIMAX_BASE_URL=https://api.minimax.io/anthropic
```

Then export that file through the existing environment bootstrap and run the live example:

```bash
source setenv
python examples/agent_filesystem_demo/main.py --provider minimax
```

The example still confines tools to its runtime workspace and grants only
`read_file` and `write_file`. To retain the written summary, pass an existing
workspace containing `notes.txt`:

```bash
python examples/agent_filesystem_demo/main.py \
  --provider minimax \
  --workspace examples/agent_workspace
```

## Compatibility check

The lower-level live adapter check uses the same variables:

```bash
python compatibility/agent_harness_spike.py --live
```

## Docker

Do not bake the API key into an image. Inject an environment file at runtime:

```bash
docker run --rm --env-file ../.env \
  fictive-agent-spike \
  python3 examples/agent_filesystem_demo/main.py --provider minimax
```

The image also accepts a read-only `.env` mounted at `/app/.env`; its
entrypoint exports that file before starting the requested command.

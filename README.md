# fictive
A library for creating LLM-based interactive fiction systems.

## Installation and Requirements

Install the package in editable mode from the repository root with:

```bash
pip install -e .
```

This uses the package metadata in `pyproject.toml`, including the direct
dependency on `llm-utils`.

You have to allow prerelease versions for `flash-attn-4`:

```bash
$ uv pip install -r requirements.txt --prerelease allow
```

Make sure your `gcc` compiler is up to date! 

If you want to run models from the `Qwen3.5` series, `qwen3_requirements.txt` has a set of instructions that work.

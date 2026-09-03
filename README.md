# fictive
A library for creating LLM-based interactive fiction systems.

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

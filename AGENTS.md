# Repository Instructions

This file (`AGENTS.md`) is the canonical source of repository-wide agent
instructions. `CLAUDE.md` and `.kiro/steering/agents.md` both import this file
rather than duplicating it, and OpenAI's Codex-family tools read `AGENTS.md`
directly. Edit instructions here; do not fork them into those other files.

## Documentation Terminology

When these instructions, or a user, refer to "documentation" without naming a
specific file, it means the following three files, each with a distinct scope:

- `REPOSITORY_DOCS.md` — developer-facing documentation of the repository
  itself: its files, modules, and architecture. This is the file the "Agent
  Context Hook" section below tells you to read first.
- `DOCS.md` — concise, human-readable documentation of the `fictive`
  software, language, and web UI, for someone using or learning about the
  project without needing repository-internals detail.
- `README.md` — the shortest version, written for a project README: a quick
  overview and getting-started reference.

The "Documentation Policy" section below governs when `DOCS.md` and
`REPOSITORY_DOCS.md` must be updated as part of a change.

## Documentation Policy

Any change that modifies files in this repository must also update `REPOSITORY_DOCS.md` when needed so it continues to reflect the current repository structure, behavior, and usage. It must also update `DOCS.md`, which is a more succinct, human-readable documentation file.

When deciding whether `DOCS.md` and `REPOSITORY_DOCS.md` needs an update, ignore changes that are only
inside:

- `llm-utils/`
- `examples/`

Those directories should not drive updates to the root documents unless a change there also requires a documented change to the main `fictive` project
itself.

This applies to:

- creating files
- deleting files
- renaming files or directories
- changing module responsibilities
- changing setup or runtime flows
- adding or removing important dependencies
- changing scenario configuration expectations

If a code or configuration change does not affect repository structure, behavior, or usage, `DOCS.md` and `REPOSITORY_DOCS.md` do not need to be edited just for the sake of touching them.

## Agent Context Hook

For future coding sessions in this repository, when the goal is to understand what a particular class, module, or file is doing, read `REPOSITORY_DOCS.md` first.
Use it as the default condensed architecture reference to reduce token usage.

Only open the underlying implementation file after consulting
`REPOSITORY_DOCS.md`, and only when `REPOSITORY_DOCS.md` does not provide a clear enough picture for the task.

## Do Not Automatically Generate A Test File

When implementing a module, do NOT automatically generate a test file in the `test/` directory. This is a waste of tokens. Only generate tests if you are specifically asked to.



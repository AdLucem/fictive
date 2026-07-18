# Repository Instructions

## Documentation Policy

Any change that modifies files in this repository must also update `DOCS.md`
when needed so it continues to reflect the current repository structure,
behavior, and usage.

When deciding whether `DOCS.md` needs an update, ignore changes that are only
inside:

- `llm-utils/`
- `examples/`

Those directories should not drive updates to the root `DOCS.md` unless a
change there also requires a documented change to the main `fictive` project
itself.

This applies to:

- creating files
- deleting files
- renaming files or directories
- changing module responsibilities
- changing setup or runtime flows
- adding or removing important dependencies
- changing scenario configuration expectations

If a code or configuration change does not affect repository structure,
behavior, or usage, `DOCS.md` does not need to be edited just for the sake of
touching it.

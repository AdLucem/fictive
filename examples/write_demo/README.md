Minimal `write` command example, driven by the library runtime.

Run:

```bash
python examples/write_demo/main.py
```

`main.py` builds the `writer` actor with no instruction list and issues every
command from Python through `fictive.Runtime.cmd_exec`, so the order of the
scene is plain Python rather than a JSON instruction list. The equivalent JSON
definition is kept in `scenario/writer.json` and `scenario/schema.json` for
comparison with the JSON runtime; the demo no longer reads them.

This scenario uses a local static pipeline, so it does not need a model server.
It writes four files into `examples/write_demo/scenario/outputs/`:

- `latest.txt` from the actor's latest generated output
- `from-store.txt` from a store variable via `read_from`
- `from-file.txt` from a scenario file via `read_from`
- `history.json` from `write_history`

The three `read_from`/latest writes pass `overwrite=True`, so re-running the
demo replaces the output files instead of appending to them.

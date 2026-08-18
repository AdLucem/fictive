Minimal `write` command example.

Run:

```bash
python examples/write_demo/main.py
```

This scenario uses a local static pipeline, so it does not need a model server.
It writes four files into `examples/write_demo/scenario/outputs/`:

- `latest.txt` from the actor's latest generated output
- `from-store.txt` from a store variable via `read_from`
- `from-file.txt` from a scenario file via `read_from`
- `history.json` from `write_history`

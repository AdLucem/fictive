# New functions and API endpoints (branch `farhan`)

> Paths in this file are relative to the `arachne` superproject root, where this repo is checked out as a submodule. The full cross-repo version lives at `NEW_FUNCTIONS_AND_ENDPOINTS.md` in the superproject.

## fictive (`centaurus/fictive`, branch `farhan`)

One small commit on top of `main`: "Stop History.read() mutating stored messages; make transformers optional". No new public API surface except `Store.has`; the rest are behaviour fixes that Centaurus's routing actor depends on.

### `fictive/data_structures.py`

function/api endpoint: `Store.has`
Reports whether a store variable was ever assigned, which `Store.get` cannot express because an unassigned variable and one assigned `None` both read back as `None`.
`centaurus/fictive/fictive/data_structures.py:232`
Prerequisites: None.
Inputs: `var_name: str`.
Outputs: `bool`.

function/api endpoint: `History.read` (modified)
Previously stringified non-string `content` in place, corrupting structured messages (the Centaurus routing actor stores a dict) for every later reader. Now returns copies with `content` stringified only in the copy.
`centaurus/fictive/fictive/data_structures.py:99`
Prerequisites: None.
Inputs: `merged: bool = True`.
Outputs: `List[dict]` of fresh message copies; stored history is untouched.

function/api endpoint: `History.get_merged` (modified)
Every branch now appends `copy(msg)` and merges same-role content with an f-string instead of `+=`, so a non-string `content` merges instead of raising and the stored dict is never aliased.
`centaurus/fictive/fictive/data_structures.py:18`
Prerequisites: None.
Inputs: none.
Outputs: merged `List[dict]`.

### `fictive/interpreter.py`

function/api endpoint: `Interpreter.store_fetch` (modified)
Uses `Store.has` (presence) instead of `get(...) is not None` (truthiness). A variable deliberately assigned `None` (e.g. an absent router argument) now returns `None` instead of raising "not in memory store".
`centaurus/fictive/fictive/interpreter.py:588`
Prerequisites: None.
Inputs: `key: str`.
Outputs: the stored value (possibly `None`); raises `Exception` only if the key was never assigned.

### `fictive/run.py`, `fictive/library_runtime.py`

function/api endpoint: module import of `transformers` (modified)
`import transformers` is now wrapped in `try/except ImportError`; it was only used to silence that library's logger, so `fictive` no longer hard-requires `transformers` (Centaurus's CPU/API-only install omits it).
`centaurus/fictive/fictive/run.py:13`, `centaurus/fictive/fictive/library_runtime.py:17`
Prerequisites: None (transformers optional).
Inputs / Outputs: n/a.

### Other
- `DOCS.md`: describes the copy semantics of `History.read`/`get_merged`, `Store.has`, and the optional `transformers` import. (The `on_delta` / `Interpreter.on_generate_delta` streaming hooks that Centaurus's SSE console uses were already on `main`.)
- Submodule pointer `llm-utils` advanced to the llm-utils `farhan` commit.

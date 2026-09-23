# `ui/` — a chat front end for fictive scenarios

A React app for running a scenario the way a reader sees it: the main actor's
visible generations are the conversation, and every other actor the scenario
calls appears inline as an expandable bar.

A bar is not a UI metaphor. Each one is a `run-actor` frame on the
interpreter's callstack, labelled with the command that opened it and the store
variable it fills when control returns. Bars nest because frames nest, and the
nesting is drawn to five levels — below that a frame is counted and named
rather than drawn, with a link back to the actor it belongs to.

The backend runs a scenario written as a Python flow against `fictive.Runtime`,
so `--scenario` below names a scenario module rather than a directory of JSON —
see `DOCS.md` for the contract a module answers.

## Running it

Two processes in development, one in production.

**1. The backend** (`fictive/web/`), from the repository root:

```bash
git submodule update --init          # llm-utils; fictive/_bootstrap.py puts it on sys.path
uv pip install --python .venv/bin/python fastapi "uvicorn[standard]"
.venv/bin/python -m fictive.web --scenario examples/evil_AI --pipeline-type mock
```

Those two packages are the `ui-server` extra. They are installed directly
rather than through `pip install -e ".[ui-server]"` for two reasons: the
repository's `.venv` is uv-managed and carries no `pip` of its own, and
`-e .` pulls the whole training stack — torch, torchvision, transformers,
scikit-learn — none of which this backend touches when the model is hosted or
mocked. Verified minimum for running the UI, in a clean virtualenv:

```bash
uv pip install --python .venv/bin/python lark requests fastapi "uvicorn[standard]" "anthropic<1"
```

With the submodule checked out, that is enough to import `fictive`, serve the
API and run a scenario end to end.

It serves on `http://127.0.0.1:8000`. `--pipeline-type mock` needs no model and
no credentials; swap in `sglang`, `anthropic` or any other pipeline
`llm_utils.pipeline_from_config` builds, with `--model`, to run the scenario
against a real one.

For Claude, `--pipeline-type anthropic --model claude-sonnet-5`. The key comes
from `$ANTHROPIC_API_KEY` (or `--token`), and `--base-url` overrides the
endpoint:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m fictive.web --scenario examples/evil_AI \
  --pipeline-type anthropic --model claude-sonnet-5
```

For an OpenAI-compatible endpoint, including OpenRouter:

```bash
# key and base URL come from OPENROUTER_API_KEY / OPENROUTER_BASE_URL, in the
# environment or a .env in the working directory
python -m fictive.web --scenario examples/evil_AI \
  --pipeline-type openai --model deepseek/deepseek-v3.2
```

`--token` and `--base-url` override that resolution when you need them to;
left alone, each pipeline reads only its own provider's variables.

**Pin `anthropic<1` for that path.** `llm_utils.anthropic_messages_completion`
passes `temperature` to `client.messages.create`, and the 1.x SDK removed that
parameter, so every call raises `TypeError: Messages.create() got an unexpected
keyword argument 'temperature'` before it reaches the network. This includes
`anthropic==1.3.0`, which `requirements.txt` pins, so the repository's own
documented install hits it: checked against 1.3.0 and 1.7.0, and neither
accepts the parameter. On `anthropic 0.x` the same call reaches the API and
authenticates normally (a bad key comes back as a clean 401). The fix belongs
in `llm-utils`, which is a submodule of this repository.

**2. The UI**, from `ui/`:

```bash
npm install
npm run dev
```

Vite serves the app on `http://localhost:5173` and proxies `/api` to the
backend, so the app's fetch paths stay relative. Point it at a backend on
another port with `FICTIVE_API=http://127.0.0.1:8123 npm run dev`.

**In one process:** `npm run build` writes `ui/dist`, which the backend mounts
at `/` when it is present. Then `python -m fictive.web` alone serves both.

## What the app calls

Every path comes from `fictive/web/app.py`:

| Method | Path | Used for |
| --- | --- | --- |
| `GET` | `/api/scenario` | the scenario's name, its actors and the pipeline, for the rail |
| `GET` | `/api/sessions` | the session list: live runs, plus session files on disk |
| `POST` | `/api/sessions` | start a run; `{"load_session_id": "..."}` resumes a saved one |
| `GET` | `/api/sessions/{id}` | the current transcript, store and callstack |
| `POST` | `/api/sessions/{id}/messages` | send the reader's turn and run until the scenario asks again |
| `POST` | `/api/sessions/{id}/rewrite` | `{"message_seq": n, "text": "..."}` — replace a reader message and run on from it |
| `POST` | `/api/sessions/{id}/fork` | `{"message_seq": n, "text": "..."}` — branch a new session at a reader message |
| `POST` | `/api/sessions/{id}/save` | write the session file |
| `DELETE` | `/api/sessions/{id}` | forget a session: the live run, its session file, or both |
| `GET` | `/api/health` | scenario, pipeline, whether the pipeline can stream |

A turn is one synchronous `POST`: the backend resumes the scenario's flow
generator with the reader's answer, runs every command the turn reaches —
including the whole nested chain of called actors — and answers with the updated
tree when the flow next asks for input. The UI shows a `running` state for the
duration. A `POST` to a session that is not waiting, or is already running a
turn, answers `409` with a `detail` the UI shows as a snackbar.

## Layout

```
src/
  api.ts                  every call, one function each
  types.ts                the JSON shapes fictive/web/chat.py serves
  theme.css               Material 3 dark scheme, purple source
  App.tsx                 session state, and the one place calls are made
  components/
    SessionsRail.tsx      live and saved sessions, search, new session, delete
    Transcript.tsx        messages and top-level flow bars
    FlowBar.tsx           one callstack frame; recursive, capped at depth 5
    Composer.tsx          the reader's turn
    Inspector.tsx         callstack, store, session file
    icons.tsx
```

## Notes

- **Depth cap.** `MAX_RENDER_DEPTH` in `FlowBar.tsx` is 5. The backend sends the
  whole tree with each frame's depth; the cap is a rendering decision, so
  raising it needs no backend change.
- **Elevation is depth.** Each level sits one surface-container tone lighter
  than the frame that called it, to L5. No bar carries a shadow — on a dark
  surface, elevation reads as tone. Shadow is kept for the FAB and the
  snackbar, which genuinely float.
- **No streaming yet.** Token-level streaming would come from
  `Interpreter.on_generate_delta`, which reaches the pipeline's
  `generate_stream`. The `llm_utils` pipelines do not define one, so the
  backend leaves the hook unset and a turn arrives whole. `/api/health` reports
  `streaming: false` for pipelines in that state.
- **Resumed sessions.** A session file holds each actor's history, the store
  and the callstack — not the flow tree, and not the flow's own position, which
  lives in a Python generator. So resuming restores the state and starts the
  scenario's entry flow again against it. The conversation is rebuilt from the
  main actor's history and says so; frames from before the save are not in the
  file. A scenario avoids re-narrating its opening by branching on the store
  variable `_fictive_resumed`, or by defining `resume_flow(runtime)`.
- **The generic placeholder.** When `waiting_prompt` is `null` the composer
  shows "Answer as the reader…". That is a flow asking with
  `ask(..., content=False)`: a bare turn-taking cue, which exists because a
  terminal has to print something before calling `input()`. This app has its own
  input box, so it shows that instead of rendering the cue as an AI message.
  `awaiting_input` is what says the session is waiting, never `waiting_prompt`.
- **Step numbers are command counts.** A flow-driven actor has no instruction
  list, so `step_pointers` and a node's `step` report how many commands that
  actor has issued rather than a position in a list.
- **Deleting a session.** Each row in the rail carries a trash control, shown
  on hover or keyboard focus. It asks once, in the row itself rather than in a
  modal — the call removes a file from disk and cannot be undone, and the rows
  are small and close together, so a stray click is the mistake worth making
  impossible. Confirming deletes everything behind the row: the live run, and
  the session file if the session was saved. One control covers both because
  the rail lists one row per session — a live run that has been saved is
  filtered out of the saved group — so a delete has only one thing it can mean.

  A session running a turn answers `409`, the same as a concurrent message, and
  the backend validates the id before joining it to a path. Deleting the open
  session moves the view to the next live one, or starts a fresh session if
  that was the last, so the app is never left with nothing to show.

- **Full prompts on a step.** A `system` or an `input-from` is nearly always
  written as a path, and the step used to show only the file's name. The
  backend now also sends `detail_text`: the whole text the command was handed,
  read off the actor once the command has run rather than by resolving the path
  again, so enclosing prompts and store lookups show as what the actor actually
  received. `Step` in `FlowBar.tsx` renders it open, with the detail line above
  it as the toggle and a word count beside it; the block scrolls inside a
  bounded height, so one long system prompt cannot push the transcript around.

- **Rewriting and forking.** Hovering a reader message reveals **Rewrite** and
  **Fork**. Both open the message in an editor; the difference is what happens
  to the turns after it. A rewrite runs the same session on from that message,
  so those turns stop existing — the editor says how many will go. A fork
  leaves the session untouched and starts a second one that shares everything
  up to the message, which is the one to use when the later turns are worth
  keeping. The view follows the fork; the original stays in the rail.

  The buttons appear only on the messages in `session.branch_points`. The
  backend can rewind only to a message it holds a checkpoint for, and it takes
  those as a turn is asked for, so a session resumed from a file has real
  messages with nothing to rewind to until it takes a turn of its own. It also
  keeps at most `RuntimeChatSession.MAX_CHECKPOINTS` (50) of them, since each
  one holds a copy of every actor's history. Sending a `message_seq` that is not
  in the list answers `404`; either call while a turn is running answers `409`.

  A rewrite works on a session whose flow has finished or died, which is the
  way out of a failed turn: going back throws the old flow away and starts a
  fresh one either way, so there is nothing for a dead generator to spoil.

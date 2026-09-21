# `ui/` — a chat front end for fictive scenarios

A React app for running a scenario the way a reader sees it: the main actor's
generations are the conversation, and every other actor the scenario calls
appears inline as an expandable bar.

A bar is not a UI metaphor. Each one is a `run-actor` frame on the
interpreter's callstack, labelled with the command that opened it and the store
variable its `exit` fills. Bars nest because frames nest, and the nesting is
drawn to five levels — below that a frame is counted and named rather than
drawn, with a link back to the actor it belongs to.

## Running it

Two processes in development, one in production.

**1. The backend** (`fictive/web/`), from the repository root:

```bash
pip install -e ".[ui-server]"
python -m fictive.web --scenario examples/ui_demo/scenario --pipeline-type mock
```

It serves on `http://127.0.0.1:8000`. `--pipeline-type mock` needs no model and
no credentials; swap in `sglang`, `anthropic` or any other pipeline
`llm_utils.pipeline_from_config` builds, with `--model`, to run the scenario
against a real one.

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
| `POST` | `/api/sessions/{id}/save` | write the session file |
| `GET` | `/api/health` | scenario, pipeline, whether the pipeline can stream |

A turn is one synchronous `POST`: the backend runs every command the turn
reaches — including the whole nested chain of called actors — and answers with
the updated tree. The UI shows a `running` state for the duration.

## Layout

```
src/
  api.ts                  every call, one function each
  types.ts                the JSON shapes fictive/web/chat.py serves
  theme.css               Material 3 dark scheme, purple source
  App.tsx                 session state, and the one place calls are made
  components/
    SessionsRail.tsx      live and saved sessions, search, new session
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
  and the callstack — not the flow tree, which is recorded from steps as they
  run. Resuming rebuilds the conversation and says so; frames from before the
  save are not in the file.

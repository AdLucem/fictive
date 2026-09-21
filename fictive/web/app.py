"""A minimal uvicorn/FastAPI app that runs one fictive scenario in chat mode.

Start it with a scenario directory and a pipeline:

    python -m fictive.web --scenario examples/ui_demo/scenario --pipeline-type mock

Every route is under `/api`. A built UI at `ui/dist` is served at `/`, so one
process can serve both; during development the Vite dev server proxies here
instead.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from llm_utils import PipelineConfig, pipeline_from_config

from .chat import ChatSession, ScenarioSpec

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO = REPO_ROOT / "examples" / "ui_demo" / "scenario"
DEFAULT_STORAGE = pathlib.Path.home() / ".fictive_logs" / "ui"
DEFAULT_UI_DIST = REPO_ROOT / "ui" / "dist"


class NewSession(BaseModel):
    title: Optional[str] = None
    load_session_id: Optional[str] = None


class Message(BaseModel):
    text: str


def create_app(
    scenario_dir: str | pathlib.Path = DEFAULT_SCENARIO,
    storage_dir: str | pathlib.Path = DEFAULT_STORAGE,
    pipeline_type: str = "mock",
    model: str = "mock",
    ui_dist: str | pathlib.Path = DEFAULT_UI_DIST,
    **pipeline_kwargs,
) -> FastAPI:
    spec = ScenarioSpec(scenario_dir)
    storage_dir = pathlib.Path(storage_dir)
    pipeline = pipeline_from_config(
        PipelineConfig(model=model, pipeline_type=pipeline_type, **pipeline_kwargs)
    )

    sessions: dict[str, ChatSession] = {}

    app = FastAPI(title="fictive", version="0.1.0")
    # The UI is served from this process in production and from the Vite dev
    # server in development; both are local, so the origin list stays open.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_session(session_id: str) -> ChatSession:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"No session {session_id}")
        return session

    def conversations_dir() -> pathlib.Path:
        return storage_dir / "conversations"

    def saved_sessions() -> list[dict]:
        directory = conversations_dir()
        if not directory.is_dir():
            return []
        rows = []
        for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            row = {
                "id": path.stem,
                "path": str(path),
                "saved_at": path.stat().st_mtime,
                "actors": [],
                "live": path.stem in sessions,
            }
            try:
                with path.open() as handle:
                    data = json.load(handle)
                row["actors"] = list((data.get("actors") or {}).keys())
                row["callstack"] = data.get("callstack", [])
            except (OSError, ValueError):
                row["unreadable"] = True
            rows.append(row)
        return rows

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "scenario": spec.name,
            "pipeline": type(pipeline).__name__,
            "streaming": hasattr(pipeline, "generate_stream"),
            "live_sessions": len(sessions),
        }

    @app.get("/api/scenario")
    def get_scenario() -> dict:
        payload = spec.to_json()
        payload["pipeline"] = type(pipeline).__name__
        payload["storage_dir"] = str(storage_dir)
        payload["conversations_dir"] = str(conversations_dir())
        return payload

    @app.get("/api/sessions")
    def list_sessions() -> dict:
        live = [
            {
                "id": session.id,
                "title": session.title,
                "status": session.status,
                "turn_count": session.turn_count,
                "main_actor": session.spec.main_actor_name,
                "saved_path": session.saved_path,
                "live": True,
            }
            for session in sessions.values()
        ]
        return {"live": live, "saved": saved_sessions()}

    @app.post("/api/sessions")
    def create_session(body: NewSession | None = None) -> dict:
        body = body or NewSession()
        session = ChatSession(spec, pipeline, storage_dir, title=body.title)
        sessions[session.id] = session
        if body.load_session_id:
            try:
                session.interpreter.load_session(session_id=body.load_session_id)
            except Exception as exc:  # a bad or foreign session file
                sessions.pop(session.id, None)
                raise HTTPException(status_code=400, detail=f"Could not load: {exc}") from exc
            session.status = "running"
            session.title = f"Resumed {body.load_session_id}"
            session.rebuild_from_history()
            session.advance()
        else:
            session.start()
        return session.to_json()

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str) -> dict:
        return get_session(session_id).to_json()

    @app.post("/api/sessions/{session_id}/messages")
    def post_message(session_id: str, body: Message) -> dict:
        session = get_session(session_id)
        if not session.awaiting_input_now():
            raise HTTPException(
                status_code=409,
                detail=f"Session {session_id} is {session.status}, not waiting for input",
            )
        session.send_input(body.text)
        return session.to_json()

    @app.post("/api/sessions/{session_id}/save")
    def save_session(session_id: str) -> dict:
        session = get_session(session_id)
        try:
            path = session.save()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"id": session.id, "saved_path": path}

    if pathlib.Path(ui_dist).is_dir():
        dist = pathlib.Path(ui_dist)
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

    return app


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the fictive chat UI backend.")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--storage-dir", default=str(DEFAULT_STORAGE))
    parser.add_argument(
        "--pipeline-type",
        default="mock",
        choices=["mock", "sglang", "transformers", "vllm", "minimax", "anthropic", "openai"],
    )
    parser.add_argument("--model", default="mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--ui-dist", default=str(DEFAULT_UI_DIST))
    # Left unset by default so each pipeline resolves its own credentials, and
    # a key for one provider can never be handed to another: the anthropic SDK
    # reads ANTHROPIC_API_KEY itself, and llm_utils' openai-compatible path
    # reads OPENAI_API_KEY or OPENROUTER_API_KEY, from the environment or a
    # `.env` in the working directory. Pass these only to override that.
    parser.add_argument(
        "--token",
        default=None,
        help="API key, when the pipeline should not resolve its own.",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL, when the pipeline should not resolve its own.",
    )
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-new-tokens", type=int, default=2048)
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    import uvicorn

    args = build_arg_parser().parse_args(argv)
    if args.pipeline_type == "anthropic" and not (args.token or os.environ.get("ANTHROPIC_API_KEY")):
        raise SystemExit(
            "--pipeline-type anthropic needs an API key: set ANTHROPIC_API_KEY or pass --token."
        )
    app = create_app(
        scenario_dir=args.scenario,
        storage_dir=args.storage_dir,
        pipeline_type=args.pipeline_type,
        model=args.model,
        ui_dist=args.ui_dist,
        token=args.token,
        base_url=args.base_url,
        temperature=args.temperature,
        max_new_tokens=args.max_new_tokens,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

"""A `Runtime` backed by Amazon Bedrock, with one method per scenario command.

Two things this class exists to do:

- **Install a Bedrock backend.** A backend is not chosen at the runtime level
  in fictive; it is `Actor.pipeline`. So this builds a `BedrockPipeline` and
  puts it on the interpreter's actors. Only `generate`, `rag-generate` and
  `web-search-and-generate` actually reach it; the other commands are
  backend-agnostic and are exposed here for a uniform API.
- **Expose the commands as Python.** `Runtime` has one generic
  `cmd_exec(command, **kwargs)`; the named methods below wrap it so a caller
  writes `rt.generate()` rather than `rt.cmd_exec("generate")`.

Four commands are deliberately *not* thin wrappers, because driving them
through `cmd_exec` would be silently wrong. `exit` is a no-op in the
interpreter and the unwind is done here; `cond` only queues instructions for
the interpreter's own loop, so `drain_pending` runs them and `evaluate` is what
an imperative caller usually wants; `loop` rewinds a step pointer that nothing
increments on this path. Each says so in its docstring.

`cmd_exec` never calls `Cmd.normalize_params`, so every parameter below is the
exact dataclass field name, with underscores -- `input_from_store`, not
`input-from-store`, and `assign(var_name=...)`, not `name=`.

Use `mode="chat"` (the default) for library work: in `"debug"`, `cmd_exec`
stops for `input("debug> ")` before every single command.
"""

import pathlib
from typing import Any, List, Literal, Optional

from .actors import Actor
from .interpreter import Interpreter
from .library_runtime import Runtime
from .pipelines import build_bedrock_pipeline


class BedrockRuntime(Runtime):
    """Drive a scenario imperatively with Claude on Bedrock behind the actors."""

    def __init__(
        self,
        interpreter: Interpreter,
        start_actor_name: str,
        mode: Literal["debug", "chat", "single-actor"] = "chat",
        *,
        pipeline: Any = None,
        model: Optional[str] = None,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        max_tokens: Optional[int] = None,
        thinking_budget: Optional[int] = None,
        timeout: float = 180,
        apply_to_actors: bool = True,
        override_existing_pipelines: bool = True,
        web_search_backend: Any = None,
    ):
        super().__init__(interpreter, start_actor_name, mode)

        # `pipeline` is the injection point: anything with `model_name`,
        # `generate` and `generate_stream` is accepted, so a test or a host with
        # its own client never touches AWS. Otherwise a `BedrockPipeline` is
        # built, and even that makes no network call until it is first used.
        self.pipeline = pipeline if pipeline is not None else build_bedrock_pipeline(
            model=model,
            region=region,
            profile=profile,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            timeout=timeout,
        )

        if apply_to_actors:
            self.install_pipeline(override_existing=override_existing_pipelines)

        if web_search_backend is not None:
            interpreter.web_search_backend = web_search_backend

    def install_pipeline(self, pipeline: Any = None, *, override_existing: bool = True) -> None:
        """Put the Bedrock pipeline on the interpreter's actors.

        Both `actor.pipeline` and `actor.cfg.pipeline` are set. The second is
        not redundant: `Actor.__init__` prefers `cfg.pipeline` over
        `cfg.pipeline_config`, so an actor rebuilt from its config later would
        otherwise fall back to whatever `pipeline_config` names.
        """
        pipeline = pipeline if pipeline is not None else self.pipeline
        for actor in self.interpreter.actors.values():
            if not override_existing and getattr(actor, "pipeline", None) is not None:
                continue
            actor.pipeline = pipeline
            cfg = getattr(actor, "cfg", None)
            if cfg is not None:
                cfg.pipeline = pipeline

    # ------------------------------------------------------------------
    # dispatch
    # ------------------------------------------------------------------

    def cmd(self, command: str, **kwargs) -> Actor:
        """Run one interpreter command against the working actor and return it.

        `None` values are dropped: every optional command field defaults to
        `None`, so omitting one is identical to passing it, and dropping them
        keeps `load-conversation`'s exactly-one-of check honest.
        """
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        self.cmd_exec(command, **kwargs)
        return self.working_actor

    # ------------------------------------------------------------------
    # commands that reach the model
    # ------------------------------------------------------------------

    def generate(self, prompt: Optional[str | pathlib.Path | dict] = None) -> Actor:
        """Generate the actor's next message and append it to history."""
        return self.cmd("generate", prompt=prompt)

    def rag_generate(
        self,
        prompt: Optional[str | pathlib.Path | dict] = None,
        query: Optional[str | dict] = None,
        top_k: int = 4,
        actor_filter: Optional[str] = None,
        enclosing_prompt: Optional[str | pathlib.Path] = None,
        backend: Optional[str] = None,
        model_arn: Optional[str] = None,
        store: Optional[str] = None,
        sources_store: Optional[str] = None,
        fallback_on_retrieval_error: bool = False,
    ) -> Actor:
        """Retrieve from past conversations, then generate from what came back.

        With the native Bedrock Knowledge Base backend the actor's pipeline --
        and so this runtime's `BedrockPipeline` -- is not used at all:
        generation happens inside `RetrieveAndGenerate` against
        `BEDROCK_MODEL_ARN`. Build `BedrockKnowledgeBaseBackend(
        native_generation=False)` to generate with the actor's pipeline instead.
        """
        return self.cmd(
            "rag-generate",
            prompt=prompt,
            query=query,
            top_k=top_k,
            actor_filter=actor_filter,
            enclosing_prompt=enclosing_prompt,
            backend=backend,
            model_arn=model_arn,
            store=store,
            sources_store=sources_store,
            fallback_on_retrieval_error=fallback_on_retrieval_error,
        )

    def web_search_and_generate(
        self,
        prompt: Optional[str | pathlib.Path | dict] = None,
        query: Optional[str | dict] = None,
        max_results: int = 5,
        enclosing_prompt: Optional[str | pathlib.Path] = None,
        backend: Optional[str] = None,
        filters: Optional[dict] = None,
        store: Optional[str] = None,
        sources_store: Optional[str] = None,
        fallback_on_search_error: bool = False,
    ) -> Actor:
        """Search the web, then generate from the results.

        The results reach the model and never the stored history. Exactly one
        assistant message is appended.
        """
        return self.cmd(
            "web-search-and-generate",
            prompt=prompt,
            query=query,
            max_results=max_results,
            enclosing_prompt=enclosing_prompt,
            backend=backend,
            filters=filters,
            store=store,
            sources_store=sources_store,
            fallback_on_search_error=fallback_on_search_error,
        )

    #: The camelCase spelling, for parity with the scenario-language alias.
    webSearchAndGenerate = web_search_and_generate

    def agent(
        self,
        profile: str,
        prompt: Optional[str | pathlib.Path | dict] = None,
        workspace: Optional[str | pathlib.Path] = None,
        tools: Optional[List[str]] = None,
        request_limit: int = 20,
        tool_call_limit: int = 50,
        store: Optional[str] = None,
        trace_store: Optional[str] = None,
    ) -> Actor:
        """Run the host's agent executor over a snapshot of the actor's history.

        Raises unless the `Interpreter` was built with both `agent_executor`
        and `agent_root`; this runtime supplies neither.
        """
        return self.cmd(
            "agent",
            profile=profile,
            prompt=prompt,
            workspace=workspace,
            tools=tools,
            request_limit=request_limit,
            tool_call_limit=tool_call_limit,
            store=store,
            trace_store=trace_store,
        )

    # ------------------------------------------------------------------
    # conversation state
    # ------------------------------------------------------------------

    def system(self, prompt: str | pathlib.Path | dict) -> Actor:
        """Set the actor's system prompt."""
        return self.cmd("system", prompt=prompt)

    def refresh(self) -> Actor:
        """Drop the actor's history, keeping only its system message."""
        return self.cmd("refresh")

    def input_from(
        self,
        *,
        human_prompt: Optional[str] = None,
        input_from_actor: Optional[str] = None,
        input_from_file: Optional[str | pathlib.Path] = None,
        input_from_store: Optional[str] = None,
        enclosing_prompt: Optional[str | pathlib.Path] = None,
        store: Optional[str] = None,
        history: bool = True,
    ) -> Actor:
        """Take input from a human, an actor, a file or the store.

        Exactly one source should be given. Note `human_prompt=""` is a real
        value that selects the human branch, which is why the sugar method
        below defaults to `""` rather than `None`.
        """
        return self.cmd(
            "input-from",
            human_prompt=human_prompt,
            input_from_actor=input_from_actor,
            input_from_file=input_from_file,
            input_from_store=input_from_store,
            enclosing_prompt=enclosing_prompt,
            store=store,
            history=history,
        )

    def input_from_human(
        self,
        human_prompt: str = "",
        enclosing_prompt: Optional[str | pathlib.Path] = None,
        store: Optional[str] = None,
        history: bool = True,
    ) -> Actor:
        """Ask the person at the keyboard. Blocks on `input()`."""
        return self.input_from(
            human_prompt=human_prompt,
            enclosing_prompt=enclosing_prompt,
            store=store,
            history=history,
        )

    def input_from_file(
        self,
        input_from_file: str | pathlib.Path,
        enclosing_prompt: Optional[str | pathlib.Path] = None,
        store: Optional[str] = None,
        history: bool = True,
    ) -> Actor:
        return self.input_from(
            input_from_file=input_from_file,
            enclosing_prompt=enclosing_prompt,
            store=store,
            history=history,
        )

    def input_from_store(
        self,
        input_from_store: str,
        enclosing_prompt: Optional[str | pathlib.Path] = None,
        store: Optional[str] = None,
        history: bool = True,
    ) -> Actor:
        return self.input_from(
            input_from_store=input_from_store,
            enclosing_prompt=enclosing_prompt,
            store=store,
            history=history,
        )

    def input_from_actor(
        self,
        input_from_actor: str,
        enclosing_prompt: Optional[str | pathlib.Path] = None,
        store: Optional[str] = None,
        history: bool = True,
    ) -> Actor:
        return self.input_from(
            input_from_actor=input_from_actor,
            enclosing_prompt=enclosing_prompt,
            store=store,
            history=history,
        )

    # ------------------------------------------------------------------
    # store, files, output
    # ------------------------------------------------------------------

    def assign(self, var_name: str, value: str | pathlib.Path) -> Actor:
        """Set a store variable. The field is `var_name`, not `name`."""
        return self.cmd("assign", var_name=var_name, value=value)

    def write(
        self,
        path: str | pathlib.Path,
        read_from: Optional[str | pathlib.Path] = None,
        write_history: Optional[str] = None,
        overwrite: bool = False,
    ) -> Actor:
        """Write the latest output, a file, or an actor's history to `path`."""
        return self.cmd(
            "write",
            path=path,
            read_from=read_from,
            write_history=write_history,
            overwrite=overwrite,
        )

    def print(self, prompt: str | pathlib.Path | dict) -> Actor:
        """Print resolved text."""
        return self.cmd("print", prompt=prompt)

    #: `print` shadows the builtin only as an attribute; `echo` reads better.
    echo = print

    def print_latest(self, actor_name: Optional[str] = None, n: int = 0) -> Actor:
        """Print an actor's nth-latest assistant output."""
        return self.cmd("print-latest", actor_name=actor_name, n=n)

    # ------------------------------------------------------------------
    # control flow
    # ------------------------------------------------------------------

    def run_actor(
        self,
        actor_name: str,
        start_step: int = 0,
        store: Optional[str] = None,
    ) -> Actor:
        """Hand control to another actor and return it.

        Only transfers control: it pushes the callee onto the callstack and
        runs none of its steps. Drive the callee yourself, then `exit()`.
        """
        return self.cmd("run-actor", actor_name=actor_name, start_step=start_step, store=store)

    def exit(self, actor_name: Optional[str] = None) -> Actor:
        """Pop the acting actor and hand control back to its caller.

        Not a `cmd_exec` wrapper: `exec_EXIT` is a no-op in the interpreter --
        the real unwind is driven by `_exec_current_step`, which imperative
        callers never reach -- so the unwind happens here.
        """
        name = actor_name or self.working_actor.name
        self.interpreter.unwind_actor(name)
        if self.interpreter.callstack:
            self.working_actor = self.interpreter.actor_fetch(self.interpreter.callstack[-1])
        return self.working_actor

    #: The name `FlowRuntime` uses for the same operation.
    return_from = exit

    def evaluate(self, condition: str) -> bool:
        """Evaluate a scenario condition against the store.

        This is usually what an imperative caller wants instead of `cond`:
        branch with Python's own `if`.
        """
        return self.interpreter.evaluate_condition(condition)

    def cond(self, conditions: List[dict]) -> Actor:
        """Queue the first matching branch's commands.

        Queues only. `exec_COND` fills the actor's `pending_instructions` for
        the interpreter's own step loop to drain, and that loop does not run on
        this path, so call `drain_pending()` afterwards -- or use `evaluate`
        and a Python `if`.
        """
        return self.cmd("cond", conditions=conditions)

    def drain_pending(self) -> Actor:
        """Run whatever `cond` queued, until nothing is pending."""
        while True:
            actor = self.working_actor
            pending = getattr(actor, "pending_instructions", None)
            if not pending:
                return actor
            instruction = pending.pop(0)
            self.working_actor = self.interpreter.exec(cmd=instruction, actor_name=actor.name)

    def loop(self, step: int = 0) -> Actor:
        """Rewind the actor's step pointer.

        Meaningless for an imperative caller: `exec_LOOP` sets `cur_step` to
        `step - 1` and relies on the interpreter's own increment, which does
        not happen through `cmd_exec`. Use Python's `while` or `for`. Exposed
        for parity with the scenario language.
        """
        return self.cmd("loop", step=step)

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------

    def save_conversation(
        self,
        path: Optional[str | pathlib.Path] = None,
        session_id: Optional[str] = None,
        store: Optional[str] = None,
    ) -> Actor:
        """Snapshot the whole interpreter to JSON.

        Writes immediately on this path. `Runtime.save_session` does the same
        thing without going through the command layer, so it does not stop at a
        `debug>` prompt.
        """
        return self.cmd("save-conversation", path=path, session_id=session_id, store=store)

    def load_conversation(
        self,
        path: Optional[str | pathlib.Path] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Restore a saved session; returns the name of the new working actor.

        Exactly one of `path` or `session_id`. The working actor legitimately
        changes: it becomes the actor on top of the restored callstack. Use
        `Runtime.load_session` when you want the session id back instead.
        """
        if (path is None) == (session_id is None):
            raise ValueError("load_conversation takes exactly one of path or session_id.")
        self.cmd("load-conversation", path=path, session_id=session_id)
        return self.working_actor.name

import re
import os
import time
import json
import pathlib
import ast
from copy import copy, deepcopy
from typing import Callable, Dict, List, Optional, Tuple
import logging
import traceback
from dataclasses import dataclass

from .agent_api import AgentExecutor, AgentRunFailed
from .agent_integration import (
    agent_result_trace,
    build_agent_request,
    resolve_agent_workspace,
)
from .parser.commands import Cmd, CommandObj
from .rag import (
    DEFAULT_RAG_ENCLOSING_PROMPT,
    backend_kind,
    build_rag_backend,
    fill_enclosing_prompt,
    format_passages,
)
from .websearch import (
    DEFAULT_WEB_SEARCH_ENCLOSING_PROMPT,
    backend_kind as web_search_backend_kind,
    build_web_search_backend,
)
from .session import (
    CONVERSATIONS_DIR,
    default_session_path,
    new_session_id,
    read_session_file,
    restore_interpreter,
    snapshot_interpreter,
    validate_session_id,
    write_session_file,
)
from .actors import Actor 
from .data_structures import Store 

@dataclass
class Interpreter:
    """Register and add functions here"""

    def __init__(self, 
                 actors: List[Actor], 
                 main_actor_name=None,
                 store: Store=None,
                 agent_executor: AgentExecutor | None = None,
                 agent_root: str | pathlib.Path | None = None,
                 rag_backend=None,
                 conversations_dir: str | pathlib.Path | None = None,
                 web_search_backend=None):

        self.actors = dict([(actor.name, actor) for actor in actors])

        # if no store is passed, then initialize empty store
        self.store = store 
        if store is None:
            self.store = Store()

        self.agent_executor = agent_executor
        self.agent_root = None
        if (agent_executor is None) != (agent_root is None):
            raise ValueError(
                "agent_executor and agent_root must either both be configured or both be omitted"
            )
        if agent_root is not None:
            try:
                resolved_agent_root = pathlib.Path(agent_root).resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise ValueError("agent_root does not exist or cannot be resolved") from exc
            if not resolved_agent_root.is_dir():
                raise ValueError("agent_root must be an existing directory")

            try:
                executor_root = pathlib.Path(agent_executor.workspace_root).resolve(strict=True)
            except (AttributeError, OSError, RuntimeError, TypeError) as exc:
                raise ValueError(
                    "agent_executor must expose an existing workspace_root directory"
                ) from exc
            if executor_root != resolved_agent_root:
                raise ValueError(
                    "agent_root must match agent_executor.workspace_root exactly"
                )
            self.agent_root = resolved_agent_root

        # Waiting on... i.e: variables that store the 
        # return value (last output) from an actor
        self.waiting_store = {}

        # Callstack
        init_callstack = main_actor_name if main_actor_name else actors[0].name
        self.callstack = [init_callstack]
        self.main_actor_name = init_callstack

        # Session files. Repeated saves default to this id, so one run
        # updates one file instead of scattering copies for RAG to find.
        self.session_id = new_session_id()
        # Bedrock RetrieveAndGenerate session id per actor, reused across
        # that actor's `rag-generate` calls and saved with the session.
        self.rag_sessions: Dict[str, str] = {}
        # A host-built RAG backend, used by every `rag-generate` that names no
        # `backend` of its own. `None` means one is built from the environment;
        # see `resolve_rag_backend`.
        self.rag_backend = rag_backend
        # Where session files go by default, and what the local RAG backend
        # indexes, in place of `<storage_dir>/conversations`. A host that gives
        # each conversation its own scratch storage directory sets this, so
        # every conversation's sessions land in one place.
        self.conversations_dir = (
            pathlib.Path(conversations_dir) if conversations_dir is not None else None
        )
        # Built RAG backends, keyed by (kind, conversations directory).
        self.rag_backends = {}
        # A host-built web search backend, used by every
        # `web-search-and-generate` that names no `backend` of its own. `None`
        # means one is built from the environment; see
        # `resolve_web_search_backend`.
        self.web_search_backend = web_search_backend
        # Built web search backends, keyed by kind.
        self.web_search_backends = {}
        # Step bookkeeping for `save-conversation` / `load-conversation`
        # inside `exec_current`; see there.
        self._in_step = False
        self._state_restored = False
        self._deferred_saves = []

        # Wait mode. `wait_until` is a `time.monotonic()` deadline and
        # `wait_seconds` the duration the command asked for, which is what a UI
        # needs to draw a countdown. Nothing blocks on any of it: `wait_active`
        # is computed from the clock, so a wait ends on its own and there is no
        # timer thread to own. Named `wait_*` rather than `waiting` because
        # `waiting_store` is next to it and is unrelated.
        self.wait_until: Optional[float] = None
        self.wait_seconds: float = 0.0

        self.exec_map = {
            "system": self.exec_SYSTEM,
            "generate": self.exec_GENERATE,
            "agent": self.exec_AGENT,
            "input-from": self.exec_INPUT_FROM,
            "run-actor": self.exec_RUN_ACTOR,
            "refresh": self.exec_REFRESH,
            "loop": self.exec_LOOP,
            "assign": self.exec_ASSIGN,
            "write": self.exec_WRITE,
            "print": self.exec_PRINT,
            "print-latest": self.exec_PRINT_LATEST,
            "wait": self.exec_WAIT,
            "cond": self.exec_COND,
            "exit": self.exec_EXIT,
            "save-conversation": self.exec_SAVE_CONVERSATION,
            "load-conversation": self.exec_LOAD_CONVERSATION,
            "rag-generate": self.exec_RAG_GENERATE,
            "web-search-and-generate": self.exec_WEB_SEARCH_AND_GENERATE,
        }
        
        # Optional hook for streaming display. When set, called as
        # `on_generate_delta(actor_name, event)` for every non-final event a
        # `generate` instruction's pipeline call produces. `None` (the
        # default) means generation proceeds exactly as before, with no
        # streaming overhead.
        self.on_generate_delta: Optional[Callable[[str, dict], None]] = None

    @property
    def wait_remaining(self) -> float:
        """Seconds left on the current wait, 0.0 when none is running."""
        if self.wait_until is None:
            return 0.0
        return max(0.0, self.wait_until - time.monotonic())

    @property
    def wait_active(self) -> bool:
        return self.wait_remaining > 0.0

    def start_wait(self, seconds: float) -> None:
        """Begin (or replace) a wait. `seconds <= 0` cancels instead.

        `time.monotonic()` rather than `time.time()`, so a system clock
        adjustment cannot make a wait finish early or hang past its deadline.
        """
        if seconds <= 0:
            self.clear_wait()
            return
        self.wait_seconds = float(seconds)
        self.wait_until = time.monotonic() + self.wait_seconds

    def clear_wait(self) -> None:
        self.wait_until = None
        self.wait_seconds = 0.0

    def log_exec_command(self, cmd: type[CommandObj], actor_name: str) -> None:
        if not logging.getLogger().isEnabledFor(logging.DEBUG):
            return

        logging.debug(f"Actor {actor_name} executing {cmd}")
        logging.debug(f"Callstack: {self.callstack}")

    def exec(self,
             cmd: type[CommandObj], 
             actor_name: str) -> Actor:
        """
        Takes as input: the command object and the name of the acting actor
        """
        # If callstack is empty, append current acting actor to callstack
        if self.callstack == []:
            self.callstack.append(actor_name)
        
        try:
            logging.debug(
                f"\n[{actor_name} executing command {cmd}] "
            )
            exec_fn = self.exec_map[cmd.name]
            acting_actor = exec_fn(cmd, actor_name)
        except:
            print(f"ERROR IN ACTOR {actor_name} INSTRUCTION {self.actors[actor_name].cur_step}: {cmd}")
            traceback.print_exc()
            raise

        return acting_actor

    def exec_current(self):
        """Execute one interpreter step; `_exec_current_step` is the step itself.

        This wrapper holds the step-scoped state the session commands need: a
        `save-conversation` in the step is written only after the step's
        bookkeeping, and a `load-conversation` tells the step to skip that
        bookkeeping. A step that raises writes nothing.
        """
        self._state_restored = False
        self._deferred_saves = []
        self._in_step = True
        try:
            next_actor = self._exec_current_step()
            for path, session_id in self._deferred_saves:
                self._write_session(path, session_id)
        finally:
            self._in_step = False
            self._state_restored = False
            self._deferred_saves = []
        return next_actor

    def _exec_current_step(self):
        """
        Execute one interpreter step for the actor at the top of the callstack.

        The step may come from either:
        - the actor's base instruction list (`cur_step`), or
        - the actor's temporary `pending_instructions` queue, which is used by
          dynamic control flow such as `cond`

        Execution flow:
        - fetch the current actor and current instruction
        - dispatch that instruction through `self.exec(...)`
        - advance either the pending queue or the base instruction pointer
        - if an actor has finished, unwind the callstack and fill any deferred
          `run-actor` outputs into the shared store

        Return:
        - the actor that now has control after the step, or
        - `-1` when execution has fully unwound and no actor remains active
        """

        # If callstack is empty i.e: no current acting actor
        # then return exit: 0
        if self.callstack == []:
            return 0 
        
        actor_name = self.callstack[-1]

        current_actor = self.actors[actor_name]
        current_from_pending = current_actor.has_pending_instruction()
        current_instr = current_actor.get_current_instr()
        was_last_base_instruction = (
            (not current_from_pending)
            and current_actor.cur_step >= (len(current_actor.instructions) - 1)
            and current_instr.name != "loop"
        )
        
        logging.debug(f"{actor_name} executing current instruction: {current_instr}")

        acting_actor = self.exec(current_instr, actor_name)

        if self._state_restored:
            # `load-conversation` replaced every step pointer and the
            # callstack; the bookkeeping below describes the state it replaced.
            if self.callstack == []:
                return -1
            return self.actor_fetch(self.callstack[-1])

        if current_instr.name == "exit":
            acting_actor.clear_pending_instructions()
            acting_actor.return_after_pending = False
            self.actors[actor_name] = acting_actor
            self.unwind_actor(actor_name)

            if self.callstack == []:
                return -1

            return self.actor_fetch(self.callstack[-1])

        if current_from_pending:
            # Branch-local commands injected by `cond` are consumed from the
            # pending queue without advancing the actor's base instruction
            # pointer.
            current_actor.pop_pending_instruction()
        else:
            current_actor.increment_instr()

        if current_from_pending:
            # Once a pending block finishes, optionally return control to the
            # caller if this actor had already reached the end of its base
            # instruction list before entering the pending block.
            if current_actor.return_after_pending and (not current_actor.has_pending_instruction()):
                current_actor.return_after_pending = False
                self.unwind_actor(actor_name)
        elif was_last_base_instruction:
            # If the actor's final base instruction queued extra work (for
            # example via `cond`), defer callstack unwinding until that pending
            # block finishes. Otherwise unwind immediately.
            if current_actor.has_pending_instruction():
                current_actor.return_after_pending = True
            else:
                self.unwind_actor(actor_name)

        if self.callstack == []:
            return -1

        return self.actor_fetch(self.callstack[-1])

    def exec_ASSIGN(self,
                    cmd: type[CommandObj],
                    actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)
        self.store.set(cmd.var_name, self.evaluate_assignment_value(cmd.value))
        return self.actor_fetch(actor_name)

    def exec_WRITE(self,
                   cmd: type[CommandObj],
                   actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)
        acting_actor = self.actor_fetch(actor_name)
        write_path = self.resolve_actor_path(cmd.path, acting_actor)
        write_path.parent.mkdir(parents=True, exist_ok=True)

        if (cmd.read_from is not None) and (cmd.write_history is not None):
            raise ValueError("write command accepts only one of read_from or write_history.")

        if cmd.write_history is not None:
            history_actor = self.actor_fetch(cmd.write_history)
            history_actor.history.save(write_path)
            return acting_actor

        if cmd.read_from is not None:
            read_from = self.resolve_prompt_path(cmd.read_from, acting_actor)
            output_text = self.parse_prompt_object(read_from)
        else:
            output_text = acting_actor.get_latest_output()
            if isinstance(output_text, dict) and ("content" in output_text):
                output_text = output_text["content"]

        write_mode = "w" if cmd.overwrite else "a"
        with open(write_path, write_mode, encoding="utf-8") as f:
            f.write(str(output_text))

        return acting_actor

    def exec_LOOP(self,
                  cmd: type[CommandObj],
                  actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)
        
        acting_actor = self.actor_fetch(actor_name)
        logging.info(f"LOOP acting actor: {acting_actor.name}")
        if cmd.step:
            acting_actor.cur_step = cmd.step - 1
        else:
            acting_actor.cur_step = -1
        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_REFRESH(self,
                     cmd: type[CommandObj],
                     actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)

        acting_actor = self.actor_fetch(actor_name)
        acting_actor.refresh()
        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_RUN_ACTOR(self,
                       cmd: type[CommandObj],
                       actor_name: str) -> Actor:
        """Pass control over to the actor specified. NOTE: This instruction modifies the callstack, this function DOES NOT RUN any of the specified actor's instructions"""
        self.log_exec_command(cmd, actor_name)
        
        actor_run = self.actor_fetch(cmd.actor_name)
        self.callstack.append(actor_run.name)

        # if store variable defined,
        # then put it in waiting-store
        if cmd.store:
            self.waiting_store[cmd.store] = actor_run.name

        # Pass control to running actor, 
        start_step = 0
        if cmd.start_step:
            start_step = int(cmd.start_step)
        actor_run.cur_step = start_step
        
        self.actors[actor_run.name] = actor_run
        # Return RUNNING ACTOR
        return actor_run

    def exec_INPUT_FROM(self,
                        cmd: type[CommandObj],
                        actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)

        acting_actor = self.actor_fetch(actor_name)
        
        # If input_type is human (assume prompt is given as
        # string only and has already been parsed
        if cmd.human_prompt or (cmd.human_prompt == ""):
            logging.debug(f"Input from user, prompt: {cmd.human_prompt}")
            human_prompt = self.parse_prompt_object(prompt_obj=cmd.human_prompt)
            input_msg = acting_actor.prompt_user(human_prompt, store_to_history=False)
        # If input type is actor
        elif cmd.input_from_actor:
            logging.debug(f"Input from actor {cmd.input_from_actor}")
            input_msg = self.actor_fetch(cmd.input_from_actor).get_latest_output()
            input_msg = self.parse_prompt_object(input_msg)

        elif cmd.input_from_file:
            file_path = self.resolve_prompt_path(cmd.input_from_file, acting_actor)
            logging.debug(f"Input from file {file_path}")
            input_msg = self.parse_prompt_object(prompt_obj=file_path)

        # If input type is store
        elif cmd.input_from_store:
            logging.debug(f"Input from store variable {cmd.input_from_store}")
            input_msg = self.store_fetch(cmd.input_from_store)

        else:
            raise Exception("Input type unclear: neither human_prompt nor input_from_actor nor input_from_file nor input_from_store were specified in input-from command")

        # If enclosing prompt is given, enclose the input
        # or append it to end
        complete_input = input_msg
        if isinstance(input_msg, dict):
            complete_input = input_msg["content"]
        if cmd.enclosing_prompt:
            enclosing_prompt = self.parse_prompt_object(prompt_obj=cmd.enclosing_prompt)
            if "{INPUT_FROM}" in enclosing_prompt:
                complete_input = enclosing_prompt.format(INPUT_FROM=input_msg)
            else:
                complete_input = enclosing_prompt + "\n" + input_msg
        
        if cmd.store:
            self.store.set(cmd.store, complete_input)
            if cmd.history:
                acting_actor.append_to_history(complete_input)
        else:
            acting_actor.append_to_history(complete_input)
        
        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_SYSTEM(self, 
                    cmd: type[CommandObj], 
                    actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)
        
        acting_actor = self.actors[actor_name]
        prompt = self.parse_prompt_object(cmd.prompt)
        acting_actor.set_system_prompt(prompt)
        # I'm not sure how in-dictionary elements change when
        # modified outside of the dict, so I'm just gonna
        # do a reassignment here for safety
        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_GENERATE(self,
                      cmd: type[CommandObj],
                      actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)
        
        acting_actor = self.actors[actor_name]
        on_delta = self._generate_delta_hook(actor_name)
        # If prompt is given, generate using prompt
        if cmd.prompt is not None:
            prompt = self.parse_prompt_object(cmd.prompt)
            _ = acting_actor.generate(prompt=prompt, on_delta=on_delta)
        else:
            _ = acting_actor.generate(on_delta=on_delta)

        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_AGENT(self,
                   cmd: type[CommandObj],
                   actor_name: str) -> Actor:
        """Run the injected agent executor with a snapshot of actor history."""

        if self.agent_executor is None or self.agent_root is None:
            raise RuntimeError(
                "Cannot execute agent command: configure both agent_executor and agent_root"
            )

        acting_actor = self.actor_fetch(actor_name)
        task = None
        if cmd.prompt is not None:
            prompt_obj = self.resolve_prompt_path(cmd.prompt, acting_actor)
            task = self.parse_prompt_object(prompt_obj)

        workspace = resolve_agent_workspace(self.agent_root, cmd.workspace)
        request = build_agent_request(
            history=acting_actor.history.read(merged=False),
            task=task,
            workspace=workspace,
            profile=cmd.profile,
            tools=cmd.tools,
            request_limit=cmd.request_limit,
            tool_call_limit=cmd.tool_call_limit,
        )
        result = self.agent_executor.run(request)
        trace = agent_result_trace(result)

        if cmd.trace_store:
            self.store.set(cmd.trace_store, trace)

        logging.info(
            "Agent run completed: run_id=%s status=%s usage=%s changed_paths=%s",
            result.run_id,
            result.status,
            result.usage,
            list(result.changed_paths),
        )

        if result.status != "completed":
            raise AgentRunFailed(result)
        if not isinstance(result.output, str):
            raise TypeError("Agent executor output must be a string")

        acting_actor.history.add({"role": "assistant", "content": result.output})
        if cmd.store:
            self.store.set(cmd.store, result.output)

        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_SAVE_CONVERSATION(self,
                               cmd: type[CommandObj],
                               actor_name: str) -> Actor:
        """Save the whole session.

        Inside `exec_current` the file is written only after the step's
        bookkeeping, so it records the step pointers as they are after this
        command, and a load resumes on the next instruction instead of saving
        again. Called directly (as `Runtime.cmd_exec` does), it writes at once.
        """
        self.log_exec_command(cmd, actor_name)

        acting_actor = self.actor_fetch(actor_name)
        session_id = validate_session_id(cmd.session_id) if cmd.session_id else self.session_id
        path = self.session_path(acting_actor, cmd.path, session_id)
        if cmd.store:
            self.store.set(cmd.store, str(path))

        if self._in_step:
            self._deferred_saves.append((path, session_id))
        else:
            self._write_session(path, session_id)
        return acting_actor

    def exec_LOAD_CONVERSATION(self,
                               cmd: type[CommandObj],
                               actor_name: str) -> Actor:
        """Replace the whole session with a saved one, returning the actor at the top of the restored callstack."""
        self.log_exec_command(cmd, actor_name)

        acting_actor = self.actor_fetch(actor_name)
        path = self.session_path(acting_actor, cmd.path, cmd.session_id)
        self._load_session_file(path)

        if self.callstack == []:
            return acting_actor
        return self.actor_fetch(self.callstack[-1])

    def exec_RAG_GENERATE(self,
                          cmd: type[CommandObj],
                          actor_name: str) -> Actor:
        """Retrieve passages from past conversations and append one assistant message.

        A backend that `generates_natively` (Bedrock) retrieves and generates in
        one call. Otherwise the backend only retrieves, and the actor's pipeline
        generates from a copy of the history whose last user message is wrapped
        in the enclosing prompt: the passages reach the model, never the stored
        history.
        """
        self.log_exec_command(cmd, actor_name)

        acting_actor = self.actor_fetch(actor_name)
        backend = self.resolve_rag_backend(cmd.backend, acting_actor)
        filters = {"actor": cmd.actor_filter} if cmd.actor_filter else None

        prompt = None
        if cmd.prompt is not None:
            prompt = self.parse_prompt_object(self.resolve_prompt_path(cmd.prompt, acting_actor))
            if isinstance(prompt, dict) and ("content" in prompt):
                prompt = prompt["content"]
            prompt = str(prompt)
        query = self.rag_query(cmd, acting_actor, prompt)

        # The prompt joins history only once the backend call has succeeded, so
        # a missing optional dependency or an AWS error leaves the conversation
        # as it was.
        if backend.generates_natively:
            system_prompt = None
            if acting_actor.system_prompt:
                system_prompt = acting_actor.system_prompt["content"]
            result = backend.retrieve_and_generate(
                query=query,
                top_k=cmd.top_k,
                filters=filters,
                system_prompt=system_prompt,
                session_id=self.rag_sessions.get(actor_name),
                model_arn=cmd.model_arn,
            )
            if result.session_id:
                self.rag_sessions[actor_name] = result.session_id
            output, passages = result.output, result.passages
            if prompt is not None:
                acting_actor.history.add({"role": "user", "content": prompt})
            acting_actor.history.add({"role": "assistant", "content": output})
        else:
            try:
                passages = backend.retrieve(
                    query=query,
                    top_k=cmd.top_k,
                    filters=filters,
                    exclude_session_id=self.session_id,
                )
            except Exception:
                # Retrieved context improves a reply; it is not the reply. A
                # host that would rather answer without it than fail says so.
                if not cmd.fallback_on_retrieval_error:
                    raise
                logging.warning(
                    "rag-generate for %s: retrieval failed, generating without retrieved context",
                    actor_name,
                    exc_info=True,
                )
                passages = []
            # Resolved before the prompt joins history, and only when there is
            # something to wrap: nothing retrieved means the pipeline sees the
            # conversation exactly as `generate` would have sent it.
            enclosing_prompt = None
            if passages:
                enclosing_prompt = DEFAULT_RAG_ENCLOSING_PROMPT
                if cmd.enclosing_prompt is not None:
                    enclosing_prompt = self.parse_prompt_object(
                        self.resolve_prompt_path(cmd.enclosing_prompt, acting_actor)
                    )
            if prompt is not None:
                acting_actor.history.add({"role": "user", "content": prompt})

            messages = acting_actor.history.read()
            if passages:
                # An index list rather than `max(...)`: with an explicit `query`,
                # no `prompt` and only a system message in history there is no
                # user turn, and `max` of an empty sequence raises.
                user_indices = [i for i, msg in enumerate(messages) if msg["role"] == "user"]
                if user_indices:
                    last_user = user_indices[-1]
                    messages[last_user]["content"] = fill_enclosing_prompt(
                        enclosing_prompt, format_passages(passages), messages[last_user]["content"]
                    )
                else:
                    messages.append({
                        "role": "user",
                        "content": fill_enclosing_prompt(
                            enclosing_prompt, format_passages(passages), ""
                        ),
                    })
            response = acting_actor._run_pipeline(messages, self._generate_delta_hook(actor_name))
            acting_actor.history.add(response)
            output = response["content"]

        if cmd.store:
            self.store.set(cmd.store, output)
        if cmd.sources_store:
            self.store.set(cmd.sources_store, [passage.to_dict() for passage in passages])

        logging.info(
            "rag-generate for %s: backend=%s passages=%d",
            actor_name, type(backend).__name__, len(passages),
        )
        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_WEB_SEARCH_AND_GENERATE(self,
                                     cmd: type[CommandObj],
                                     actor_name: str) -> Actor:
        """Search the web and append one assistant message generated from the results.

        The results reach the model and never the stored history: the actor's
        pipeline generates from a copy of the history whose last user message is
        wrapped in the enclosing prompt, exactly as the retrieval-only path of
        `rag-generate` does.
        """
        self.log_exec_command(cmd, actor_name)

        acting_actor = self.actor_fetch(actor_name)
        backend = self.resolve_web_search_backend(cmd.backend)

        prompt = None
        if cmd.prompt is not None:
            prompt = self.parse_prompt_object(self.resolve_prompt_path(cmd.prompt, acting_actor))
            if isinstance(prompt, dict) and ("content" in prompt):
                prompt = prompt["content"]
            prompt = str(prompt)
        query = self.web_search_query(cmd, acting_actor, prompt)

        # The prompt joins history only once the search has returned, so an
        # unreachable gateway or a missing optional dependency leaves the
        # conversation as it was.
        try:
            results = backend.search(
                query=query,
                max_results=cmd.max_results,
                filters=cmd.filters,
            )
        except Exception:
            # Web results improve a reply; they are not the reply. A host that
            # would rather answer without them than fail says so.
            if not cmd.fallback_on_search_error:
                raise
            logging.warning(
                "web-search-and-generate for %s: search failed, generating without web results",
                actor_name,
                exc_info=True,
            )
            results = []

        # Resolved before the prompt joins history, and only when there is
        # something to wrap: nothing found means the pipeline sees the
        # conversation exactly as `generate` would have sent it.
        enclosing_prompt = None
        if results:
            enclosing_prompt = DEFAULT_WEB_SEARCH_ENCLOSING_PROMPT
            if cmd.enclosing_prompt is not None:
                enclosing_prompt = self.parse_prompt_object(
                    self.resolve_prompt_path(cmd.enclosing_prompt, acting_actor)
                )
        if prompt is not None:
            acting_actor.history.add({"role": "user", "content": prompt})

        # `history.read()` hands back fresh dicts, so wrapping one here reaches
        # the pipeline without touching what the actor stores.
        messages = acting_actor.history.read()
        if results:
            context = format_passages(results)
            user_indices = [i for i, msg in enumerate(messages) if msg["role"] == "user"]
            if user_indices:
                last_user = user_indices[-1]
                messages[last_user]["content"] = fill_enclosing_prompt(
                    enclosing_prompt, context, messages[last_user]["content"]
                )
            else:
                messages.append(
                    {"role": "user", "content": fill_enclosing_prompt(enclosing_prompt, context, "")}
                )
        response = acting_actor._run_pipeline(messages, self._generate_delta_hook(actor_name))
        acting_actor.history.add(response)
        output = response["content"]

        if cmd.store:
            self.store.set(cmd.store, output)
        if cmd.sources_store:
            self.store.set(cmd.sources_store, [result.to_dict() for result in results])

        logging.info(
            "web-search-and-generate for %s: backend=%s results=%d",
            actor_name, type(backend).__name__, len(results),
        )
        self.actors[actor_name] = acting_actor
        return acting_actor

    def _generate_delta_hook(self, actor_name: str):
        """`on_generate_delta` bound to `actor_name`, or `None` when it is unset."""
        if self.on_generate_delta is None:
            return None
        return lambda event: self.on_generate_delta(actor_name, event)

    def resolve_rag_backend(self, override: Optional[str], actor: Actor):
        """The backend a `rag-generate` uses.

        The host's `rag_backend` unless the command names a `backend`;
        otherwise one built from the environment (`fictive.rag.backend_kind`)
        over the actor's conversations directory, and kept for reuse.
        """
        if override is None and self.rag_backend is not None:
            return self.rag_backend
        kind = backend_kind(override)
        conversations = self.conversations_root(actor)
        key = (kind, str(conversations))
        if key not in self.rag_backends:
            self.rag_backends[key] = build_rag_backend(kind, conversations)
        return self.rag_backends[key]

    def resolve_web_search_backend(self, override: Optional[str] = None):
        """The backend a `web-search-and-generate` uses.

        The host's `web_search_backend` unless the command names a `backend`;
        otherwise one built from the environment
        (`fictive.websearch.backend_kind`), and kept for reuse.
        """
        if override is None and self.web_search_backend is not None:
            return self.web_search_backend
        kind = web_search_backend_kind(override)
        if kind not in self.web_search_backends:
            self.web_search_backends[kind] = build_web_search_backend(kind)
        return self.web_search_backends[kind]

    def web_search_query(self, cmd: type[CommandObj], actor: Actor, prompt: Optional[str]) -> str:
        """What to search on: `query`, else the prompt, else the latest user message.

        `query` is literal text, a message dict, or `var:<store-name>`. Unlike a
        prompt it is never read as a file path: it is usually someone's words.
        """
        if cmd.query is None:
            return prompt if prompt is not None else self.latest_user_message(
                actor, command="web-search-and-generate"
            )
        query = cmd.query
        if isinstance(query, dict) and ("content" in query):
            query = query["content"]
        elif isinstance(query, str) and query.startswith("var:"):
            query = self.store_fetch(query[len("var:"):])
        return str(query)

    def rag_query(self, cmd: type[CommandObj], actor: Actor, prompt: Optional[str]) -> str:
        """What `rag-generate` retrieves on: `query`, else the prompt, else the latest user message.

        `query` is literal text, a message dict, or `var:<store-name>`. Unlike a
        prompt it is never read as a file path: it is usually someone's words.
        """
        if cmd.query is None:
            return prompt if prompt is not None else self.latest_user_message(actor)
        query = cmd.query
        if isinstance(query, dict) and ("content" in query):
            query = query["content"]
        elif isinstance(query, str) and query.startswith("var:"):
            query = self.store_fetch(query[len("var:"):])
        return str(query)

    def latest_user_message(self, actor: Actor, command: str = "rag-generate") -> str:
        for msg in reversed(actor.history.read(merged=False)):
            if msg["role"] == "user":
                return msg["content"]
        raise ValueError(
            f"{command} for actor {actor.name!r} needs a prompt or a user message in its history."
        )

    def session_path(self, actor: Actor, path=None, session_id=None) -> pathlib.Path:
        """`path` resolved like `write`'s, else `<session_id>.json` in `conversations_root(actor)`."""
        if path is not None:
            return self.resolve_actor_path(path, actor)
        return self.conversations_root(actor) / default_session_path(session_id or self.session_id).name

    def conversations_root(self, actor: Actor) -> pathlib.Path:
        """Where session files go and the local RAG backend looks.

        `conversations_dir` when the host set one, else `conversations/` in the
        actor's storage directory.
        """
        if self.conversations_dir is not None:
            return self.conversations_dir
        return self.resolve_actor_path(CONVERSATIONS_DIR, actor)

    def save_session(self, path=None, session_id=None) -> pathlib.Path:
        """Save the whole session now and return the file written.

        A relative `path` resolves against the main actor's storage directory;
        without one the file goes to `conversations_root`. `session_id`
        defaults to this interpreter's, so repeated saves update one file. See
        `fictive/session.py` for the format.
        """
        session_id = validate_session_id(session_id) if session_id else self.session_id
        path = self.session_path(self.actor_fetch(self.main_actor_name), path, session_id)
        return self._write_session(path, session_id)

    def load_session(self, path=None, session_id=None) -> str:
        """Replace the whole session with a saved one and return its session id.

        Takes exactly one of `path` or `session_id`, resolved against the main
        actor's storage directory.
        """
        if (path is None) == (session_id is None):
            raise ValueError("load_session takes exactly one of path or session_id.")
        path = self.session_path(self.actor_fetch(self.main_actor_name), path, session_id)
        return self._load_session_file(path)

    def _write_session(self, path, session_id: str) -> pathlib.Path:
        written = write_session_file(path, snapshot_interpreter(self, session_id))
        self.session_id = session_id
        return written

    def _load_session_file(self, path) -> str:
        doc = read_session_file(path)
        restore_interpreter(self, doc)
        self.session_id = doc["session_id"]
        self._state_restored = True
        return self.session_id

    def exec_PRINT(self,
                   cmd: type[CommandObj],
                   actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)

        prompt = self.parse_prompt_object(cmd.prompt)
        print(prompt)
        return self.actor_fetch(actor_name)

    def exec_PRINT_LATEST(self,
                          cmd: type[CommandObj],
                          actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)

        target_actor_name = actor_name if cmd.actor_name is None else cmd.actor_name
        latest_output = self.actor_fetch(target_actor_name).get_latest_output(cmd.n)
        if isinstance(latest_output, dict) and ("content" in latest_output):
            print(latest_output["content"])
        else:
            print(latest_output)
        return self.actor_fetch(actor_name)

    def exec_WAIT(self,
                  cmd: type[CommandObj],
                  actor_name: str) -> Actor:
        """Enter wait mode for `cmd.seconds`.

        Non-blocking by design: this sets a deadline and returns, so the flow
        runs straight on and reads `wait_active` / `wait_remaining` when it
        wants to know whether the clock is still running.
        """
        self.log_exec_command(cmd, actor_name)

        self.start_wait(cmd.seconds)
        return self.actor_fetch(actor_name)

    def exec_COND(self,
                  cmd: type[CommandObj],
                  actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)

        acting_actor = self.actor_fetch(actor_name)
        selected_commands = []

        for branch in cmd.conditions:
            condition = branch.get("condition")
            is_else = condition in (None, "", "else", "ELSE")
            condition_matches = False if is_else else self.evaluate_condition(condition)
            if is_else or condition_matches:
                if is_else:
                    logging.debug("Conditional branch -> ELSE")
                else:
                    logging.debug(f"Conditional branch -> {condition}")
                selected_commands = branch.get("commands", [])
                break

        if selected_commands:
            logging.debug(f"Executing commands {selected_commands}")
            acting_actor.queue_instructions(selected_commands)
            self.actors[actor_name] = acting_actor

        return acting_actor

    def exec_EXIT(self,
                  cmd: type[CommandObj],
                  actor_name: str) -> Actor:
        self.log_exec_command(cmd, actor_name)
        return self.actor_fetch(actor_name)
    
    def exec_OTHER(self, 
                   cmd: type[CommandObj],
                   actor_name: str):
        self.log_exec_command(cmd, actor_name)
        print("TO BE DONE")
        return None

    def unwind_actor(self, actor_name: str):
        if self.callstack and (self.callstack[-1] == actor_name):
            self.callstack.pop()
        self.fill_variable(actor_name)

    def fill_variable(self, actor_name: str | None = None):
        """Replace a variable in the waiting store,
        with {var: actor output} in store"""

        for var, waiting_actor_name in list(self.waiting_store.items()):
            if (actor_name is not None) and (waiting_actor_name != actor_name):
                continue

            actor_output = self.actor_fetch(waiting_actor_name).get_latest_output()
            if isinstance(actor_output, dict) and ("content" in actor_output):
                self.store.set(var, actor_output["content"])
            else:
                self.store.set(var, actor_output)
                
            self.waiting_store.pop(var)

    def __repr__(self):
        
        s = "INTERPRETER STATE:" + ("=" * 60) + "\n"
        for actor in self.actors:
            s += actor.__repr__() + "\n"
        s += self.store.__repr__()
        s += "=" * 60
        return s

    def retrieve_actor(self, actor_name, display=False) -> Actor:
        """
        Retrieve and/or print the updated state of the actor present in
        the interpreter.
        """
        if display:
            print(self.actors[actor_name])
        return self.actors[actor_name]
    
    def parse_prompt_object(self, prompt_obj: str | dict) -> str:

        # If prompt is None, then raise an error
        if prompt_obj is None:
            raise Exception("Prompt given to Interpreter.parse_prompt_objects is None. This must be caught in the command execution function.")
        # if prompt is given as a {"role": ..., "content": ...}
        # dict, then return content
        elif isinstance(prompt_obj, dict) and ("role" in prompt_obj) and ("content" in prompt_obj):
            return prompt_obj["content"]
        # Else if prompt is given as a .txt file path 
        # (note that file path must exist), then load
        # prompt from file and return
        elif os.path.isfile(prompt_obj):
            with open(prompt_obj) as f:
                prompt_str = f.read()
                return prompt_str
        # Else if prompt is a variable name 
        # (`var:<variable name)`, then return
        # the store value with that key
        elif prompt_obj[:4] == "var:":
            varname = prompt_obj.split(":")[1]
            var_value = self.store_fetch(varname)
            return var_value
        # else just assume that the string is the prompt
        else:
            return prompt_obj

    def resolve_actor_path(self, path_value: str | pathlib.Path, actor: Actor) -> pathlib.Path:
        path = pathlib.Path(path_value)
        if path.is_absolute() or (not actor.storage_dir):
            return path
        return pathlib.Path(actor.storage_dir) / path

    def resolve_prompt_path(self, prompt_obj: str | pathlib.Path | dict, actor: Actor):
        if isinstance(prompt_obj, pathlib.Path):
            return self.resolve_actor_path(prompt_obj, actor)

        if not isinstance(prompt_obj, str):
            return prompt_obj

        if prompt_obj.startswith("var:"):
            return prompt_obj

        if os.path.isabs(prompt_obj) or os.path.isfile(prompt_obj):
            return prompt_obj

        resolved_path = self.resolve_actor_path(prompt_obj, actor)
        # A long literal prompt is not a path at all, and asking the filesystem
        # about it raises (ENAMETOOLONG) rather than answering False.
        try:
            is_file = resolved_path.is_file()
        except OSError:
            is_file = False
        if is_file:
            return resolved_path

        return prompt_obj

    def store_fetch(self, key):
        """The stored value for `key`, raising only if it was never assigned.

        Presence, not truthiness. Testing `is not None` meant a variable
        deliberately assigned `None` -- an optional argument a router left out,
        say -- raised "not in memory store", which is a different and
        misleading complaint.
        """

        if self.store.has(key):
            return self.store.get(key)
        raise Exception(f"Variable name {key} not in memory store")
    
    def actor_fetch(self, name):
        
        if name in self.actors:
            return self.actors[name]
        else:
            raise Exception(f"Actor name {name} not in theater")

    def expand_expression_placeholders(self, expression: str) -> str:
        def replace_placeholder(match):
            key = match.group(1)
            return repr(self.store_fetch(key))

        return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace_placeholder, expression)

    def evaluate_assignment_value(self, value):
        if not (isinstance(value, str) and value.startswith("python:")):
            return value

        expression = value[len("python:"):]
        return self.evaluate_safe_expression(expression, "assign value")

    def evaluate_condition(self, condition: str) -> bool:
        return bool(self.evaluate_safe_expression(condition, "cond condition"))

    def evaluate_safe_expression(self, expression: str, expression_type: str):
        context = {
            **self.store.store,
            "True": True,
            "False": False,
            "None": None,
        }

        expression = self.expand_expression_placeholders(expression)
        tree = ast.parse(expression, mode="eval")
        allowed_nodes = (
            ast.Expression,
            ast.BoolOp,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.Name,
            ast.Load,
            ast.Subscript,
            ast.Dict,
            ast.List,
            ast.Tuple,
            ast.Constant,
            ast.Slice,
            ast.And,
            ast.Or,
            ast.Not,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.Mod,
            ast.Pow,
            ast.Eq,
            ast.NotEq,
            ast.Lt,
            ast.LtE,
            ast.Gt,
            ast.GtE,
        )
        for node in ast.walk(tree):
            if not isinstance(node, allowed_nodes):
                raise ValueError(f"Unsupported expression in {expression_type}: {expression}")
            if isinstance(node, ast.Name) and (node.id not in context):
                raise ValueError(f"Unknown variable '{node.id}' in {expression_type}: {expression}")

        return eval(compile(tree, f"<{expression_type}>", "eval"), {"__builtins__": {}}, context)

import argparse
from copy import deepcopy
import json 
import transformers
import traceback

from llm_utils import pipeline_config_from_args, pipeline_from_config
from .parse_scenario_config import load_scenario_config
from .actors import ActorConfig, Actor
from .debugger import DebuggerSession
from .interpreter import Interpreter
from .data_structures import Store

transformers.logging.set_verbosity_error()


def run_single_actor(interpreter: Interpreter, actor_name: str):
    """Implement a function similar to `run_debug`, but which runs in single-actor mode. In single-actor mode, we only run a single actor i.e: (a) All INPUT_FROM commands that take input from an agent, are converted into taking input from the user, and (b) all RUN_ACTOR commands are skipped over, and (c) Any variables that do not have corresponding values in the Store are also taken as input from users"""

    # Quickest way to do this is to modify the `Interpreter` class a bit
    def exec_INPUT_FROM_single_actor(self, cmd, acting_actor_name):
        acting_actor = self.actor_fetch(acting_actor_name)

        if cmd.human_prompt or (cmd.human_prompt == ""):
            human_prompt = self.parse_prompt_object(prompt_obj=cmd.human_prompt)
            input_msg = acting_actor.prompt_user(human_prompt, store_to_history=False)
        elif cmd.input_from_actor:
            input_msg = acting_actor.prompt_user(
                f"Input for {cmd.input_from_actor}:",
                store_to_history=False,
            )
        elif cmd.input_from_file:
            file_path = self.resolve_prompt_path(cmd.input_from_file, acting_actor)
            input_msg = self.parse_prompt_object(prompt_obj=file_path)
        elif cmd.input_from_store:
            try:
                input_msg = self.store_fetch(cmd.input_from_store)
            except Exception:
                input_msg = acting_actor.prompt_user(
                    f"Value for {cmd.input_from_store}:",
                    store_to_history=False,
                )
                self.store.set(cmd.input_from_store, input_msg)
        else:
            raise Exception("Input type unclear: neither human_prompt nor input_from_actor nor input_from_file nor input_from_store were specified in input-from command")

        complete_input = input_msg
        if isinstance(input_msg, dict):
            complete_input = input_msg["content"]
        if cmd.enclosing_prompt:
            enclosing_prompt = interpreter.parse_prompt_object(cmd.enclosing_prompt)
            if "{INPUT_FROM}" in enclosing_prompt:
                complete_input = enclosing_prompt.format(INPUT_FROM=input_msg)
            else:
                complete_input = enclosing_prompt + "\n" + input_msg

        if cmd.store:
            self.store.set(cmd.store, complete_input)
        else:
            acting_actor.append_to_history(complete_input)

        self.actors[acting_actor_name] = acting_actor
        return acting_actor

    def exec_RUN_ACTOR_single_actor(self, cmd, acting_actor_name):
        return self.actor_fetch(acting_actor_name)

    def store_fetch_single_actor(self, key):
        value = self.store.get(key)
        if value is not None:
            return value

        acting_actor = self.actor_fetch(actor_name)
        value = acting_actor.prompt_user(f"Value for {key}:", store_to_history=False)
        self.store.set(key, value)
        return value

    interpreter.exec_INPUT_FROM = exec_INPUT_FROM_single_actor.__get__(interpreter, Interpreter)
    interpreter.exec_RUN_ACTOR = exec_RUN_ACTOR_single_actor.__get__(interpreter, Interpreter)
    interpreter.store_fetch = store_fetch_single_actor.__get__(interpreter, Interpreter)
    interpreter.exec_map["input-from"] = interpreter.exec_INPUT_FROM
    interpreter.exec_map["run-actor"] = interpreter.exec_RUN_ACTOR

    run_debug(interpreter, main_actor_name=actor_name)


def run_debug(interpreter: Interpreter, main_actor_name: str):
    DebuggerSession(interpreter, main_actor_name).run()
            

def run_chat(interpreter: Interpreter, main_actor_name: str):
    # Build the same session object that debug mode uses so chat mode follows
    # the exact same interpreter/callstack state transitions.
    session = DebuggerSession(interpreter, main_actor_name)

    while True:
        # Reuse the debugger's exit detection before every step. This covers
        # the same terminal states as `run_debug`, including an empty callstack
        # or any abnormal interpreter exit code stored in `working_actor`.
        exit_message = session.get_exit_message()
        if exit_message is not None:
            break

        # Advance the interpreter by exactly one step, just like the debugger's
        # `next` command would do, but automatically and without prompting the
        # user for an explicit debug command.
        session.working_actor = session.interpreter.exec_current()

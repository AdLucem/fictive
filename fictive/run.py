import argparse
from copy import deepcopy
import json 
import transformers

from .parse_scenario_config import load_scenario_config
from .pipelines import pipeline_config_from_args, pipeline_from_config
from .actors import ActorConfig, Actor
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
            raise Exception("Input type unclear: neither human_prompt nor input_from_actor nor input_from_store were specified in input-from command")

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
    def _print_help():
        print(
            "\n".join([
                "Debugger commands:",
                "  n / next            Execute the current interpreter step",
                "  h / help            Show this help message",
                "  q / quit            Exit the debugger",
                "  s / state           Show the full interpreter state",
                "  store               Show the full store",
                "  store <key>         Show one store value",
                "  actors              List actor names and current steps",
                "  a / actor           Show the main actor state",
                "  actor <name>        Show another actor state",
                "  hist [name]         Show unmerged history for an actor",
                "  latest [name] [n]   Show the nth latest assistant output (default n=0)",
                "  instr [name]        Show the current instruction for an actor",
            ])
        )

    def _actor_or_main(actor_name: str | None) -> Actor:
        return interpreter.actor_fetch(actor_name or main_actor_name)

    def _print_actor_summary():
        for name, actor in interpreter.actors.items():
            current_instr = actor.get_current_instr()
            print(f"{name}: step={actor.cur_step} current_instr={current_instr}")

    def _print_history(actor_name: str):
        actor = interpreter.actor_fetch(actor_name)
        history = actor.history.read()
        if not history:
            print(f"{actor_name} history is empty.")
            return
        print(json.dumps(history, indent=2))

    def _print_latest(actor_name: str, n: int):
        latest_output = interpreter.actor_fetch(actor_name).get_latest_output(n)
        if isinstance(latest_output, dict):
            print(json.dumps(latest_output, indent=2))
        else:
            print(latest_output)

    _print_help()

    main_actor = interpreter.actor_fetch(main_actor_name)
    working_actor = main_actor
    last_instr_flag = False 
    while True:

        if working_actor.is_last_instr():
            print(
                f"{main_actor_name} is at its last instruction step "
                f"({main_actor.cur_step}). Stopping debug run."
            )
            break 
        
        current_instr = working_actor.get_current_instr()
        print(
            f"\n[{working_actor.name} step {working_actor.cur_step}] "
            f"Next instruction: {current_instr} \n Callstack: {interpreter.callstack}"
        )

        while True:
            raw_command = input("debug> ").strip()
            if raw_command == "":
                continue

            parts = raw_command.split()
            command = parts[0].lower()

            try:
                if command in {"n", "next"}:
                    working_actor = interpreter.exec_current()
                    print()
                    break
                if command in {"h", "help"}:
                    _print_help()
                    continue
                if command in {"q", "quit"}:
                    return
                if command in {"s", "state"}:
                    print(interpreter)
                    continue
                if command == "store":
                    if len(parts) == 1:
                        print(interpreter.store)
                    else:
                        key = " ".join(parts[1:])
                        print(interpreter.store_fetch(key))
                    continue
                if command == "actors":
                    _print_actor_summary()
                    continue
                if command in {"a", "actor"} and len(parts) == 1:
                    print(_actor_or_main(None))
                    continue
                if command == "actor" and len(parts) >= 2:
                    print(interpreter.actor_fetch(" ".join(parts[1:])))
                    continue
                if command == "hist":
                    actor_name = parts[1] if len(parts) >= 2 else main_actor_name
                    _print_history(actor_name)
                    continue
                if command == "latest":
                    actor_name = working_actor.name
                    n = 0
                    if len(parts) >= 2:
                        try:
                            n = int(parts[1])
                        except ValueError:
                            actor_name = parts[1]
                    if len(parts) >= 3:
                        n = int(parts[2])
                    _print_latest(actor_name, n)
                    continue
                if command == "instr":
                    actor = _actor_or_main(parts[1] if len(parts) >= 2 else None)
                    print(actor.get_current_instr())
                    continue

                print(f"Unknown command: {raw_command}")
                _print_help()
            except IndexError:
                pass

            # except Exception as exc:
            #    print(f"Debugger error: {exc}")
    
        

def run_chat(interpreter: Interpreter, main_actor_name: str):
    main_actor = interpreter.actor_fetch(main_actor_name)
    working_actor = main_actor

    while True:
        if main_actor.is_last_instr():
            break

        current_instr = working_actor.get_current_instr()
        working_actor = interpreter.exec_current()

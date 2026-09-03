import re
import os
import time
import json
import pathlib
import ast
from copy import copy, deepcopy
from typing import Dict, List, Optional, Tuple
import logging
import traceback
from dataclasses import dataclass

from .parser.commands import Cmd, CommandObj
from .actors import Actor 
from .data_structures import Store 


@dataclass
class Interpreter:
    """Register and add functions here"""

    def __init__(self, 
                 actors: List[Actor], 
                 main_actor_name=None,
                 store: Store=None):

        self.actors = dict([(actor.name, actor) for actor in actors])

        # if no store is passed, then initialize empty store
        self.store = store 
        if store is None:
            self.store = Store()

        # Waiting on... i.e: variables that store the 
        # return value (last output) from an actor
        self.waiting_store = {}

        # Callstack
        init_callstack = main_actor_name if main_actor_name else actors[0].name
        self.callstack = [init_callstack]

        self.exec_map = {
            "system": self.exec_SYSTEM,
            "generate": self.exec_GENERATE,
            "input-from": self.exec_INPUT_FROM,
            "run-actor": self.exec_RUN_ACTOR,
            "refresh": self.exec_REFRESH,
            "loop": self.exec_LOOP,
            "assign": self.exec_ASSIGN,
            "write": self.exec_WRITE,
            "print": self.exec_PRINT,
            "print-latest": self.exec_PRINT_LATEST,
            "cond": self.exec_COND,
            "exit": self.exec_EXIT,
        }

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
        self.store.set(cmd.var_name, self.evaluate_assignment_value(cmd.value))
        return self.actor_fetch(actor_name)

    def exec_WRITE(self,
                   cmd: type[CommandObj],
                   actor_name: str) -> Actor:
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

        acting_actor = self.actor_fetch(actor_name)
        acting_actor.refresh()
        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_RUN_ACTOR(self,
                       cmd: type[CommandObj],
                       actor_name: str) -> Actor:
        """Pass control over to the actor specified. NOTE: This instruction modifies the callstack, this function DOES NOT RUN any of the specified actor's instructions"""
        
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
        
        acting_actor = self.actors[actor_name]
        # If prompt is given, generate using prompt
        if cmd.prompt is not None:
            prompt = self.parse_prompt_object(cmd.prompt)
            _ = acting_actor.generate(prompt=prompt)
        else:
            _ = acting_actor.generate()

        self.actors[actor_name] = acting_actor
        return acting_actor

    def exec_PRINT(self,
                   cmd: type[CommandObj],
                   actor_name: str) -> Actor:

        prompt = self.parse_prompt_object(cmd.prompt)
        print(prompt)
        return self.actor_fetch(actor_name)

    def exec_PRINT_LATEST(self,
                          cmd: type[CommandObj],
                          actor_name: str) -> Actor:

        target_actor_name = actor_name if cmd.actor_name is None else cmd.actor_name
        latest_output = self.actor_fetch(target_actor_name).get_latest_output(cmd.n)
        if isinstance(latest_output, dict) and ("content" in latest_output):
            print(latest_output["content"])
        else:
            print(latest_output)
        return self.actor_fetch(actor_name)

    def exec_COND(self,
                  cmd: type[CommandObj],
                  actor_name: str) -> Actor:

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
        return self.actor_fetch(actor_name)
    
    def exec_OTHER(self, 
                   cmd: type[CommandObj],
                   actor_name: str):
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
        if resolved_path.is_file():
            return resolved_path

        return prompt_obj

    def store_fetch(self, key):

        value = self.store.get(key)
        if value is not None:
            return value
        else:
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

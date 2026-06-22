import re
import os
import time
import json
import pathlib
from copy import copy, deepcopy
from typing import Dict, List, Optional, Tuple
import logging
import traceback
from enum import StrEnum, auto
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
            "print": self.exec_PRINT,
            "print-latest": self.exec_PRINT_LATEST,
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
        
        # Is it the acting actor's last instruction?
        is_last = self.actor_fetch(actor_name).is_last_instr()

        try:
            logging.debug(
                f"\n[{actor_name} executing command {cmd}] "
            )
            exec_fn = self.exec_map[cmd.name]
            acting_actor = exec_fn(cmd, actor_name)
        except:
            print(f"ERROR IN ACTOR {actor_name} INSTRUCTION {self.actors[actor_name].cur_step}: {cmd}")
            traceback.print_exc()

        # If last instruction executed, pop callstack
        if is_last:
            self.callstack.pop()
            # And check if actor output needs to be captured
            self.fill_variable()
        
        # If callstack is empty AFTER popping, return abnormal exit
        if self.callstack == []:
            return -1
        
        current_acting_actor = self.actor_fetch(self.callstack[-1])
        return current_acting_actor

    def exec_current(self):
        """
        Execute the current instruction step that the program is on.
        """

        # If callstack is empty i.e: no current acting actor
        # then return exit: 0
        if self.callstack == []:
            return 0 
        
        actor_name = self.callstack[-1]

        current_actor = self.actors[actor_name]
        current_instr = current_actor.get_current_instr()
        
        logging.debug(f"{actor_name} executing current instruction: {current_instr}")

        acting_actor = self.exec(current_instr, actor_name)
        current_actor.increment_instr()

        return acting_actor
             
    def exec_ASSIGN(self,
                    cmd: type[CommandObj],
                    actor_name: str) -> Actor:
        self.store.set(cmd.var_name, cmd.value)
        return self.actor_fetch(actor_name)

    def exec_LOOP(self,
                  cmd: type[CommandObj],
                  actor_name: str) -> Actor:
        
        acting_actor = self.actor_fetch(actor_name)
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

        # If input type is store
        elif cmd.input_from_store:
            logging.debug(f"Input from store variable {cmd.input_from_store}")
            input_msg = self.store_fetch(cmd.input_from_store)

        else:
            raise Exception("Input type unclear: neither human_prompt nor input_from_actor nor input_from_store were specified in input-from command")

        # If enclosing prompt is given, enclose the input
        # or append it to end
        complete_input = input_msg
        if isinstance(input_msg, dict):
            complete_input = input_msg["content"]
        if cmd.enclosing_prompt:
            if "{INPUT_FROM}" in cmd.enclosing_prompt:
                complete_input = cmd.enclosing_prompt.format(INPUT_FROM=input_msg)
            else:
                complete_input = cmd.enclosing_prompt + "\n" + input_msg
        
        if cmd.store:
            self.store.set(cmd.store, complete_input)
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
    
    def exec_OTHER(self, 
                   cmd: type[CommandObj],
                   actor_name: str):
        print("TO BE DONE")
        return None

    def fill_variable(self):
        """Replace a variable in the waiting store,
        with {var: actor output} in store"""

        for var, actor_name in self.waiting_store.items():
            actor_output = self.actor_fetch(actor_name).get_latest_output()
            if isinstance(actor_output, str):
                self.store.set(var, actor_output)
            elif isinstance(actor_output, dict) and ("content" in actor_output):
                self.store.set(var, actor_output["content"])
            else:
                raise Exception(f"Actor output {actor_output} in wrong format- can accept only str or dict.")
            
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
        elif isinstance(prompt_obj, dict) and ("role" in dict) and ("content" in dict):
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

    def store_fetch(self, key):

        value = self.store.get(key)
        if value:
            return value
        else:
            raise Exception(f"Variable name {key} not in memory store")
    
    def actor_fetch(self, name):
        
        if name in self.actors:
            return self.actors[name]
        else:
            raise Exception(f"Actor name {name} not in theater")
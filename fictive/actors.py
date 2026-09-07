import os
import json
import pathlib
import argparse
from typing import Callable, List, Optional
from dataclasses import dataclass
import logging
from copy import deepcopy

from llm_utils import LLMPipeline, PipelineConfig, pipeline_from_config
from .data_structures import History, Scene, Store 
from .parser.commands import CommandObj, parse_command_dict

# List of commands that automatically return false when queried for `is_last_instr`
LOOPING_INSTRUCTIONS = ["loop", "cond"]

@dataclass
class ActorConfig:
    """Configuration for a chat Actor"""

    name: str
    storage_dir: str

    actor_type: Optional[str] = None 
    source_file: Optional[str] = None 
    # Note that instructions takes precedence over source_file
    instructions: Optional[List[dict | type[CommandObj]]] = None

    pipeline_config: Optional[PipelineConfig | argparse.Namespace] = None
    pipeline: Optional[LLMPipeline] = None
    
    output_format: Optional[str] = None


class Actor:
    """
    Runtime representation of one scenario actor.

    An actor owns:
    - A name and ActorConfig
    - a parsed instruction list loaded from scenario JSON
    - `cur_step` pointer 
    - a temporary pending-instruction queue used for dynamic control flow such as `cond`
    - conversation history and optional system prompt
    - an optional LLM pipeline used only by `generate`

    The interpreter drives actors step-by-step by asking for the current
    instruction, executing it, and then advancing either the base instruction
    pointer or the pending queue.
    """

    def __init__(self, actor_cfg: ActorConfig):

        self.name = actor_cfg.name
        self.cfg = actor_cfg
        self.source = actor_cfg.source_file 
        self.history = History()

        # If source file is given, load instructions
        if actor_cfg.instructions:
            self.instructions = Actor.normalize_instructions(actor_cfg.instructions)
        elif (not actor_cfg.instructions) and self.source:
            self.instructions = Actor.parse_actor_instructions(self.source)
        # Current step of instructions that the actor is at
        self.cur_step = 0
        self.pending_instructions = []
        self.return_after_pending = False
 
        self.system_prompt = None 

        if actor_cfg.pipeline:
            self.pipeline = actor_cfg.pipeline
        elif actor_cfg.pipeline_config:
            self.pipeline = self._init_pipeline(actor_cfg.pipeline_config)
        else:
            self.pipeline = None
        
        # Storage and formatting
        self.store = True if (actor_cfg.storage_dir != None) else False
        self.storage_dir = actor_cfg.storage_dir

        if self.store and not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir, exist_ok=True)        
        self.output_format = actor_cfg.output_format

    @staticmethod
    def _init_pipeline(pipeline_cfg: PipelineConfig) -> LLMPipeline:
    
        pipeline = pipeline_from_config(pipeline_cfg)
        return pipeline

    def set_system_prompt(self, system_prompt: str | dict):
        """
           Set the system prompt. If history already exists, do not change it;
           else if history ONLY has system prompt, then change that. If history is
           empty, add system prompt.
        """
        if isinstance(system_prompt, dict):
            self.system_prompt = system_prompt
        elif isinstance(system_prompt, str):
            self.system_prompt = {
                "role": "system",
                "content": system_prompt}
        history_ls = self.history.read()

        # If history is empty, add system prompt
        if history_ls == []:
            self.history.add(self.system_prompt)
        # Else if history ONLY has system prompt, then change that
        elif (len(history_ls) == 1) and (history_ls[0]["role"] == "system"):
            self.history.set_values([self.system_prompt])

    def get_current_instr(self) -> type[CommandObj]:
        """
        Return the current instruction (from the actor instructions list)
        that the actor is on.
        """
        if self.pending_instructions:
            return self.pending_instructions[0]
        return self.instructions[self.cur_step]

    def has_pending_instruction(self) -> bool:
        return len(self.pending_instructions) > 0

    def queue_instructions(self, instructions: List[type[CommandObj]]):
        self.pending_instructions.extend(instructions)

    def pop_pending_instruction(self):
        if self.pending_instructions:
            self.pending_instructions.pop(0)

    def clear_pending_instructions(self):
        self.pending_instructions = []
    
    def increment_instr(self, n=1):
        """
        Move the actor pointer to the next instruction, or 
        (optionally) to `n` instructions after the current one.
        """
        # Increment cur_step
        self.cur_step += n
        # If overflow
        if self.cur_step >= len(self.instructions):
            # Then modulo
            self.cur_step = self.cur_step % len(self.instructions)

    @staticmethod
    def normalize_instructions(instructions: List[dict | type[CommandObj]]):
        """
        Take a list of instructions in either command or json_dict format. Leave the CommandObj ones alone, parse the json_dict ones into objects
        """

        for i, instr in enumerate(instructions):
            if isinstance(instr, dict):
                cmd = Actor.parse_instruction(instr)
                instructions[i] = cmd 
        return instructions
    
    @staticmethod
    def parse_actor_instructions(source: pathlib.Path):
        """
        Parse an actor instructions file and return a
        list of command objects
        """

        if os.path.exists(source):
            with open(source, "r", encoding="utf-8") as f:
                sequence = json.load(f)

        elif type(source) == dict:
            sequence = source

        command_objects = []
        logging.debug("Actor Instructions being parsed:")
        for s in sequence:
            cmd_obj = parse_command_dict(s)
            logging.debug(f"Parsed {s} -> {cmd_obj}")
            command_objects.append(cmd_obj)

        return command_objects

    @staticmethod
    def parse_instruction(instr: dict):
        cmd_obj = parse_command_dict(instr)
        logging.debug(f"Parsed {instr} -> {cmd_obj}")
        return cmd_obj
    
    def _run_pipeline(
        self,
        messages: list,
        on_delta: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Call `self.pipeline` for one turn and return the resulting message dict.

        Subclasses that call the pipeline directly instead of going through
        `generate` (e.g. `RoutingActor`, `FileLookupActor`) should use this
        rather than `self.pipeline.generate(...)`, so they pick up streaming
        support automatically. If `on_delta` is given, iterates
        `self.pipeline.generate_stream(messages)` and calls `on_delta` with
        every non-final event; otherwise calls `self.pipeline.generate(messages)`
        directly. Either way, the returned dict is the same shape.
        """
        if self.pipeline is None:
            raise RuntimeError(
                f"Cannot execute generate for actor {self.name!r}: no pipeline is configured"
            )

        if on_delta is None:
            return self.pipeline.generate(messages)

        response = None
        for event in self.pipeline.generate_stream(messages):
            if event["type"] == "done":
                response = event["message"]
            else:
                on_delta(event)
        if response is None:
            raise RuntimeError(
                f"Pipeline for actor {self.name!r} ended its stream without a final message."
            )
        return response

    def generate(
        self,
        prompt: Optional[dict | str] = None,
        on_delta: Optional[Callable[[dict], None]] = None,
    ):
        """Generate next message based on current history. Optionally,
        append prompt (or if file, load prompt from file and then append) to history before generating.

        If `on_delta` is given, generation goes through the pipeline's
        `generate_stream` instead of `generate`, and `on_delta` is called
        with each non-final event (`{"type": "delta"|"thinking_delta", ...}`)
        as it arrives. The final history entry is identical either way."""

        debug_msg = ("-" * 60) + "\n"

        # Process prompt
        if prompt:
            if isinstance(prompt, dict):
                self.history.add(prompt)
                prompt_display = prompt["content"]
            elif os.path.isfile(prompt):
                with open(prompt) as f:
                    prompt_str = f.read()
                    prompt_display = prompt_str
                    self.history.add({
                        "role": "user",
                        "content": prompt
                    })
            elif isinstance(prompt, str):
                prompt_display = prompt
                self.history.add({
                    "role": "user",
                    "content": prompt
                })
            debug_msg += f"Query to {self.name}: {prompt_display}\n"

        messages = self.history.read()
        response = self._run_pipeline(messages, on_delta)
        debug_msg += f"Answer from {self.name}: {response['content']}\n"
        debug_msg += ("-" * 60) + "\n"
        logging.debug(debug_msg)

        self.history.add(response)

        
    def prompt_user(self, prompt: Optional[dict | str]=None, store_to_history=True) -> str:
        
        prompt_str = "" if (prompt is None) else prompt
        user_input = input(f"{self.name}: {prompt_str} ")
        
        if store_to_history:
            # If prompt string is nonempty, I'll register it
            # as an assistant prompt
            if prompt_str != "":
                self.history.add({
                    "role": "assistant",
                    "content": prompt_str})
            self.history.add({
                "role": "user",
                "content": user_input
            })
        return user_input

    def get_latest_output(self, n=0) -> str:
        """Get n'th-indexed-from-last output ((n + 1)'th previous `assistant` message) of actor- default is zero i.e: the most recent `assistant` message"""

        prev_msg, prev_count = None, 0
        history = self.history.get_merged()

        # Read history starting from last message backwards
        for i, msg in enumerate(history[::-1]):
            if msg['role'] in ["system", 'assistant']:
                prev_count += 1
                if prev_count == (n + 1):
                    return msg
                
        if prev_msg is None:
            raise Exception(f"{n + 1}'th-from-previous message for actor {self.name} not found.")

    def get_scene(self) -> str:
        return self.history.to_scene()
            
    def __repr__(self):

        s = ""
        s += "++++++++++" + self.name + "++++++++++\n"
        s += f"Current instruction step: {self.cur_step}\n\n"
        s += self.history.__repr__()

        return s

    def append_to_history(self, message : str | dict):

        if isinstance(message, dict):
            self.history.add_role_content(role=message["role"],
                                          content=message["content"])
        # If no role given, append as user
        elif isinstance(message, str):
            self.history.add_role_content(role="user",
                                          content=message)

    def is_last_instr(self):
        """Determine if actor is on its last instruction"""
        last_in_seq = self.cur_step >= (len(self.instructions) - 1) 
        is_not_loop = self.get_current_instr().name not in LOOPING_INSTRUCTIONS

        if last_in_seq and is_not_loop:
            return True
        else:
            return False
        
    def refresh(self):
        """Delete everything except system prompt. Return deleted history"""

        old_history = self.history.get_merged()
        self.history = History()
        if (not old_history == []) and (old_history[0]["role"] == "system"):
            self.history.add({"role": "system",
                              "content": old_history[0]["content"]})

        return old_history

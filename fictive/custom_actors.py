import re
import os
import time
import json
import pathlib
from copy import deepcopy
import argparse
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass

from .actors import ActorConfig, Actor
from .commands import Cmd, CommandObj


default_scorer_format = "SCORE:\\s[12345]\\s*\\nJUSTIFICATION:\\s.*"


class Generator(Actor):
    """This Actor type returns its entire scene (i.e: all user-assistant chats EXCEPT system prompt and those bracketed in `(INSTRUCTIONS... )`) instead of latest output."""

    def __init__(self, cfg: ActorConfig):
        
        super().__init__(cfg)

    def get_latest_output(self, n=0):
        return super().get_scene()

    
class Scorer(Actor):

    def __init__(self, cfg: ActorConfig, output_format=default_scorer_format):
        
        super().__init__(cfg)
        self.pattern = re.compile(output_format)

        self.scores = []

    def generate(self, prompt = None):
        super().generate(prompt)
        result = super().get_latest_output()
        content = result["content"]

        matches = re.findall(self.pattern, content)
        num_regens = 10
        for i in range(num_regens):
            if matches:
                break
            else:
                logging.debug(f"Current output for {self.name} not matching pattern. Regenerating...")
                self.history.remove(role="assistant")
                super().generate(prompt)
                result = super().get_latest_output()
                content = result["content"]
                matches = re.findall(self.pattern, content)

        if matches:
            last_match = matches[-1]

            score_num = int(re.search(r"\d+", last_match).group())
            self.scores.append(score_num)
        else:
            raise Exception(f"Not getting properly formatted output from actor {self.name} even after {num_regens} reruns")

    def get_latest_output(self, n=0):

        return self.scores[-n]        
    

actor_class_map = {
    None: Actor,
    "scorer": Scorer,
    "generator": Generator
}

def actor_from_config(cfg: ActorConfig):

    if cfg.actor_type in actor_class_map:
        actor_class = actor_class_map[cfg.actor_type]
        return actor_class(cfg)
    else:
        raise Exception(f"Actor of type {cfg.actor_type} not defined. To define a new Actor, make it a subclass of the `fictive.Actor` class, and register it in `fictive.actor_class_map`")
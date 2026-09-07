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
from .parser.commands import Cmd, CommandObj


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

    def generate(self, prompt=None, on_delta=None):
        def extract_score(text):
            matches = re.findall(self.pattern, text)
            if matches:
                score_match = re.search(r"\d+", matches[-1])
                if score_match:
                    return int(score_match.group())

            relaxed_match = re.search(
                r"SCORE\s*:?\s*([1-5])",
                text,
                flags=re.IGNORECASE,
            )
            if relaxed_match:
                return int(relaxed_match.group(1))

            return None

        super().generate(prompt, on_delta=on_delta)
        result = super().get_latest_output()
        content = result["content"]

        score_num = extract_score(content)
        num_regens = 10
        for i in range(num_regens):
            if score_num is not None:
                break
            else:
                logging.debug(f"Current output for {self.name} not matching pattern. Regenerating...")
                self.history.remove(role="assistant")
                super().generate(prompt, on_delta=on_delta)
                result = super().get_latest_output()
                content = result["content"]
                score_num = extract_score(content)

        if score_num is not None:
            self.scores.append(score_num)
        else:
            raise Exception(
                f"Not getting properly formatted output from actor {self.name} even after {num_regens} reruns. "
                f"Last output was: {content}"
            )

    def get_latest_output(self, n=0):
        return self.scores[-(n + 1)]

    def refresh(self):
        old_history = super().refresh()
        self.scores = []
        return old_history
    

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

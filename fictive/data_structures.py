import re
import json 
from copy import copy, deepcopy 
from typing import List

BRIGHT_NAME = "\033[96;1m"
ANSI_RESET = "\033[0m"
INSTRUCTIONS_RE = re.compile(r"\(INSTRUCTIONS:.*?\)", re.DOTALL)

class History:

    def __init__(self, names={"user": "user", "assistant": "assistant"}, init_list=[]):
        """names :: mapping of roles to screen name for that role. Eg: names[user] = MyName"""

        self.names = names
        self._h = copy(init_list)

    def get_merged(self):
        """Consecutive same-role messages merged into one, as fresh dicts.

        Every append is a `copy`, including the first. Appending the stored
        dict and then merging into it edits the caller's history in place --
        which is what the long-standing comment about losing a day to this was
        describing. The copy was applied to the append-as-separate branch but
        not to the first message, so `_h[0]` was still corrupted whenever the
        second message shared its role.

        Content is joined with an f-string rather than `+=` so a non-string
        content concatenates instead of raising: the routing actor stores its
        parsed route as a dict.
        """

        merged = []
        for msg in self._h:
            role, content = msg["role"], msg["content"]
            # print(f"Currently merging: {role}, {content}")
            # Every branch appends a copy: `merged.append(msg)` would alias the
            # stored dict, so the concatenation below would edit `self._h`.
            if merged == []:
                merged.append(copy(msg))
            # Else if current role same as previous
            elif merged[-1]["role"] == role:
                # Formatting rather than `+=` so that a non-string content
                # (the routing actor stores a dict) merges instead of raising.
                merged[-1]["content"] = f"{merged[-1]['content']}\n\n {content}"
            # Else just append as separate message
            elif merged[-1]["role"] != role:
                merged.append(copy(msg))

        return merged

    def add_role_content(self, role: str, content: str):

        self._h.append({"role": role, "content": content})
     
    def remove(self, role=None, content=None):
        """Remove last (unmerged) message. If role/content given, 
           remove (up to) last message with specified role/content."""

        if (role == None) and (content == None):
            removed = self._h.pop()
        elif (role != None) and (content == None):
            temp_hist = copy(self._h)
            exists = False 
            removed = []
            cur = temp_hist.pop()
            while temp_hist:
                removed.append(cur)  
                if cur["role"] == role:
                    exists = True 
                    break
                cur = temp_hist.pop()

            if exists:
                return removed 
            else:
                raise Exception(f"Message to remove with role {role} and content {content} not found.")
        else:
            temp_hist = copy(self._h)
            exists = False 
            removed = []
            cur = temp_hist.pop()
            while temp_hist:
                removed.append(cur)  
                if (cur["role"] == role) and (cur["content"] == content):
                    exists = True 
                    break
                cur = temp_hist.pop()

            if exists:
                return removed 
            else:
                raise Exception(f"Message to remove with role {role} and content {content} not found.")

    
    def add(self, sequence: dict | List[dict]):

        if isinstance(sequence, dict):
            if ("role" in sequence) and ("content" in sequence):
                self.add_role_content(sequence["role"],
                                      sequence["content"])
            else:
                raise Exception(f"Input message {sequence} to History.add() in wrong format. It should be in 'role': role, 'content': content format")
        
        elif isinstance(sequence, list) and isinstance(sequence[0], dict):
            for msg in sequence:
                self.add(sequence=msg)
        else:
            raise Exception(f"Input message {sequence} to History.add_sequence() in wrong format.")

    def read(self, merged=True) -> List[dict]:
        """The history as fresh dicts, every `content` rendered as a string.

        Reading by default returns the merged history, i.e. with consecutive
        same-role messages combined.

        History may hold a non-string `content` -- a dict or a list, for a
        function-calling model -- and a reader wants text. Stringifying used to
        happen on the stored messages themselves, so one read flattened a
        structured content for every later reader too. The copies here are what
        keep `read` a read; see `test_read_returns_strings_only`, which has
        always asserted this and used to pass only because the one message that
        got aliased happened to hold a string.
        """

        source = self.get_merged() if merged else self._h
        out = []
        for msg in source:
            msg = copy(msg)
            if "content" in msg and not isinstance(msg["content"], str):
                msg["content"] = str(msg["content"])
            out.append(msg)
        return out
    
    def set_values(self, content: List[dict]):

        for msg in content:
            if ('role' in msg) and ('content' in msg):
                self.add(copy(msg))
            else:
                raise Exception(f"Input messages {content} to History.set_values() in wrong format.")

    def to_scene(self):
        scene = ""
        if len(self._h) < 2:
            return scene 
        
        scene += f"{self._h[1]['content']}\n"

        for msg in self._h[2:]:
            if msg["role"] == "user":
                msg_text = msg["content"].strip()
                # Remove anything between "(INSTRUCTIONS: ...)" using regex
                msg_content = INSTRUCTIONS_RE.sub("", msg_text)
                msg_content = msg_content.strip().strip("\n")
                if msg_content != "":
                    # print(f"MESSAGE_CONTENT ___{msg_content}___")  # test print
                    scene += f"\n{self.names['user']}: {msg_content}\n"

            elif msg["role"] == "assistant":
                scene += f"\n{self.names['assistant']}: {msg['content']}\n"

        scene = INSTRUCTIONS_RE.sub("", scene)
        return scene
    
    def rewind_single(self):
        print("TO BE DONE")

    def rewind(self, steps=1):
        for step in range(steps):
            if self.h == []:
                break
            else: 
                self.rewind_single()

    def save(self, filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.read(), f, indent=2)

    def get_name(self, role):
        if role in self.names:
            return self.names[role]
        else:
            return role

    def __repr__(self):

        s = "HISTORY ===================================\n"
        for msg in self._h:
            name = self.get_name(msg["role"])
            content = msg['content']
            s += f"{BRIGHT_NAME}{name}{ANSI_RESET}: {content}\n"
        s += "============================================\n"
        return s


class Scene:
    """Class to handle individual scenes
       Args:
            names :: mapping of roles to screen name for that role. Eg: names[user] = MyName
    """

    def __init__(self, names={}, actor=None, agent=None, init_scene=[]):

        if agent is not None and actor is None:
            actor = agent

        if actor:
            self.scene = History(names=names, init_list=actor.history.read()[:2])
        elif init_scene != []:
            self.scene = History(names=names, init_list=init_scene)
        else:
            self.scene = History(names=names)


    def add(self, msg, exclude_patterns=[], exclude_words=["INSTRUCTIONS"]):

        to_exclude_re = [INSTRUCTIONS_RE.search(msg["content"])]
        to_exclude_re.extend(re.search(p, msg["content"]) for p in exclude_patterns)
        to_exclude_words = [(word in msg["content"]) for word in exclude_words]
        to_exclude = to_exclude_re + to_exclude_words
        if True in to_exclude:
            return self.scene
        
        if msg["role"] in ["user", "assistant"]:
            self.scene.add(msg["role"], msg["content"])

        return self.scene

    def show(self):
        return self.scene.to_scene()

    def __repr__(self):
        return self.scene.to_scene()


class Store:
    """Assigned variable:values for a particular session"""

    def __init__(self):
        self.store = {}

    def get(self, var_name):
        if var_name in self.store:
            return self.store[var_name]
        else:
            return None 

    def has(self, var_name) -> bool:
        """Whether `var_name` was ever assigned.

        `get` cannot answer this: an unassigned variable and one deliberately
        assigned `None` both read back as `None`, so a caller that needs to
        tell "no value" from "the value is nothing" has to ask here.
        """
        return var_name in self.store

        
    def set(self, var_name, value):
        self.store[var_name] = value

    def __repr__(self):

        s = "STORE ++++\n"
        for k, v in self.store.items():
            s += f"{k} = {v}\n"
        s += "++++++++++\n"
        return s


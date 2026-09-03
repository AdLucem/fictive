import os 
import json 
import re 
from pathlib import Path

def read_multirole_prompt(text):

    lines = [l.strip().strip("\n") for l in text.split("===")]

    chat_prompt = []
    for line in lines:

        rows = line.split("\n")
        role = rows[0].strip().strip(":")
        content = "\n".join(rows[1:])

        if role not in ["system", "user", "assistant", "user_input"]:
            raise Exception(f"Role {role} not found!")

        msg = {"role": role, "content": content}
        chat_prompt.append(msg)

    return chat_prompt


def read_prompt_file(file_path: str, role=None) -> str:
    if not os.path.isfile(file_path):
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

        # if multiple turns in file
        if len(content.split("===")) > 1:
            return read_multirole_prompt(content)
        # else if single or no turns in file
        else:
            return [{"role": role, "content": content}]


def read_all_prompts(base_dir, actors):

    if not os.path.exists(base_dir):
        raise Exception(f"{base_dir} directory not found")

    all_prompts = {}
    for actor in actors:
        actor_name = actor["name"]
        actor_type = actor["type"]

        if "source" in actor:
            actor_source = os.path.join(base_dir, actor["source"])
        else:
            actor_source = base_dir

        systemfile = os.path.join(actor_source, f"{actor_name}_system.txt")
        mainfile = os.path.join(actor_source, f"{actor_name}_prompt.txt")
        sequencefile = os.path.join(actor_source, f"{actor_name}_sequence.txt")

        systemprompt = read_prompt_file(systemfile, "system")
        mainprompt = read_prompt_file(mainfile, "user")
        sequences = read_prompt_file(sequencefile)

        # steps: [[system, main], [sequences]]
        steps = []
        if sequences != []:
            steps.append(sequences)

        all_prompts[actor_name] = {"type": actor_type,
                                   "system": systemprompt,
                                   "main": mainprompt,
                                   "steps": steps}
    return all_prompts


def load_scenario_config(scenario_dir):

    schemafile = os.path.join(scenario_dir, "schema.json")

    if not os.path.isfile(schemafile):
        raise Exception(f"Error: {schemafile} schema file for scenario not found")

    with open(schemafile) as f:
        schema = json.load(f)

    # Convert actor-output-format strings to compiled regex
    actor_output_formats = {}
    if "actor_output_formats" in schema:
        for actor_name, output_format in schema["actor_output_formats"].items():
            pattern = re.compile(output_format)
            actor_output_formats[actor_name] = pattern
        schema["actor_output_formats"] = actor_output_formats

    # Load actor definitions from defn. files
    actor_defn_paths = schema.get("actor_definitions")
    if actor_defn_paths is None:
        actor_defn_paths = {}
    for actor_name in schema["actors"]:
        if actor_name not in actor_defn_paths:
            actor_defn_path = os.path.join(scenario_dir, f"{actor_name}.json")
            actor_defn_paths[actor_name] = actor_defn_path    
    
    actor_definitions = {}
    for actor_name in schema["actors"]:
        actor_defn_path = actor_defn_paths.get(actor_name)

        if not os.path.isfile(actor_defn_path):
            raise Exception(f"Error: definition file {actor_defn_path} for actor {actor_name} not found.")

        with open(actor_defn_path) as f:
            print(f"Reading {actor_name} definition")
            actor_defn = json.load(f)
            actor_definitions[actor_name] = actor_defn

    def resolve_actor_definition_paths(name, value):
        
        if value == "":
            return value
     
        elif isinstance(value, dict):
            is_agent_command = value.get("cmd") == "agent"
            return {
                key: (
                    item
                    if is_agent_command and key == "workspace"
                    else resolve_actor_definition_paths(name, item)
                )
                for key, item in value.items()
            }

        elif isinstance(value, list):
            return [resolve_actor_definition_paths(name, v) for v in value]

        elif isinstance(value, str) and not os.path.isabs(value):
            actor_base_path = Path(actor_defn_paths.get(name)).parent
            scenario_path = os.path.join(actor_base_path, value)
            if os.path.exists(scenario_path):
                return scenario_path

        return value

    actor_definitions = {
        actor_name: resolve_actor_definition_paths(actor_name, actor_defn)
        for actor_name, actor_defn in actor_definitions.items()
    }

    # Author intent    
    if "author_intent" in schema:
        author_intent = schema["author_intent"]
    else:
        author_intent = [{"condition": "True", "intent": "Continue"}]

    return schema, actor_definitions, author_intent

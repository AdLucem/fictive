import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fictive import Actor, ActorConfig, Interpreter, load_scenario_config, run_debug


class StaticPipeline:
    def generate(self, messages):
        return {
            "role": "assistant",
            "content": "This line came from the writer actor's latest output.",
        }


def main():
    scenario_dir = Path(__file__).resolve().parent / "scenario"
    os.chdir(scenario_dir)

    schema, actor_definitions, _ = load_scenario_config(str(scenario_dir))

    actors = []
    for actor_name, actor_defn in actor_definitions.items():
        actors.append(
            Actor(
                ActorConfig(
                    name=actor_name,
                    storage_dir=str(scenario_dir),
                    instructions=actor_defn,
                    pipeline=StaticPipeline(),
                )
            )
        )

    interpreter = Interpreter(actors, main_actor_name=schema["actors"][0])
    run_debug(interpreter, main_actor_name="writer")

    print("Wrote demo files:")
    for rel_path in [
        "outputs/latest.txt",
        "outputs/from-store.txt",
        "outputs/from-file.txt",
        "outputs/history.json",
    ]:
        print(f"- {scenario_dir / rel_path}")


if __name__ == "__main__":
    main()

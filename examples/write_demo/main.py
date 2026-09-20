"""Minimal `write` demo, driven from Python with the library runtime.

The same flow is expressed in `scenario/writer.json` for the JSON runtime.
Here the actor carries no instruction list at all: every command is issued
from this file through `Runtime.cmd_exec`, so ordinary Python controls the
order of the scene.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fictive import Actor, ActorConfig, Interpreter, Runtime


class StaticPipeline:
    def generate(self, messages):
        return {
            "role": "assistant",
            "content": "This line came from the writer actor's latest output.",
        }


OUTPUT_FILES = [
    "outputs/latest.txt",
    "outputs/from-store.txt",
    "outputs/from-file.txt",
    "outputs/history.json",
]


def main():
    scenario_dir = Path(__file__).resolve().parent / "scenario"

    writer = Actor(
        ActorConfig(
            name="writer",
            storage_dir=str(scenario_dir),
            pipeline=StaticPipeline(),
        )
    )
    interpreter = Interpreter([writer], main_actor_name="writer")
    runtime = Runtime(interpreter, start_actor_name="writer")

    # `write` paths are resolved against the actor's storage directory, but a
    # `system` prompt is read as given, so pass that one as a full path.
    runtime.cmd_exec("system", prompt=str(scenario_dir / "writer_system.txt"))
    runtime.cmd_exec(
        "generate",
        prompt="Generate one deterministic line for the write demo.",
    )
    runtime.cmd_exec("write", path="outputs/latest.txt", overwrite=True)

    runtime.cmd_exec("assign", var_name="store-message", value="Hello from the store.")
    runtime.cmd_exec(
        "write",
        path="outputs/from-store.txt",
        read_from="var:store-message",
        overwrite=True,
    )

    runtime.cmd_exec(
        "write",
        path="outputs/from-file.txt",
        read_from="seed.txt",
        overwrite=True,
    )
    runtime.cmd_exec("write", path="outputs/history.json", write_history="writer")

    print("Wrote demo files:")
    for rel_path in OUTPUT_FILES:
        print(f"- {scenario_dir / rel_path}")


if __name__ == "__main__":
    main()

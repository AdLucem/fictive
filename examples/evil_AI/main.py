"""The `evil_AI` scenario, played in a terminal.

`flows.py` defines the scene's control flow as Python against `fictive.Runtime`,
while `config.py` defines names, paths and arguments. The entry flow is a
generator: it yields wherever it needs a human answer, and `drive_flow` supplies
those answers from stdin. The web backend drives the same generator itself, one
resume per request -- see `fictive_scenario.py`.
"""

from pathlib import Path

from config import build_actors, main_args_parser
from flows import flow, run_single_actor_flow

from fictive import CommandExit, CommandRestart, Interpreter, Runtime, drive_flow
from llm_utils import pipeline_from_config, pipeline_config_from_args


if __name__ == "__main__":
    args = main_args_parser()

    scenario_dir = Path(args.scenario).resolve()

    # Pass the pipeline to all actors - we currently support
    # one pipeline for all actors only. A nice-to-have would be
    # optionally defining a pipeline in the actor definition
    if args.pipeline_log_level:
        args.log_level = args.pipeline_log_level

    pipeline_cfg = pipeline_config_from_args(args)
    pipeline = pipeline_from_config(pipeline_cfg)

    actors = build_actors(scenario_dir, args.storage_dir, pipeline)

    if args.mode == "actor":
        if not args.single_actor:
            raise Exception(f"Actor name to test not specified in single-actor mode")
        intp = Interpreter(actors, main_actor_name=args.single_actor)
        runtime = Runtime(intp,
                          start_actor_name=args.single_actor,
                          mode="single-actor")
        drive_flow(run_single_actor_flow(runtime, args.single_actor))
    else:
        intp = Interpreter(actors, main_actor_name="generator")
        # In "debug" mode the runtime stops for a debugger command before
        # every command it is about to execute.
        runtime = Runtime(intp, start_actor_name="generator", mode=args.mode)
        if args.mode == "debug":
            print(runtime.HELP_TEXT)

        # A registered slash command can ask for the flow to restart (after a
        # `/load`, say) or to exit; both arrive as exceptions out of `ask`.
        while True:
            try:
                drive_flow(flow(runtime))
                break
            except CommandRestart:
                continue
            except CommandExit:
                break
            except KeyboardInterrupt:
                print("\nInterrupted.")
                break

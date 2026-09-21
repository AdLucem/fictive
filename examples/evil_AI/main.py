"""The `evil_AI` scenario

Each flow in `flows.py` issues its commands one at a time through `Runtime.cmd_exec`. `flows.py` define the scene's control flows, while `config.py` defines names, variables etc.
"""

from pathlib import Path

from config import build_actors, main_args_parser
from flows import generator_flow, run_single_actor_flow

from fictive import Interpreter, Runtime
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
        run_single_actor_flow(runtime, scenario_dir, args.single_actor)
    else:
        intp = Interpreter(actors, main_actor_name="generator")
        # In "debug" mode the runtime stops for a debugger command before
        # every command it is about to execute.
        runtime = Runtime(intp, start_actor_name="generator", mode=args.mode)
        if args.mode == "debug":
            print(runtime.HELP_TEXT)
        generator_flow(runtime, scenario_dir)

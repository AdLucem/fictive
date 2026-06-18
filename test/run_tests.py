import argparse

from fictive import load_scenario_config, ActorConfig, Actor, Interpreter, run_debug
from llm_utils import pipeline_config_from_args, pipeline_from_config

def _main_args_parser():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", 
        default="sample_scenarios/evil_AI_scenario"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level (default: INFO).",
    )
    parser.add_argument(
        "--storage-dir",
        default=None,
        help="Store scenes (default: same directory as scenario definition).",
    )
    parser.add_argument(
        "--mode", 
        choices=["chat", "debug"], 
        default="chat", 
        help="Select the mode of operation: 'chat' for interactive chat, 'debug' for debugging mode."
    )
    parser.add_argument(
        "--test-actor", 
        default=None, 
        help="Specify a single ag to test. Use ONLY in instructions/test modes."
    )
    parser.add_argument(
        "--load-prev", 
        action="store_true", 
        help="Load most recent chat from chat logs directory. Used ONLY in chat/instructions modes"
    )
    parser.add_argument(
        "--load-from", 
        default=None, 
        help="Load chat from specified file. Used ONLY in chat/instructions modes. Note that this command takes precedence over `load-prev`"
    )

    subparsers = parser.add_subparsers()
    parser_pipe = subparsers.add_parser('pipeline', help='Arguments for LLM pipeline to be used by actors. Currently, we can only have one pipeline for all actors')
    parser_pipe.add_argument(
        "--model", 
        help="Huggingface model url"
    )
    parser_pipe.add_argument(
        "--pipeline-type", 
        choices=["sglang", "transformers", "SGLang", "Transformers", "mock"],
        default="sglang", 
        help="Which backend to use for running the model. If backend is sglang, then SGLang request arguments should be specified and SGLang server should be running."
    )
    parser_pipe.add_argument(
        "--pipeline-log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level for the LLM pipeline (default: same as main Actor logging level).",
    )

     # Model hyperparameters
    parser_pipe.add_argument(
        "--temperature", 
        type=float, 
        default=0.7,
        help="Sampling temperature (default: 0.7).",
    )
    parser_pipe.add_argument(
        "--max-new-tokens",
        type=int,
        default=2048,
        help="Maximum tokens to generate per response (default: 2048).",
    )
    parser_pipe.add_argument(
        "--top-p", 
        type=float, 
        default=0.9
    )
    parser_pipe.add_argument(
        "--top-k", 
        type=int, 
        default=50
    )

    # SGLang request arguments
    parser_pipe.add_argument(
        "--host",
        default="127.0.0.1",
        help=f"SGLang server host (default: 127.0.0.1).",
    )
    parser_pipe.add_argument(
        "--port",
        type=int,
        default=30000,
        help=f"SGLang server port (default: 30000).",
    )
    parser_pipe.add_argument(
        "--timeout",
        type=int,
        default=180,
        help=f"Request timeout in seconds (default: 180).",
    )

    # Transformers request arguments
    parser_pipe.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda", "mps"],
        help="Execution device.",
    )
    parser_pipe.add_argument(
        "--dtype",
        default="auto",
        choices=["auto", "float16", "bfloat16", "float32"],
        help="Torch dtype to load model with.",
    )

    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = _main_args_parser()
    
    schema, actor_definitions, author_intent = load_scenario_config(args.scenario)

    # Pass the pipeline to all actors - we currently support
    # one pipeline for all actors only. A nice-to-have would be 
    # optionally defining a pipeline in the actor definition
    pipeline_cfg = pipeline_config_from_args(args)
    pipeline = pipeline_from_config(pipeline_cfg)
    
    # Initialize actors
    actors = []
    for actor_name, actor_defn in actor_definitions.items():

        actor_config = ActorConfig(name=actor_name,
                                   storage_dir=args.scenario,
                                   instructions=actor_defn,
                                   pipeline=pipeline)
        actor = Actor(actor_config)
        actors.append(actor)

    interpreter = Interpreter(actors, main_actor_name="generator")

    if args.mode == "chat":
        print("TO BE DONE")
    elif args.mode == "debug":
        run_debug(interpreter, main_actor_name="generator")

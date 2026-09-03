import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fictive import run_debug, run_chat, run_single_actor, load_scenario_config, ActorConfig, actor_from_config, Interpreter
from llm_utils import pipeline_from_config, pipeline_config_from_args

print("HELLO")

def _main_args_parser():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", 
        default="examples/evil_AI/scenario"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level (default: INFO).",
    )
    parser.add_argument(
        "--storage-dir",
        default=str(Path.home() / ".fictive_logs" / "evil_AI"),
        help="Store scenes (default: ~/.fictive_logs/evil_AI).",
    )
    parser.add_argument(
        "--mode", 
        choices=["chat", "debug", "actor"], 
        default="chat", 
        help="Select the mode of operation: 'chat' for interactive chat, 'debug' for debugging mode, 'actor' for run-single-actor mode"
    )
    parser.add_argument(
        "--single-actor", 
        default=None, 
        help="Specify a single actor to test. Use ONLY in `actor` mode."
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
    parser.add_argument(
        "--model", 
        help="Huggingface model url",
        default="coder3101/Qwen3.5-27B-heretic"
    )
    parser.add_argument(
        "--pipeline-type", 
        choices=["sglang", "transformers", "vllm", "minimax", "SGLang", "Transformers", "VLLM", "MiniMax", "mock"],
        default="sglang", 
        help="Which backend to use for running the model. If backend is sglang, then SGLang request arguments should be specified and SGLang server should be running."
    )
    parser.add_argument(
        "--pipeline-log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level for the LLM pipeline (default: same as main Actor logging level).",
    )

     # Model hyperparameters
    parser.add_argument(
        "--temperature", 
        type=float, 
        default=0.7,
        help="Sampling temperature (default: 0.7).",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=4096,
        help="Maximum tokens to generate per response (default: 2048).",
    )
    parser.add_argument(
        "--top-p", 
        type=float, 
        default=0.9
    )
    parser.add_argument(
        "--top-k", 
        type=int, 
        default=50
    )

    # SGLang request arguments
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help=f"SGLang server host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=30000,
        help=f"SGLang server port (default: 30000).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help=f"Request timeout in seconds (default: 180).",
    )
    parser.add_argument(
        "--device",
        default="auto"
    )
    parser.add_argument(
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
    if args.pipeline_log_level:
        args.log_level = args.pipeline_log_level

    pipeline_cfg = pipeline_config_from_args(args)
    pipeline = pipeline_from_config(pipeline_cfg)
    
    # Initialize actors
    actors = []
    for actor_name, actor_defn in actor_definitions.items():

        actor_type = None
        if "_scorer" in actor_name:
            actor_type = "scorer"
        elif "generator" in actor_name:
            actor_type = "generator"

        actor_config = ActorConfig(name=actor_name,
                                   actor_type=actor_type,
                                   storage_dir=args.storage_dir,
                                   instructions=actor_defn,
                                   pipeline=pipeline)
        actor = actor_from_config(actor_config)
        actors.append(actor)

    intp = Interpreter(actors, main_actor_name="generator")

    if args.mode == "chat":
        run_chat(intp, main_actor_name="generator")
    elif args.mode == "debug":
        run_debug(intp, main_actor_name="generator")
    elif args.mode == "actor":
        if args.single_actor:
            intp = Interpreter(actors, main_actor_name=args.single_actor)
            run_single_actor(intp, actor_name=args.single_actor)
        else:
            raise Exception(f"Actor name to test not specified in single-actor mode")

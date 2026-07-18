import argparse
import pathlib
import logging
from copy import deepcopy

from llm_utils import PipelineConfig, pipeline_config_from_args, pipeline_from_config
from llm_utils.cli import parse_prompt_file


def _pipeline_args_parser():
    """Parse args if running code in the main `agents.py` file"""

    parser = argparse.ArgumentParser()

    # Pipeline arguments
    parser.add_argument(
        "--model", 
        help="Huggingface model url"
    )
    parser.add_argument(
        "--pipeline-type", 
        choices=["sglang", "transformers", "SGLang", "Transformers", "mock"],
        default="sglang", 
        help="Which backend to use for running the model. If backend is sglang, then SGLang request arguments should be specified and SGLang server should be running."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Python logging level (default: INFO).",
    )

    # Inputs
    parser.add_argument(
        "--init-prompts", 
        type=pathlib.Path, 
        required=True,
        help="Path to prompt file (JSON or [SYSTEM]/[USER] plain text format)."
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
        default=2048,
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
        default="127.0.0.1",
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

    # Transformers request arguments
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda", "mps"],
        help="Execution device.",
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

    args = _pipeline_args_parser()
    pipeline_cfg = pipeline_config_from_args(args)
    pipeline = pipeline_from_config(pipeline_cfg)

    logging.info("Reading prompts from: %s", args.init_prompts)
    
    prompt_messages = parse_prompt_file(args.init_prompts)
    system_prompt = prompt_messages[0]["content"]
    user_init = prompt_messages[1]["content"]
    init_messages = deepcopy(prompt_messages)
    messages = []
    messages.append({"role": "system", "content": system_prompt})
    if user_init != "":
        messages.append({"role": "user", "content": user_init})

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ["exit", "quit"]:
            print("Goodbye. Ending current session and starting a new one.")
            messages = deepcopy(init_messages)
            continue
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        response = pipeline.generate(messages)
        logging.info(f"Response: {response}")

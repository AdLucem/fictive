import argparse
import logging

from llm_utils.pipelines import VLLMPipeline, PipelineConfig

parser = argparse.ArgumentParser(description="Run the vLLM pipeline test.")
parser.add_argument("--model", required=True, help="Model name to use for the test.")
parser.add_argument(
    "--log-level",
    default="INFO",
    help="Logging level (for example: DEBUG, INFO, WARNING, ERROR).",
)
parser.add_argument(
    "--max-tokens",
    type=int,
    default=1024,
    help="Maximum number of tokens to generate.",
)
parser.add_argument(
    "--prompt-file",
    default=None,
    help="Path to the file containing the prompt to run.",
)

args = parser.parse_args()

logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

cfg = PipelineConfig(
    model=args.model,
    pipeline_type="vllm",
    log_level=args.log_level,
    init_prompts=args.prompt_file,
    max_new_tokens=args.max_tokens
)
pipeline = VLLMPipeline(cfg=cfg)

input_msg = [
    {
        "role": "system",
        "content": "You are a test of this VLLM pipeline."
    },
    {
        "role": "user",
        "content": "Respond with only two words: HELLO WORLD"
    }
]
response = pipeline.generate(inputs=input_msg)
print(response)
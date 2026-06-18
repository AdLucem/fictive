#!/usr/bin/env python3
"""
Deploy an SGLang model server from the command line.

This script validates a Hugging Face model (optional), then launches an
SGLang server process to serve that model.

Example:
    python src/deploy_sglang.py \
        --model meta-llama/Llama-3.1-8B-Instruct \
        --host 0.0.0.0 \
        --port 30000
"""

import argparse
import logging
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from transformers import AutoConfig, AutoTokenizer


@dataclass
class DeployConfig:
    """Runtime configuration for launching an SGLang server."""

    model: str
    host: str
    port: int
    tp_size: int
    dtype: str
    trust_remote_code: bool
    max_model_len: Optional[int]
    api_key: Optional[str]
    log_level: str
    skip_transformers_check: bool
    sglang_module: str
    extra_sglang_args: List[str]


def build_parser() -> argparse.ArgumentParser:
    """Create and return the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Deploy an SGLang server for a Hugging Face model.",
    )

    parser.add_argument(
        "--model",
        required=True,
        help="Hugging Face model id or local model path.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface for the SGLang server (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=30000,
        help="Port for the SGLang server (default: 30000).",
    )
    parser.add_argument(
        "--tp-size",
        type=int,
        default=1,
        help="Tensor parallel size (default: 1).",
    )
    parser.add_argument(
        "--dtype",
        default="auto",
        choices=["auto", "float16", "bfloat16", "float32"],
        help="Model dtype for SGLang (default: auto).",
    )
    parser.add_argument(
        "--max-model-len",
        type=int,
        default=None,
        help="Optional max model sequence length override.",
    )
    parser.add_argument(
        "--trust-remote-code",
        action="store_true",
        help="Allow execution of custom modeling code from model repo.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key for protecting SGLang endpoints.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Python logging level (default: INFO).",
    )
    parser.add_argument(
        "--skip-transformers-check",
        action="store_true",
        help="Skip model/tokenizer pre-validation with transformers.",
    )
    parser.add_argument(
        "--sglang-module",
        default="sglang.launch_server",
        help=(
            "Python module used to launch SGLang server "
            "(default: sglang.launch_server)."
        ),
    )
    parser.add_argument(
        "--extra-sglang-args",
        nargs=argparse.REMAINDER,
        default=[],
        help=(
            "Extra raw arguments forwarded to the SGLang launcher. "
            "Example: --extra-sglang-args --reasoning-parser qwen3"
        ),
    )

    return parser


def parse_args() -> DeployConfig:
    """Parse CLI args and convert them into a DeployConfig."""
    args = build_parser().parse_args()

    if args.port <= 0 or args.port > 65535:
        raise ValueError("--port must be between 1 and 65535.")
    if args.tp_size <= 0:
        raise ValueError("--tp-size must be >= 1.")
    if args.max_model_len is not None and args.max_model_len <= 0:
        raise ValueError("--max-model-len must be > 0 when provided.")

    return DeployConfig(
        model=args.model,
        host=args.host,
        port=args.port,
        tp_size=args.tp_size,
        dtype=args.dtype,
        trust_remote_code=args.trust_remote_code,
        max_model_len=args.max_model_len,
        api_key=args.api_key,
        log_level=args.log_level,
        skip_transformers_check=args.skip_transformers_check,
        sglang_module=args.sglang_module,
        extra_sglang_args=args.extra_sglang_args,
    )


def configure_logging(level: str) -> None:
    """Configure global logging format and level."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def should_enable_trust_remote_code(model_id_or_path: str) -> bool:
    """Return True when the model family commonly requires remote code."""
    model_name = model_id_or_path.lower()
    return "Qwen/" in model_name or model_name.startswith("Qwen")


def validate_model_with_transformers(cfg: DeployConfig) -> None:
    """Ensure the model and tokenizer are loadable before server launch."""
    if cfg.skip_transformers_check:
        logging.info("Skipping transformers model/tokenizer pre-check.")
        return

    # If model path is local and missing, fail early with a clear error.
    if Path(cfg.model).exists() or cfg.model.startswith((".", "/")):
        model_path = Path(cfg.model)
        if not model_path.exists():
            raise FileNotFoundError(f"Local model path not found: {model_path}")

    trust_remote_code = cfg.trust_remote_code or should_enable_trust_remote_code(cfg.model)
    if trust_remote_code and not cfg.trust_remote_code:
        logging.info(
            "Auto-enabling trust_remote_code for model family: %s",
            cfg.model,
        )

    logging.info("Validating model config with transformers: %s", cfg.model)
    AutoConfig.from_pretrained(
        cfg.model,
        trust_remote_code=trust_remote_code,
    )

    logging.info("Validating tokenizer with transformers: %s", cfg.model)
    AutoTokenizer.from_pretrained(
        cfg.model,
        trust_remote_code=trust_remote_code,
    )


def build_sglang_command(cfg: DeployConfig) -> List[str]:
    """Build the command that launches the SGLang server."""
    cmd: List[str] = [
        sys.executable,
        "-m",
        cfg.sglang_module,
        "--model-path",
        cfg.model,
        "--host",
        cfg.host,
        "--port",
        str(cfg.port),
        "--tp-size",
        str(cfg.tp_size),
        "--dtype",
        cfg.dtype,
    ]

    trust_remote_code = cfg.trust_remote_code or should_enable_trust_remote_code(cfg.model)
    if trust_remote_code and not cfg.trust_remote_code:
        logging.info(
            "Auto-enabling --trust-remote-code for model family: %s",
            cfg.model,
        )

    if trust_remote_code:
        cmd.append("--trust-remote-code")
    if cfg.max_model_len is not None:
        cmd.extend(["--max-model-len", str(cfg.max_model_len)])
    if cfg.api_key:
        cmd.extend(["--api-key", cfg.api_key])
    if cfg.extra_sglang_args:
        cmd.extend(cfg.extra_sglang_args)

    return cmd


def launch_server(cmd: List[str]) -> int:
    """Launch server process and forward termination signals cleanly."""
    logging.info("Launching SGLang server:\n%s", " ".join(shlex.quote(x) for x in cmd))

    process = subprocess.Popen(cmd)

    def _forward_signal(sig: int, _frame: object) -> None:
        logging.warning("Received signal %s, forwarding to server process...", sig)
        if process.poll() is None:
            process.send_signal(sig)

    signal.signal(signal.SIGINT, _forward_signal)
    signal.signal(signal.SIGTERM, _forward_signal)

    return process.wait()


def main() -> None:
    """Entry point for script execution."""
    try:
        cfg = parse_args()
        configure_logging(cfg.log_level)
        validate_model_with_transformers(cfg)
        cmd = build_sglang_command(cfg)
        exit_code = launch_server(cmd)
        if exit_code != 0:
            logging.error("SGLang server exited with non-zero status: %d", exit_code)
            sys.exit(exit_code)
    except Exception as exc:
        logging.exception("Failed to deploy SGLang server: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()

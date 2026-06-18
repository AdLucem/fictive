import argparse
from dataclasses import dataclass
from typing import Optional
from pathlib import Path 


@dataclass
class RequestConfig:
    """Runtime configuration for chat requests."""

    model: str
    host: str
    port: int
    temperature: float
    max_new_tokens: int
    timeout: int
    log_level: str
    prompt_file: Optional[Path] = None


def args_to_request_config(args: argparse.Namespace) -> RequestConfig:
    """Validate fields and create request config from args"""

    if args.port <= 0 or args.port > 65535:
        raise ValueError("--port must be between 1 and 65535.")
    if args.max_tokens <= 0:
        raise ValueError("--max-tokens must be > 0.")
    if args.timeout <= 0:
        raise ValueError("--timeout must be > 0.")

    return RequestConfig(
        model=args.model,
        host=args.host,
        port=args.port,
        temperature=args.temperature,
        max_new_tokens=args.max_tokens,
        timeout=args.timeout,
        log_level=args.log_level,
        prompt_file=args.prompt_file
    )
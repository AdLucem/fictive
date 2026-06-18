import argparse
import logging
import json
from pathlib import Path
from typing import Optional, List, Dict, Tuple  

from llm_utils import RequestConfig, sglang_chat_completion, sglang_chat_completion_batch, args_to_request_config

from llm_utils.request_sglang import configure_logging, build_base_url


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 30000
DEFAULT_TIMEOUT = 120


def build_parser() -> argparse.ArgumentParser:
    """Create and return the CLI parser."""
    parser = argparse.ArgumentParser(
        description="Read prompts from a file and chat with an SGLang server.",
    )
    parser.add_argument(
        "prompt_file",
        help="Path to prompt file (JSON or [SYSTEM]/[USER] plain text format).",
    )
    parser.add_argument(
        "--model",
        default="default",
        help="Model name exposed by server (default: default).",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"SGLang server host (default: {DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"SGLang server port (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key used as Bearer token.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.7,
        help="Sampling temperature (default: 0.7).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=1024,
        help="Maximum tokens to generate per response (default: 1024).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Python logging level (default: INFO).",
    )
    return parser


def run_chat_loop(cfg: RequestConfig, system_prompt: str, user_prompt: str) -> None:
    """Start a minimal interactive chat session."""
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]

    # Send the initial user prompt from file first.
    messages.append({"role": "user", "content": user_prompt})
    assistant_reply = sglang_chat_completion(cfg, messages)
    messages.append(assistant_reply)

    print("\nAssistant:")
    print(assistant_reply["content"])

    print("\nInteractive chat started. Type 'exit' or 'quit' to stop.")
    while True:
        user_text = input("\nYou: ").strip()
        if user_text.lower() in {"exit", "quit"}:
            print("Ending chat session.")
            return
        if not user_text:
            continue

        messages.append({"role": "user", "content": user_text})
        assistant_reply = sglang_chat_completion(cfg, messages)
        messages.append(assistant_reply)

        print("\nAssistant:")
        print(assistant_reply["content"])


def parse_prompt_file(path: str) -> Tuple[str, str]:
    """Return (system_prompt, user_prompt) from JSON or sectioned text file."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    raw = file_path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError("Prompt file is empty.")

    # Try JSON first.
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            system_prompt = str(payload.get("system", "")).strip()
            user_prompt = str(payload.get("user", "")).strip()
            if system_prompt and user_prompt:
                return system_prompt, user_prompt
    except json.JSONDecodeError:
        pass

    # Fallback: plain text with explicit section markers.
    system_prompt, user_prompt = parse_sectioned_text(raw)
    if not system_prompt or not user_prompt:
        raise ValueError(
            "Could not parse prompt file. Use JSON with keys 'system' and 'user', "
            "or text sections [SYSTEM] and [USER]."
        )
    return system_prompt, user_prompt


def parse_sectioned_text(content: str) -> Tuple[str, str]:
    """Parse [SYSTEM]/[USER] sections from plain text content."""
    upper = content.upper()
    system_tag = "[SYSTEM]"
    user_tag = "[USER]"

    system_index = upper.find(system_tag)
    user_index = upper.find(user_tag)
    if system_index == -1 or user_index == -1:
        return "", ""
    if user_index < system_index:
        return "", ""

    system_body_start = system_index + len(system_tag)
    system_prompt = content[system_body_start:user_index].strip()
    user_prompt = content[user_index + len(user_tag):].strip()
    return system_prompt, user_prompt


def main() -> None:
    """CLI entry point."""
    try:
        args = build_parser().parse_args()
        cfg = args_to_request_config(args)
        configure_logging(cfg.log_level)

        logging.info("Reading prompts from: %s", cfg.prompt_file)
        system_prompt, user_prompt = parse_prompt_file(cfg.prompt_file)

        logging.info("Connecting to SGLang server at %s", build_base_url(cfg))
        run_chat_loop(cfg, system_prompt, user_prompt)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as exc:
        logging.exception("Failed to run SGLang request client: %s", exc)
        raise SystemExit(1)
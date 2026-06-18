#!/usr/bin/env python3
"""
Send chat requests to an SGLang server.

This script:
1) Reads an initial system and user prompt from a file.
2) Sends the prompts to an SGLang server using its OpenAI-compatible API.
3) Starts a basic interactive chat loop.

Supported prompt-file formats:
- JSON file with keys: {"system": "...", "user": "..."}
- Plain text file with sections:
    [SYSTEM]
    ...system prompt...
    [USER]
    ...user prompt...
"""

import argparse
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests

from .llm_configs import RequestConfig


def configure_logging(level: str) -> None:
    """Configure global logger."""
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )




def build_base_url(cfg: RequestConfig) -> str:
    """Build base URL for OpenAI-compatible SGLang endpoint."""
    return f"http://{cfg.host}:{cfg.port}/v1"


def parse_assistant_message(content: str) -> Dict[str, str]:
    """Split assistant output into thinking and visible content when present."""

    message = {"role": "assistant"}

    start = content.find("<think>")
    if start == -1:
        end = content.find("</think>")
        if end == -1:
            message["content"] = content.strip()
            return message

        thinking = content[:end].strip()
        visible_content = content[end + len("</think>") :]

        if thinking:
            message["thinking"] = thinking
        message["content"] = visible_content.strip()
        return message

    think_start = start + len("<think>")
    end = content.find("</think>", think_start)
    if end == -1:
        message["content"] = content.strip()
        return message

    thinking = content[think_start:end].strip()
    visible_content = f"{content[:start]}{content[end + len('</think>'):]}"

    if thinking:
        message["thinking"] = thinking
    message["content"] = visible_content.strip()
    return message


def sglang_chat_completion(
    cfg: RequestConfig,
    messages: List[Dict[str, str]],
) -> Dict[str, str]:
    """Send one chat completion request and return assistant message."""
    url = f"{build_base_url(cfg)}/chat/completions"
    headers = {"Content-Type": "application/json"}

    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_new_tokens,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": False}
        }
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=cfg.timeout)
    resp.raise_for_status()

    data = resp.json()
    try:
        return parse_assistant_message(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected API response shape: {data}") from exc


def sglang_chat_completion_batch(
    cfg: RequestConfig,
    requests_messages: List[List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """Send multiple chat completion requests and return assistant messages."""
    outputs: List[Dict[str, str]] = []
    for messages in requests_messages:
        outputs.append(sglang_chat_completion(cfg, messages))
    return outputs




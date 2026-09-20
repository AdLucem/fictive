"""Any Bedrock model through the Converse API, shaped like an ``llm_utils`` pipeline.

``BedrockPipeline`` uses the Anthropic SDK's ``AnthropicBedrock`` client, which
only speaks the Anthropic Messages API and therefore only works with Anthropic
models on Bedrock.  This pipeline uses boto3's ``bedrock-runtime``
``converse`` / ``converse_stream`` operations, which work with every model
Bedrock hosts: Amazon Nova, Titan, Llama, Mistral, etc.

The contract is the same duck-typed interface the rest of the flow uses:

- ``model_name`` -- a readable attribute.
- ``generate(inputs) -> dict`` with ``role`` and ``content``.
- ``generate_stream(inputs)`` -- yields ``{"type": "delta", "text": ...}``
  and ends with exactly one ``{"type": "done", "message": ...}``.

The boto3 client is built lazily, so this module imports and this class
constructs with no credentials, no network and no boto3 installed.
"""

from __future__ import annotations

import os
from typing import Any, Iterator, Optional


CONVERSE_REGION_ENV = "BEDROCK_REGION"
CONVERSE_PROFILE_ENV = "BEDROCK_PROFILE"

EARLIER_CONTEXT_PROMPT = "Earlier in this conversation:"
CONTINUE_PROMPT = "Continue."


class ConverseUnusableResponse(RuntimeError):
    """The model answered, but with nothing the flow can use."""


def converse_request_messages(
    messages: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split a flow history into Converse API ``system`` and ``messages``.

    Returns ``(system_blocks, turns)`` where ``system_blocks`` is a list of
    ``{"text": ...}`` dicts (the Converse API's system format) and ``turns``
    is a list of ``{"role": ..., "content": [{"text": ...}]}`` dicts.
    """
    system_parts: list[str] = []
    turns: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "")
        if not content.strip():
            continue
        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            turns.append({"role": role, "content": [{"text": content}]})

    if turns and turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": [{"text": EARLIER_CONTEXT_PROMPT}]})
    if not turns or turns[-1]["role"] == "assistant":
        turns.append({"role": "user", "content": [{"text": CONTINUE_PROMPT}]})

    system_blocks = [{"text": t} for t in system_parts] if system_parts else []
    return system_blocks, turns


def _as_messages(inputs: Any) -> list[dict]:
    """The same input shapes ``llm_utils.LLMPipeline.parse_inputs`` accepts."""
    if isinstance(inputs, str):
        return [{"role": "user", "content": inputs}]
    if isinstance(inputs, list) and inputs and isinstance(inputs[0], str):
        return [{"role": "user", "content": text} for text in inputs]
    return list(inputs)


def _is_batch(inputs: Any) -> bool:
    return isinstance(inputs, list) and bool(inputs) and isinstance(inputs[0], list)


def _extract_text(output: dict) -> str:
    """Pull the assistant text out of a Converse API ``output`` dict."""
    message = output.get("output", {}).get("message", {})
    parts = []
    for block in message.get("content", []):
        if "text" in block:
            parts.append(block["text"])
    return "\n".join(parts).strip()


class ConversePipeline:
    """Any Bedrock model through boto3's Converse API."""

    def __init__(
        self,
        model: str,
        *,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        max_tokens: int = 4096,
        timeout: float = 180,
        client: Any = None,
    ):
        self.model_name = model
        self.region = region or os.environ.get(CONVERSE_REGION_ENV)
        self.profile = profile or os.environ.get(CONVERSE_PROFILE_ENV)
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = client

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise ImportError(
                    "The Converse pipeline needs boto3. "
                    "Install it with: pip install boto3"
                ) from exc
            kwargs: dict[str, Any] = {}
            if self.region:
                kwargs["region_name"] = self.region
            if self.profile:
                import botocore.session
                session = boto3.Session(profile_name=self.profile)
                self._client = session.client(
                    "bedrock-runtime",
                    config=Config(read_timeout=int(self.timeout)),
                    **kwargs,
                )
            else:
                self._client = boto3.client(
                    "bedrock-runtime",
                    config=Config(read_timeout=int(self.timeout)),
                    **kwargs,
                )
        return self._client

    def _params(self, inputs: Any) -> dict:
        system_blocks, turns = converse_request_messages(_as_messages(inputs))
        params: dict[str, Any] = {
            "modelId": self.model_name,
            "messages": turns,
            "inferenceConfig": {"maxTokens": self.max_tokens},
        }
        if system_blocks:
            params["system"] = system_blocks
        return params

    def generate(self, inputs: Any) -> dict:
        if _is_batch(inputs):
            return [self.generate(messages) for messages in inputs]
        response = self.client.converse(**self._params(inputs))
        text = _extract_text(response)
        if not text:
            stop = response.get("stopReason", "unknown")
            raise ConverseUnusableResponse(f"Model returned no text (stopReason={stop}).")
        return {"role": "assistant", "content": text}

    def generate_stream(self, inputs: Any) -> Iterator[dict]:
        if _is_batch(inputs):
            raise TypeError("ConversePipeline.generate_stream does not accept batched inputs.")
        response = self.client.converse_stream(**self._params(inputs))
        collected: list[str] = []
        for event in response["stream"]:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    collected.append(delta["text"])
                    yield {"type": "delta", "text": delta["text"]}
        text = "".join(collected).strip()
        if not text:
            raise ConverseUnusableResponse("Model returned no text in stream.")
        yield {"type": "done", "message": {"role": "assistant", "content": text}}

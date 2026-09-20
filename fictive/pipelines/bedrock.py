"""Claude on Amazon Bedrock, shaped like an `llm_utils` pipeline.

Not `llm_utils.AnthropicAPIPipeline`: that one always sends `temperature`,
which current Claude models reject, and it cannot stream. It also talks to
Anthropic's own API, not Bedrock.

The contract this answers, which is all `Actor._run_pipeline` ever asks for:

- `model_name` -- a readable attribute that must not raise.
- `generate(inputs) -> dict` with `role` and `content`, `thinking` optional.
  A batch input (a list of message lists) returns a list of those dicts.
- `generate_stream(inputs)` -- yields `{"type": "delta"|"thinking_delta",
  "text": ...}` and ends with exactly one `{"type": "done", "message": ...}`.
  `Actor._run_pipeline` raises if that final event never arrives.

Both methods stream, so a long answer never runs into an HTTP timeout. That
matters more here than on the direct API, because extended thinking on a large
budget regularly outruns a default read timeout.

The AWS client is built lazily, so this module imports and this class
constructs with no credentials, no network and no boto3 installed.
"""

from typing import Any, Iterator, Optional

from . import (
    BEDROCK_MAX_TOKENS_ENV,
    BEDROCK_MODEL_ENV,
    BEDROCK_PROFILE_ENV,
    BEDROCK_REGION_ENV,
    BEDROCK_THINKING_ENV,
    DEFAULT_BEDROCK_MODEL,
    DEFAULT_MAX_TOKENS,
    MIN_THINKING_BUDGET,
    _env_int,
)

import os

#: Stands in for the user turn Claude requires before a history's first
#: assistant turn -- an actor that refreshes into a history starting with its
#: own summary lands here -- and after its last one, since current Claude
#: models reject a request that ends on an assistant message. A fictive actor
#: reaches that second shape easily: `input-from` with `store` set appends
#: nothing to history, so a `generate` straight after a `generate` would send a
#: history whose last turn is the assistant's.
EARLIER_CONTEXT_PROMPT = "Earlier in this conversation:"
CONTINUE_PROMPT = "Continue."


def bedrock_request_messages(messages: list[dict]) -> tuple[Optional[str], list[dict]]:
    """Split an actor history into Claude's `system` string and `messages` list.

    Fictive histories carry system prompts as `role: "system"` entries, which
    the Messages API takes as a top-level field rather than a turn. Empty turns
    are dropped, because the API rejects empty text.
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
            turns.append({"role": role, "content": content})

    if turns and turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": EARLIER_CONTEXT_PROMPT})
    if not turns or turns[-1]["role"] == "assistant":
        turns.append({"role": "user", "content": CONTINUE_PROMPT})
    return ("\n\n".join(system_parts) or None), turns


def _as_messages(inputs: Any) -> list[dict]:
    """The same input shapes `llm_utils.LLMPipeline.parse_inputs` accepts."""
    if isinstance(inputs, str):
        return [{"role": "user", "content": inputs}]
    if isinstance(inputs, list) and inputs and isinstance(inputs[0], str):
        return [{"role": "user", "content": text} for text in inputs]
    return list(inputs)


def _is_batch(inputs: Any) -> bool:
    return isinstance(inputs, list) and bool(inputs) and isinstance(inputs[0], list)


class BedrockUnusableResponse(RuntimeError):
    """Bedrock answered, but with nothing an actor can use: a refusal or no text."""


def _assistant_message(message: Any) -> dict:
    """Claude's final message in the shape the other pipelines return."""
    if message.stop_reason == "refusal":
        raise BedrockUnusableResponse("Claude declined the request.")
    text = "\n".join(block.text for block in message.content if block.type == "text").strip()
    if not text:
        raise BedrockUnusableResponse(
            f"Claude returned no text (stop_reason={message.stop_reason})."
        )
    thinking = "\n".join(
        block.thinking for block in message.content if block.type == "thinking"
    ).strip()
    return {"role": "assistant", "thinking": thinking, "content": text}


class BedrockPipeline:
    """Claude on Amazon Bedrock through the Anthropic SDK's Bedrock client."""

    def __init__(
        self,
        model: Optional[str] = None,
        *,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        max_tokens: Optional[int] = None,
        thinking_budget: Optional[int] = None,
        timeout: float = 180,
        client: Any = None,
    ):
        self.model_name = model or os.environ.get(BEDROCK_MODEL_ENV) or DEFAULT_BEDROCK_MODEL
        self.region = region or os.environ.get(BEDROCK_REGION_ENV)
        self.profile = profile or os.environ.get(BEDROCK_PROFILE_ENV)
        self.max_tokens = max_tokens or _env_int(BEDROCK_MAX_TOKENS_ENV) or DEFAULT_MAX_TOKENS
        self.thinking_budget = (
            thinking_budget if thinking_budget is not None else _env_int(BEDROCK_THINKING_ENV)
        )
        self.timeout = timeout
        self._client = client

        if self.thinking_budget is not None:
            # Caught here rather than at the first call, and not fixed by
            # quietly raising max_tokens, which would be a cost surprise.
            if self.thinking_budget < MIN_THINKING_BUDGET:
                raise ValueError(
                    f"A thinking budget must be at least {MIN_THINKING_BUDGET}, "
                    f"got {self.thinking_budget}."
                )
            if self.max_tokens <= self.thinking_budget:
                raise ValueError(
                    f"max_tokens ({self.max_tokens}) must be greater than the thinking "
                    f"budget ({self.thinking_budget})."
                )

    @property
    def client(self):
        if self._client is None:
            try:
                from anthropic import AnthropicBedrock
            except ImportError as exc:
                raise ImportError(
                    "The Bedrock pipeline needs the anthropic SDK's Bedrock client. "
                    "Install it with: pip install 'fictive[bedrock]'"
                ) from exc
            kwargs: dict = {"timeout": self.timeout}
            # Passed only when set: the SDK infers the region from AWS_REGION,
            # AWS_DEFAULT_REGION or the profile, and an empty string defeats that.
            if self.region:
                kwargs["aws_region"] = self.region
            if self.profile:
                kwargs["aws_profile"] = self.profile
            self._client = AnthropicBedrock(**kwargs)
        return self._client

    def _params(self, inputs: Any) -> dict:
        system, turns = bedrock_request_messages(_as_messages(inputs))
        params: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "messages": turns,
        }
        if system:
            params["system"] = system
        if self.thinking_budget:
            params["thinking"] = {"type": "enabled", "budget_tokens": self.thinking_budget}
        return params

    def generate(self, inputs: Any) -> Any:
        if _is_batch(inputs):
            return [self.generate(messages) for messages in inputs]
        with self.client.messages.stream(**self._params(inputs)) as stream:
            final = stream.get_final_message()
        return _assistant_message(final)

    def generate_stream(self, inputs: Any) -> Iterator[dict]:
        if _is_batch(inputs):
            # Without this the batch falls through to `_as_messages`, which
            # returns a list of lists and earns an opaque 400 from the API.
            raise TypeError("BedrockPipeline.generate_stream does not accept batched inputs.")
        with self.client.messages.stream(**self._params(inputs)) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if event.delta.type == "thinking_delta":
                    yield {"type": "thinking_delta", "text": event.delta.thinking}
                elif event.delta.type == "text_delta":
                    yield {"type": "delta", "text": event.delta.text}
            final = stream.get_final_message()
        yield {"type": "done", "message": _assistant_message(final)}

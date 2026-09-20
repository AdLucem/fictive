"""Model backends that plug into an actor as its pipeline.

An actor's pipeline is duck-typed: `Actor` takes whatever object
`ActorConfig(pipeline=...)` hands it and only ever calls `model_name`,
`generate` and `generate_stream` on it. So a backend here does not subclass
`llm_utils.LLMPipeline`; it just answers that contract.

- `bedrock` (`fictive.pipelines.bedrock`): Claude on Amazon Bedrock, through
  the Anthropic SDK's `AnthropicBedrock` client. Credentials and region come
  from the standard AWS chain unless overridden.

The backend module is not imported until one is built, so importing `fictive`
never imports `boto3` or the SDK's Bedrock client. This module reads
`os.environ` but never loads a `.env` file; that is an entry point's job.
"""

import os
from typing import Any, Optional

#: A Bedrock inference profile id, not a bare model id -- Bedrock rejects
#: `anthropic.claude-sonnet-4-6` and wants `us.anthropic.claude-sonnet-4-6`.
#: The geography prefix is region-family specific: a deployment in `eu-*`
#: needs `eu.`, not `us.`.
BEDROCK_MODEL_ENV = "BEDROCK_MODEL_ID"
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-6"

BEDROCK_REGION_ENV = "BEDROCK_REGION"
BEDROCK_PROFILE_ENV = "BEDROCK_PROFILE"
BEDROCK_MAX_TOKENS_ENV = "BEDROCK_MAX_TOKENS"
BEDROCK_THINKING_ENV = "BEDROCK_THINKING_BUDGET"

DEFAULT_MAX_TOKENS = 16384
#: Anthropic's floor for an extended-thinking budget.
MIN_THINKING_BUDGET = 1024

BACKEND_KINDS = ("bedrock", "converse")


def _env_int(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}.") from exc


def build_bedrock_pipeline(
    model: Optional[str] = None,
    *,
    region: Optional[str] = None,
    profile: Optional[str] = None,
    max_tokens: Optional[int] = None,
    thinking_budget: Optional[int] = None,
    timeout: float = 180,
    client: Any = None,
):
    """Build a `BedrockPipeline`, filling anything omitted from the environment."""
    from .bedrock import BedrockPipeline

    return BedrockPipeline(
        model,
        region=region,
        profile=profile,
        max_tokens=max_tokens,
        thinking_budget=thinking_budget,
        timeout=timeout,
        client=client,
    )


def build_converse_pipeline(
    model: Optional[str] = None,
    *,
    region: Optional[str] = None,
    profile: Optional[str] = None,
    max_tokens: int = 4096,
    timeout: float = 180,
    client: Any = None,
):
    """Build a `ConversePipeline` for any Bedrock model via the Converse API."""
    from .converse import ConversePipeline

    return ConversePipeline(
        model or "us.amazon.nova-micro-v1:0",
        region=region,
        profile=profile,
        max_tokens=max_tokens,
        timeout=timeout,
        client=client,
    )


def build_pipeline(kind: str, **kwargs):
    """Build a pipeline backend by name, mirroring `fictive.rag.build_rag_backend`."""
    if kind == "bedrock":
        return build_bedrock_pipeline(**kwargs)
    if kind == "converse":
        return build_converse_pipeline(**kwargs)
    raise ValueError(f"Unknown pipeline backend {kind!r}; expected one of {', '.join(BACKEND_KINDS)}.")

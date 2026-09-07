"""Pydantic AI model construction isolated from the host application."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from .config import AgentProfile
from .errors import ConfigurationError


ModelBuilder = Callable[[AgentProfile, Mapping[str, str]], Model]


@dataclass(frozen=True)
class BuiltModel:
    """A constructed model and secret values that must be redacted."""

    model: Model
    secrets: tuple[str, ...] = ()


def build_anthropic_model(profile: AgentProfile, environ: Mapping[str, str]) -> Model:
    """Construct Anthropic or an Anthropic-compatible custom endpoint."""

    if not profile.api_key_env:
        raise ConfigurationError("Anthropic profiles require api_key_env")
    api_key = environ.get(profile.api_key_env)
    if not api_key:
        raise ConfigurationError(
            f"Required credential environment variable is not set: {profile.api_key_env}"
        )

    provider_kwargs: dict[str, str] = {"api_key": api_key}
    if profile.base_url:
        provider_kwargs["base_url"] = profile.base_url
    provider = AnthropicProvider(**provider_kwargs)
    return AnthropicModel(profile.model, provider=provider)


DEFAULT_MODEL_BUILDERS: Mapping[str, ModelBuilder] = {"anthropic": build_anthropic_model}


def build_model(
    profile: AgentProfile,
    environ: Mapping[str, str],
    model_builders: Mapping[str, ModelBuilder] | None = None,
) -> BuiltModel:
    """Build a model using a built-in or host-registered provider adapter."""

    builders = dict(DEFAULT_MODEL_BUILDERS)
    if model_builders:
        builders.update(model_builders)
    try:
        builder = builders[profile.provider]
    except KeyError as exc:
        raise ConfigurationError(f"No model builder registered for {profile.provider!r}") from exc

    model = builder(profile, environ)
    secrets: tuple[str, ...] = ()
    if profile.api_key_env and environ.get(profile.api_key_env):
        secrets = (environ[profile.api_key_env],)
    return BuiltModel(model=model, secrets=secrets)

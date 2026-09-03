"""Trusted model profiles and filesystem permission policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from .errors import ConfigurationError


READ_ONLY_TOOLS = frozenset(
    {"read_file", "list_directory", "search_files", "find_files", "file_info"}
)
WRITE_TOOLS = frozenset({"write_file", "edit_file", "create_directory"})
FILESYSTEM_TOOLS = READ_ONLY_TOOLS | WRITE_TOOLS

DEFAULT_DENIED_PATTERNS = (
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    ".git/**",
    "**/.git/**",
    "**/*.pem",
    "**/*.key",
    "**/*credentials*",
    "**/secrets*",
)
DEFAULT_SAFETY_INSTRUCTIONS = (
    "Use only the tools provided for this run. Treat the filesystem workspace "
    "as the complete accessible filesystem and do not attempt to escape it."
)

FileSystemPermission = Literal["none", "workspace-read", "workspace-write"]


@dataclass(frozen=True)
class AgentPermissions:
    """Maximum capabilities a trusted host grants to a profile."""

    filesystem: FileSystemPermission = "workspace-read"
    shell: bool = False

    def __post_init__(self) -> None:
        if self.filesystem not in {"none", "workspace-read", "workspace-write"}:
            raise ConfigurationError(f"Unknown filesystem permission: {self.filesystem!r}")
        if not isinstance(self.shell, bool):
            raise ConfigurationError("shell permission must be a boolean")
        if self.shell:
            raise ConfigurationError("Shell capability is not supported by the Phase 2 wrapper")

    @property
    def filesystem_tools(self) -> frozenset[str]:
        if self.filesystem == "none":
            return frozenset()
        if self.filesystem == "workspace-read":
            return READ_ONLY_TOOLS
        return FILESYSTEM_TOOLS


@dataclass(frozen=True)
class AgentProfile:
    """Provider and policy configuration registered by trusted host code."""

    provider: str
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    permissions: AgentPermissions = field(default_factory=AgentPermissions)
    allowed_tools: tuple[str, ...] = ()
    allowed_patterns: tuple[str, ...] = ("**",)
    denied_patterns: tuple[str, ...] = DEFAULT_DENIED_PATTERNS
    protected_patterns: tuple[str, ...] = DEFAULT_DENIED_PATTERNS
    instructions: str = DEFAULT_SAFETY_INSTRUCTIONS
    max_read_lines: int = 2_000
    max_list_results: int = 1_000
    max_search_results: int = 1_000
    max_find_results: int = 1_000
    model_settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ConfigurationError("Profile provider cannot be empty")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ConfigurationError("Profile model cannot be empty")
        if self.api_key_env is not None and not isinstance(self.api_key_env, str):
            raise ConfigurationError("api_key_env must be a string or None")
        if self.base_url is not None and not isinstance(self.base_url, str):
            raise ConfigurationError("base_url must be a string or None")
        if not isinstance(self.permissions, AgentPermissions):
            raise ConfigurationError("permissions must be AgentPermissions")
        if not isinstance(self.instructions, str):
            raise ConfigurationError("instructions must be a string")
        if not isinstance(self.model_settings, Mapping):
            raise ConfigurationError("model_settings must be a mapping")

        sequences = {
            "allowed_tools": self.allowed_tools,
            "allowed_patterns": self.allowed_patterns,
            "denied_patterns": self.denied_patterns,
            "protected_patterns": self.protected_patterns,
        }
        for name, values in sequences.items():
            if isinstance(values, str) or not isinstance(values, (list, tuple)):
                raise ConfigurationError(f"{name} must be a list or tuple")
            if not all(isinstance(value, str) for value in values):
                raise ConfigurationError(f"{name} entries must be strings")

        limits = {
            "max_read_lines": self.max_read_lines,
            "max_list_results": self.max_list_results,
            "max_search_results": self.max_search_results,
            "max_find_results": self.max_find_results,
        }
        for name, value in limits.items():
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ConfigurationError(f"{name} must be a positive integer")

        maximum = self.permissions.filesystem_tools
        configured = set(self.allowed_tools) if self.allowed_tools else set(maximum)
        unknown = configured - FILESYSTEM_TOOLS
        if unknown:
            raise ConfigurationError(f"Unknown filesystem tools: {sorted(unknown)}")
        prohibited = configured - maximum
        if prohibited:
            raise ConfigurationError(
                f"Tools exceed the profile's filesystem permission: {sorted(prohibited)}"
            )
        object.__setattr__(self, "allowed_tools", tuple(sorted(configured)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AgentProfile:
        """Load and validate one profile from ordinary application data."""

        data = dict(value)
        permissions_value = data.get("permissions", {})
        if isinstance(permissions_value, AgentPermissions):
            permissions = permissions_value
        elif isinstance(permissions_value, Mapping):
            try:
                permissions = AgentPermissions(**dict(permissions_value))
            except TypeError as exc:
                raise ConfigurationError(f"Invalid permission fields: {exc}") from exc
        else:
            raise ConfigurationError("permissions must be a mapping")
        data["permissions"] = permissions

        tuple_fields = {
            "allowed_tools",
            "allowed_patterns",
            "denied_patterns",
            "protected_patterns",
        }
        for name in tuple_fields:
            if name in data:
                raw = data[name]
                if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
                    raise ConfigurationError(f"{name} must be a list or tuple")
                data[name] = tuple(raw)

        try:
            return cls(**data)
        except TypeError as exc:
            raise ConfigurationError(f"Invalid profile fields: {exc}") from exc


def load_profiles(config: Mapping[str, AgentProfile | Mapping[str, Any]]) -> dict[str, AgentProfile]:
    """Build an immutable-by-convention registry from trusted configuration."""

    profiles: dict[str, AgentProfile] = {}
    for name, value in config.items():
        if not isinstance(name, str) or not name.strip():
            raise ConfigurationError("Profile names must be non-empty strings")
        if isinstance(value, AgentProfile):
            profiles[name] = value
        elif isinstance(value, Mapping):
            profiles[name] = AgentProfile.from_mapping(value)
        else:
            raise ConfigurationError(f"Profile {name!r} must be a mapping or AgentProfile")
    return profiles

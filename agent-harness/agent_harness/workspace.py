"""Workspace containment and side-effect accounting."""

from __future__ import annotations

import fnmatch
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic_ai.toolsets import FilteredToolset
from pydantic_ai_harness import FileSystem

from .config import AgentProfile
from .errors import ConfigurationError, WorkspaceViolation


@dataclass(frozen=True)
class EntryState:
    kind: int
    size: int
    modified_ns: int
    link_target: str | None


def resolve_workspace(host_root: Path, requested_workspace: Path) -> Path:
    """Resolve a relative workspace and prove that it remains under host_root."""

    try:
        root = host_root.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceViolation("Host workspace root does not exist or cannot be resolved") from exc
    if not root.is_dir():
        raise WorkspaceViolation(f"Host workspace root is not a directory: {root}")
    if requested_workspace.is_absolute():
        raise WorkspaceViolation("Requested workspace must be relative")

    try:
        workspace = (root / requested_workspace).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceViolation("Requested workspace does not exist or cannot be resolved") from exc
    if not workspace.is_dir():
        raise WorkspaceViolation("Requested workspace is not a directory")
    if not workspace.is_relative_to(root):
        raise WorkspaceViolation("Requested workspace resolves outside the host root")
    return workspace


def select_tools(profile: AgentProfile, requested_tools: Iterable[str]) -> frozenset[str]:
    """Select a subset without allowing a request to broaden host permissions."""

    requested = frozenset(requested_tools)
    if not all(isinstance(tool, str) for tool in requested):
        raise ConfigurationError("Requested tool names must be strings")
    allowed = frozenset(profile.allowed_tools)
    if not requested:
        return allowed
    prohibited = requested - allowed
    if prohibited:
        raise ConfigurationError(f"Requested tools are not allowed: {sorted(prohibited)}")
    return requested


def build_filesystem_toolset(profile: AgentProfile, workspace: Path, tools: frozenset[str]):
    """Build a fresh, workspace-bound harness toolset for one run."""

    if not tools:
        return None
    filesystem = FileSystem(
        root_dir=workspace,
        allowed_patterns=profile.allowed_patterns,
        denied_patterns=profile.denied_patterns,
        protected_patterns=profile.protected_patterns,
        max_read_lines=profile.max_read_lines,
        max_list_results=profile.max_list_results,
        max_search_results=profile.max_search_results,
        max_find_results=profile.max_find_results,
        read_only=profile.permissions.filesystem == "workspace-read",
    )
    return FilteredToolset(filesystem.get_toolset(), lambda _ctx, tool: tool.name in tools)


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or (
        pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:])
    )


def _is_denied(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_matches(path, pattern) for pattern in patterns)


def snapshot_workspace(
    workspace: Path,
    *,
    denied_patterns: tuple[str, ...],
    max_entries: int = 100_000,
) -> dict[str, EntryState]:
    """Capture metadata without following symlinked directories or reading files."""

    result: dict[str, EntryState] = {}
    pending = [workspace]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(workspace).as_posix()
                if _is_denied(relative, denied_patterns):
                    continue
                metadata = entry.stat(follow_symlinks=False)
                link_target = os.readlink(path) if entry.is_symlink() else None
                result[relative] = EntryState(
                    kind=stat.S_IFMT(metadata.st_mode),
                    size=metadata.st_size,
                    modified_ns=metadata.st_mtime_ns,
                    link_target=link_target,
                )
                if len(result) > max_entries:
                    raise ConfigurationError(
                        f"Workspace contains more than {max_entries} reportable entries"
                    )
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
    return result


def changed_paths(before: dict[str, EntryState], after: dict[str, EntryState]) -> tuple[str, ...]:
    """Return normalized relative paths whose metadata changed."""

    return tuple(
        sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    )

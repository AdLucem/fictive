"""Compatibility shim for using this repository as a parent-project submodule."""

import sys
from importlib import import_module



_inner_package = import_module(".fictive", __name__)

__all__ = list(getattr(_inner_package, "__all__", ()))

for _name in __all__:
    globals()[_name] = getattr(_inner_package, _name)

for _submodule_name in (
    "agent_api",
    "agent_integration",
    "actors",
    "custom_actors",
    "data_structures",
    "debugger",
    "goals",
    "interpreter",
    "library_runtime",
    "bedrock_runtime",
    "parse_scenario_config",
    "run",
    "session",
    "parser",
    "parser.commands",
    "parser.expressions",
    "pipelines",
    "pipelines.bedrock",
    "rag",
    "rag.bedrock",
    "rag.local",
    "websearch",
    "websearch.agentcore",
):
    _module = import_module(f".fictive.{_submodule_name}", __name__)
    sys.modules[f"{__name__}.{_submodule_name}"] = _module

    _attr_name = _submodule_name.rsplit(".", 1)[-1]
    if "." not in _submodule_name:
        globals()[_attr_name] = _module

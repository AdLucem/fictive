"""Web search for the `web-search-and-generate` command.

One backend answers a small protocol:

- `agentcore` (`fictive.websearch.agentcore`): an Amazon Bedrock AgentCore
  Gateway fronting the AWS-managed Web Search Tool connector, reached over MCP
  with SigV4-signed requests. Bedrock has no server-side `web_search` tool --
  it serves Anthropic's *client* tools but not the server tools that run on
  Anthropic's own infrastructure -- which is why the gateway exists.

A host can also build a backend itself and hand it to
`Interpreter(web_search_backend=...)`, which is what every
`web-search-and-generate` uses when it names no `backend` of its own.

Results come back as `fictive.rag.RetrievedPassage`, so this command and
`rag-generate` share one result shape, one `sources-store` shape and one
context-wrapping path.

The backend module is not imported until one is built, so importing `fictive`
never imports `boto3`. This module reads `os.environ` but never loads a `.env`
file; that is an entry point's job.
"""

from typing import List, Optional, Protocol

from ..rag import RetrievedPassage, fill_enclosing_prompt, format_passages

WEBSEARCH_GATEWAY_URL_ENV = "WEBSEARCH_GATEWAY_URL"
WEBSEARCH_GATEWAY_STACK_ENV = "WEBSEARCH_GATEWAY_STACK"
WEBSEARCH_REGION_ENV = "WEBSEARCH_REGION"
WEBSEARCH_PROFILE_ENV = "WEBSEARCH_PROFILE"

BACKEND_KINDS = ("agentcore",)

#: The connector's own limits.
MAX_QUERY_CHARS = 200
MIN_RESULTS = 1
MAX_RESULTS = 25

DEFAULT_WEB_SEARCH_ENCLOSING_PROMPT = (
    "Results from a web search:\n\n"
    "{CONTEXT}\n\n"
    "Use these results where they help, and ignore them where they do not. "
    "When you use one, name its source.\n\n"
    "{INPUT}"
)
NO_RESULTS_TEXT = "(No web search results were found.)"

__all__ = [
    "WebSearchBackend",
    "RetrievedPassage",
    "backend_kind",
    "build_web_search_backend",
    "fill_enclosing_prompt",
    "format_passages",
    "DEFAULT_WEB_SEARCH_ENCLOSING_PROMPT",
    "MAX_QUERY_CHARS",
    "MAX_RESULTS",
    "MIN_RESULTS",
    "NO_RESULTS_TEXT",
]


class WebSearchBackend(Protocol):
    def search(
        self,
        query: str,
        max_results: int,
        filters: Optional[dict] = None,
    ) -> List[RetrievedPassage]: ...


def backend_kind(override: Optional[str] = None) -> str:
    """`override` if given, else `agentcore`."""
    if override is not None:
        if override not in BACKEND_KINDS:
            raise ValueError(
                f"Unknown web search backend {override!r}; expected one of "
                f"{', '.join(BACKEND_KINDS)}."
            )
        return override
    return "agentcore"


def build_web_search_backend(kind: str) -> WebSearchBackend:
    if kind == "agentcore":
        from .agentcore import AgentCoreGatewayBackend

        return AgentCoreGatewayBackend()
    raise ValueError(f"Unknown web search backend {kind!r}.")

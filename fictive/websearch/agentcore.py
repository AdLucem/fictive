"""An Amazon Bedrock AgentCore Gateway fronting the AWS-managed Web Search Tool.

The gateway speaks MCP over HTTP. It is created with `AuthorizerType: AWS_IAM`,
so every JSON-RPC post is SigV4-signed for the `bedrock-agentcore` service with
whatever credentials the standard AWS chain resolves.

Unlike a model-driven tool loop, this backend performs the search itself and
hands the results back as passages; `web-search-and-generate` folds them into
the prompt. The model is never given a tool to call.

Only the standard library and botocore are used, and both are imported inside
the methods that need them, so importing `fictive` needs no boto3.

One instance holds an MCP session id and a request counter, so it is not
thread-safe. `Interpreter` is single-threaded, so that is fine; a host sharing
one backend across threads must not.

See:
https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-connector-web-search-tool.html
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, List, Optional

from ..rag import RetrievedPassage
from . import (
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    MIN_RESULTS,
    WEBSEARCH_GATEWAY_STACK_ENV,
    WEBSEARCH_GATEWAY_URL_ENV,
    WEBSEARCH_PROFILE_ENV,
    WEBSEARCH_REGION_ENV,
)

MCP_PROTOCOL_VERSION = "2025-03-26"
SIGNING_SERVICE = "bedrock-agentcore"

#: Keys a connector may use for the list of hits inside its JSON payload.
_RESULT_LIST_KEYS = ("results", "webSearchResults", "items")


class AgentCoreGatewayBackend:
    """Search the web through an AgentCore Gateway's web-search connector."""

    def __init__(
        self,
        gateway_url: Optional[str] = None,
        *,
        region: Optional[str] = None,
        profile: Optional[str] = None,
        stack_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.region = region or os.environ.get(WEBSEARCH_REGION_ENV)
        self.profile = profile or os.environ.get(WEBSEARCH_PROFILE_ENV)
        self.stack_name = stack_name or os.environ.get(WEBSEARCH_GATEWAY_STACK_ENV)
        self.tool_name = tool_name
        self.timeout = timeout

        self._url = self._resolve_url(gateway_url)
        self._mcp_session_id: Optional[str] = None
        self._request_id = 0
        self.tool: Optional[dict] = None

    # -- discovery ---------------------------------------------------------

    def _resolve_url(self, gateway_url: Optional[str]) -> str:
        url = gateway_url or os.environ.get(WEBSEARCH_GATEWAY_URL_ENV)
        if not url and self.stack_name:
            url = self._url_from_stack(self.stack_name)
        if not url:
            raise ValueError(
                "The AgentCore web search backend needs a gateway URL: set "
                f"{WEBSEARCH_GATEWAY_URL_ENV}, or set {WEBSEARCH_GATEWAY_STACK_ENV} to the "
                "name of the CloudFormation stack that created the gateway."
            )
        # CloudFormation's GatewayUrl output is the bare host. The MCP endpoint
        # lives at /mcp -- posting JSON-RPC to the bare host answers HTTP 200
        # with an UnknownOperationException body rather than an error status.
        url = url.rstrip("/")
        if not url.endswith("/mcp"):
            url += "/mcp"
        return url

    def _session(self):
        import boto3

        return boto3.Session(profile_name=self.profile) if self.profile else boto3.Session()

    def _url_from_stack(self, stack_name: str) -> str:
        """Read the gateway's endpoint out of the stack that created it."""
        try:
            import boto3  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "The AgentCore web search backend needs boto3. "
                "Install it with: pip install 'fictive[web-search]'"
            ) from exc
        kwargs = {"region_name": self.region} if self.region else {}
        cfn = self._session().client("cloudformation", **kwargs)
        stacks = cfn.describe_stacks(StackName=stack_name)["Stacks"]
        for output in stacks[0].get("Outputs", []):
            if output["OutputKey"] == "GatewayUrl":
                return output["OutputValue"]
        raise RuntimeError(f"Stack {stack_name!r} has no GatewayUrl output.")

    # -- transport ---------------------------------------------------------

    def _sign(self, body: bytes) -> dict:
        try:
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
        except ImportError as exc:
            raise ImportError(
                "The AgentCore web search backend needs botocore. "
                "Install it with: pip install 'fictive[web-search]'"
            ) from exc

        session = self._session()
        region = self.region or session.region_name
        if not region:
            raise ValueError(
                f"No AWS region for the web search gateway: set {WEBSEARCH_REGION_ENV} "
                "or configure one for the profile."
            )
        credentials = session.get_credentials().get_frozen_credentials()
        headers = {
            "Content-Type": "application/json",
            # Streamable HTTP lets the server pick either representation.
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self._mcp_session_id:
            headers["Mcp-Session-Id"] = self._mcp_session_id
        request = AWSRequest(method="POST", url=self._url, data=body, headers=headers)
        SigV4Auth(credentials, SIGNING_SERVICE, region).add_auth(request)
        return dict(request.headers)

    @staticmethod
    def _extract(raw: bytes, content_type: str) -> Optional[dict]:
        if content_type.startswith("text/event-stream"):
            for line in raw.decode("utf-8").splitlines():
                if not line.startswith("data:"):
                    continue
                message = json.loads(line[len("data:"):].strip())
                if "result" in message or "error" in message:
                    return message
            return None
        if not raw.strip():
            return None
        return json.loads(raw)

    def _rpc(self, method: str, params: Optional[dict] = None, *, notification: bool = False):
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            self._request_id += 1
            payload["id"] = self._request_id

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._url, data=body, headers=self._sign(body), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type", "")
                # The server assigns a session on initialize; echo it back after.
                session_id = response.headers.get("Mcp-Session-Id")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"Gateway returned {exc.code}: {detail}") from exc

        if session_id:
            self._mcp_session_id = session_id
        if notification:
            return None

        message = self._extract(raw, content_type)
        if message is None:
            raise RuntimeError(f"No JSON-RPC response for {method!r}.")
        if "error" in message:
            raise RuntimeError(f"MCP error on {method!r}: {message['error']}")
        if "result" not in message:
            # A non-JSON-RPC body returned under HTTP 200, e.g. the gateway's
            # UnknownOperationException. Surfacing it here beats letting an
            # empty result masquerade as "the server has no tools".
            raise RuntimeError(f"Non-JSON-RPC reply to {method!r}: {json.dumps(message)[:300]}")
        return message["result"]

    # -- MCP ---------------------------------------------------------------

    def connect(self) -> dict:
        """Run the MCP handshake and discover the web search tool."""
        self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "fictive", "version": "0.1.0"},
            },
        )
        self._rpc("notifications/initialized", {}, notification=True)

        tools = (self._rpc("tools/list", {}) or {}).get("tools", [])
        if not tools:
            raise RuntimeError("Gateway exposed no tools; check that the web-search target is READY.")
        for tool in tools:
            # The gateway namespaces tools as "<target-name>___<ToolName>", so
            # match on the suffix rather than assuming the full string.
            if self.tool_name is not None:
                if tool["name"] == self.tool_name:
                    self.tool = tool
                    return tool
            elif tool["name"].split("___")[-1].lower() == "websearch":
                self.tool = tool
                return tool
        raise RuntimeError(f"No web search tool among: {[t['name'] for t in tools]}")

    # -- the backend protocol ----------------------------------------------

    def search(
        self,
        query: str,
        max_results: int,
        filters: Optional[dict] = None,
    ) -> List[RetrievedPassage]:
        if self.tool is None:
            self.connect()

        query = str(query or "").strip()
        if len(query) > MAX_QUERY_CHARS:
            # Truncated rather than rejected: the natural default query is the
            # actor's latest user message, which routinely runs past the limit,
            # and raising would make the command unusable in its most ordinary
            # configuration.
            logging.warning(
                "web search query is %d characters; truncating to the connector's limit of %d.",
                len(query),
                MAX_QUERY_CHARS,
            )
            query = query[:MAX_QUERY_CHARS]

        arguments: dict[str, Any] = {
            "query": query,
            "maxResults": max(MIN_RESULTS, min(int(max_results), MAX_RESULTS)),
        }
        if filters:
            arguments["filters"] = filters

        result = self._rpc("tools/call", {"name": self.tool["name"], "arguments": arguments}) or {}
        blocks = [b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"]
        if result.get("isError"):
            raise RuntimeError(f"Web search failed: {' '.join(t for t in blocks if t) or 'unknown error'}")
        return self._passages(blocks)

    @staticmethod
    def _passages(blocks: List[str]) -> List[RetrievedPassage]:
        """Turn the connector's text blocks into passages.

        Each block is normally a JSON document holding a list of hits, but a
        connector is free to answer with plain prose, so unparseable text
        becomes a single passage rather than an error.
        """
        passages: List[RetrievedPassage] = []
        for block in blocks:
            if not block.strip():
                continue
            try:
                payload = json.loads(block)
            except (ValueError, TypeError):
                passages.append(RetrievedPassage(text=block.strip()))
                continue

            entries = None
            if isinstance(payload, dict):
                for key in _RESULT_LIST_KEYS:
                    if isinstance(payload.get(key), list):
                        entries = payload[key]
                        break
            elif isinstance(payload, list):
                entries = payload

            if entries is None:
                passages.append(RetrievedPassage(text=block.strip()))
                continue

            for entry in entries:
                if not isinstance(entry, dict):
                    passages.append(RetrievedPassage(text=str(entry)))
                    continue
                text = entry.get("text") or entry.get("snippet") or entry.get("content") or entry.get("title") or ""
                passages.append(
                    RetrievedPassage(
                        text=str(text).strip(),
                        score=entry.get("score"),
                        source=entry.get("url") or entry.get("link"),
                        metadata=dict(entry),
                    )
                )
        return passages

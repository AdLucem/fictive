"""Amazon Bedrock Knowledge Bases backend for `rag-generate`.

This backend only queries an existing Knowledge Base. Getting conversations into
its data source and syncing it happens outside fictive.

By default it generates too, in the same `RetrieveAndGenerate` call. Built with
`native_generation=False` it only retrieves, through `Retrieve`, and the
interpreter generates with the actor's own pipeline, which sees the actor's
whole history.

Configuration comes from the environment:

- `KNOWLEDGE_BASE_ID`: the Knowledge Base to query (required).
- `BEDROCK_MODEL_ARN`: the model or inference profile ARN that
  `RetrieveAndGenerate` generates with, unless the command passes `model-arn`.
- Region and credentials: boto3's standard chain (`AWS_REGION`, `AWS_PROFILE`, ...).

An `actor-filter` becomes a Knowledge Base metadata filter on the `actor` key, so
it only matches documents whose metadata carries that key.
"""

import os
from typing import List, Optional

from . import KNOWLEDGE_BASE_ENV, RagResult, RetrievedPassage

MODEL_ARN_ENV = "BEDROCK_MODEL_ARN"


def prompt_template(system_prompt: str) -> str:
    """A generation prompt carrying the actor's system prompt.

    Built by concatenation: Bedrock fills the `$...$` placeholders, and the
    system prompt may contain braces.
    """
    return (
        f"{system_prompt.strip()}\n\n"
        "Excerpts from relevant past conversations:\n"
        "$search_results$\n\n"
        "$output_format_instructions$\n\n"
        "Message:\n"
        "$query$"
    )


def vector_search_configuration(top_k: int, filters: Optional[dict]) -> dict:
    config = {"numberOfResults": top_k}
    conditions = [
        {"equals": {"key": key, "value": value}} for key, value in (filters or {}).items()
    ]
    if len(conditions) == 1:
        config["filter"] = conditions[0]
    elif conditions:
        config["filter"] = {"andAll": conditions}
    return config


def location_uri(location: dict) -> Optional[str]:
    """The URI of a Knowledge Base location, whichever data source type it is."""
    for key, value in (location or {}).items():
        if key != "type" and isinstance(value, dict):
            for uri_key in ("uri", "url"):
                if value.get(uri_key):
                    return value[uri_key]
    return None


def passage_from_reference(reference: dict) -> RetrievedPassage:
    return RetrievedPassage(
        text=(reference.get("content") or {}).get("text", ""),
        score=reference.get("score"),
        source=location_uri(reference.get("location")),
        metadata=dict(reference.get("metadata") or {}),
    )


class BedrockKnowledgeBaseBackend:
    generates_natively = True

    def __init__(self, knowledge_base_id=None, model_arn=None, client=None, native_generation=True):
        self.knowledge_base_id = knowledge_base_id or os.environ.get(KNOWLEDGE_BASE_ENV)
        if not self.knowledge_base_id:
            raise ValueError(
                f"The Bedrock RAG backend needs a Knowledge Base id: set {KNOWLEDGE_BASE_ENV}."
            )
        self.model_arn = model_arn or os.environ.get(MODEL_ARN_ENV)
        self._client = client
        # False makes this a retrieval-only backend: `rag-generate` then
        # generates with the actor's own pipeline, which sees the actor's whole
        # history, instead of `RetrieveAndGenerate`, which does not.
        self.generates_natively = native_generation

    @property
    def client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ImportError(
                    "The Bedrock RAG backend needs boto3. "
                    "Install it with: pip install 'fictive[rag-bedrock]'"
                ) from exc
            self._client = boto3.client("bedrock-agent-runtime")
        return self._client

    def retrieve(
        self,
        query: str,
        top_k: int,
        filters: Optional[dict] = None,
        exclude_session_id: Optional[str] = None,
    ) -> List[RetrievedPassage]:
        """Retrieval only. `exclude_session_id` is ignored: the Knowledge Base's
        contents are synced outside fictive and need not carry session ids."""
        response = self.client.retrieve(
            knowledgeBaseId=self.knowledge_base_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": vector_search_configuration(top_k, filters)
            },
        )
        return [passage_from_reference(r) for r in response.get("retrievalResults", [])]

    def retrieve_and_generate(
        self,
        query: str,
        top_k: int,
        filters: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        model_arn: Optional[str] = None,
    ) -> RagResult:
        model_arn = model_arn or self.model_arn
        if not model_arn:
            raise ValueError(
                f"The Bedrock RAG backend needs a model ARN: set {MODEL_ARN_ENV} "
                "or pass model-arn to rag-generate."
            )

        kb_config = {
            "knowledgeBaseId": self.knowledge_base_id,
            "modelArn": model_arn,
            "retrievalConfiguration": {
                "vectorSearchConfiguration": vector_search_configuration(top_k, filters)
            },
        }
        if system_prompt:
            kb_config["generationConfiguration"] = {
                "promptTemplate": {"textPromptTemplate": prompt_template(system_prompt)}
            }
        request = {
            "input": {"text": query},
            "retrieveAndGenerateConfiguration": {
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": kb_config,
            },
        }
        if session_id:
            request["sessionId"] = session_id

        response = self.client.retrieve_and_generate(**request)

        # A reference cited by several parts of the answer is listed once.
        passages, seen = [], set()
        for citation in response.get("citations", []):
            for reference in citation.get("retrievedReferences", []):
                passage = passage_from_reference(reference)
                key = (passage.text, passage.source)
                if key not in seen:
                    seen.add(key)
                    passages.append(passage)

        return RagResult(
            output=response["output"]["text"],
            passages=passages,
            session_id=response.get("sessionId"),
        )

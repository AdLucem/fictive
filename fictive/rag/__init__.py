"""Retrieval-augmented generation for the `rag-generate` command.

Two backends answer the same small protocol:

- `bedrock` (`fictive.rag.bedrock`): an Amazon Bedrock Knowledge Base, chosen
  whenever `KNOWLEDGE_BASE_ID` is set. By default it retrieves and generates in
  one `RetrieveAndGenerate` call, so it `generates_natively`; built with
  `native_generation=False` it only retrieves.
- `local` (`fictive.rag.local`): a LlamaIndex vector index over the session
  files in the conversations directory (`Interpreter.conversations_root`),
  plus any reference documents a host adds. It only retrieves; the
  interpreter generates with the actor's own pipeline.

A host can also build a backend itself and hand it to
`Interpreter(rag_backend=...)`.

Neither backend module is imported until one is built, so importing `fictive`
never imports `boto3` or `llama_index`. This module reads `os.environ` but never
loads a `.env` file; that is an entry point's job.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

KNOWLEDGE_BASE_ENV = "KNOWLEDGE_BASE_ID"
BACKEND_KINDS = ("bedrock", "local")

DEFAULT_RAG_ENCLOSING_PROMPT = (
    "Excerpts from relevant past conversations:\n\n"
    "{CONTEXT}\n\n"
    "Use these excerpts where they help, and ignore them where they do not.\n\n"
    "{INPUT}"
)
NO_PASSAGES_TEXT = "(No relevant past conversations were found.)"
PLACEHOLDER_RE = re.compile(r"\{(CONTEXT|INPUT)\}")


@dataclass(frozen=True)
class RetrievedPassage:
    text: str
    score: Optional[float] = None
    source: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "score": self.score,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RagResult:
    output: str
    passages: List[RetrievedPassage] = field(default_factory=list)
    session_id: Optional[str] = None


class RagBackend(Protocol):
    generates_natively: bool

    def retrieve(
        self,
        query: str,
        top_k: int,
        filters: Optional[dict] = None,
        exclude_session_id: Optional[str] = None,
    ) -> List[RetrievedPassage]: ...

    def retrieve_and_generate(
        self,
        query: str,
        top_k: int,
        filters: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
        model_arn: Optional[str] = None,
    ) -> RagResult: ...


def backend_kind(override: Optional[str] = None) -> str:
    """`override` if given, else `bedrock` when `KNOWLEDGE_BASE_ID` is set, else `local`."""
    if override is not None:
        if override not in BACKEND_KINDS:
            raise ValueError(
                f"Unknown RAG backend {override!r}; expected one of {', '.join(BACKEND_KINDS)}."
            )
        return override
    return "bedrock" if os.environ.get(KNOWLEDGE_BASE_ENV) else "local"


def build_rag_backend(kind: str, conversations_dir) -> RagBackend:
    if kind == "bedrock":
        from .bedrock import BedrockKnowledgeBaseBackend

        return BedrockKnowledgeBaseBackend()
    if kind == "local":
        from .local import LlamaIndexConversationBackend

        return LlamaIndexConversationBackend(conversations_dir)
    raise ValueError(f"Unknown RAG backend {kind!r}.")


def format_passages(passages: List[RetrievedPassage]) -> str:
    if not passages:
        return NO_PASSAGES_TEXT
    blocks = []
    for i, passage in enumerate(passages, start=1):
        header = f"[{i}] {passage.source}" if passage.source else f"[{i}]"
        blocks.append(f"{header}\n{passage.text.strip()}")
    return "\n\n".join(blocks)


def fill_enclosing_prompt(enclosing_prompt: str, context: str, user_input: str) -> str:
    """Put `context` at `{CONTEXT}` and `user_input` at `{INPUT}` (or after the prompt).

    One substitution pass rather than `str.format` or chained `replace`:
    transcripts are full of braces, and a retrieved passage that happens to
    contain `{INPUT}` must not be substituted into.
    """
    if "{CONTEXT}" not in enclosing_prompt:
        raise ValueError("A rag-generate enclosing prompt must contain the {CONTEXT} placeholder.")
    values = {"CONTEXT": context, "INPUT": user_input}
    filled = PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], enclosing_prompt)
    if "{INPUT}" in enclosing_prompt:
        return filled
    return f"{filled}\n\n{user_input}"

"""Local LlamaIndex backend for `rag-generate`: retrieval over saved sessions.

Every session file in the conversations directory becomes one LlamaIndex
document per actor, holding that actor's transcript. The vector index is
persisted to `<conversations_dir>/.rag_index/` and brought up to date at the
start of every retrieval: `refresh_ref_docs` re-embeds only documents whose text
changed, and documents whose source is gone are deleted. Saving a session is
all it takes to make it retrievable.

A host can index more than sessions, and less of them:

- `document_paths`: reference files (a wiki, say), indexed alongside the
  sessions as one document each and re-embedded when their text changes.
- `actors`: only these actors' transcripts are indexed. A router's JSON or a
  hidden sub-actor's scratch work is rarely worth retrieving.
- `transcript_renderer`: turns an actor's saved history into the indexed text,
  in place of `fictive.session.render_transcript`. A host that injects large
  context blocks into history can leave them out here.
- `max_reference_passages`: at most this many results come from reference
  documents, and the rest from conversations. A long reference file is split
  into many chunks, and without a cap they can take every slot from a short
  conversation that matters more. A side with too few results leaves its
  slots to the other.

Embeddings come from a local Hugging Face model, `FICTIVE_RAG_EMBED_MODEL`
(default `BAAI/bge-small-en-v1.5`). The model is passed explicitly everywhere,
so LlamaIndex never falls back to its OpenAI defaults. This backend only
retrieves; the interpreter generates with the actor's pipeline.
"""

import json
import logging
import os
import pathlib
from types import SimpleNamespace
from typing import Callable, List, Optional

from . import RagResult, RetrievedPassage
from ..session import check_session_doc, render_transcript

EMBED_MODEL_ENV = "FICTIVE_RAG_EMBED_MODEL"
DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
INDEX_DIR = ".rag_index"
# Bookkeeping metadata, kept out of the text that is embedded or shown to a model.
BOOKKEEPING_KEYS = ["session_id", "saved_at", "session_file"]
PASSAGE_METADATA_KEYS = ["actor", "document", *BOOKKEEPING_KEYS]


def import_llama_index() -> SimpleNamespace:
    try:
        from llama_index.core import (
            Document,
            StorageContext,
            VectorStoreIndex,
            load_index_from_storage,
        )
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
        )
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    except ImportError as exc:
        raise ImportError(
            "The local RAG backend needs LlamaIndex. "
            "Install it with: pip install 'fictive[rag-local]'"
        ) from exc

    return SimpleNamespace(
        Document=Document,
        StorageContext=StorageContext,
        VectorStoreIndex=VectorStoreIndex,
        load_index_from_storage=load_index_from_storage,
        FilterOperator=FilterOperator,
        MetadataFilter=MetadataFilter,
        MetadataFilters=MetadataFilters,
        HuggingFaceEmbedding=HuggingFaceEmbedding,
    )


def document_metadata(**values) -> dict:
    """Every metadata key on every document, `""` where it does not apply.

    A reference document has no session and a session has no document name,
    but both carry both keys: a `session_id != current` filter must keep a
    document with no session rather than depend on how a vector store treats a
    missing key.
    """
    return {key: values.get(key) or "" for key in PASSAGE_METADATA_KEYS}


def excluded_metadata_keys(metadata: dict) -> list:
    """Bookkeeping and empty keys, which say nothing worth embedding."""
    return [key for key, value in metadata.items() if key in BOOKKEEPING_KEYS or not value]


class LlamaIndexConversationBackend:
    generates_natively = False

    def __init__(
        self,
        conversations_dir,
        embed_model=None,
        document_paths=(),
        actors=None,
        transcript_renderer: Optional[Callable[[list], str]] = None,
        max_reference_passages: Optional[int] = None,
    ):
        self.conversations_dir = pathlib.Path(conversations_dir)
        self.index_dir = self.conversations_dir / INDEX_DIR
        self.document_paths = [pathlib.Path(path) for path in document_paths]
        self.actors = None if actors is None else frozenset(actors)
        self.transcript_renderer = transcript_renderer or render_transcript
        self.max_reference_passages = max_reference_passages
        self._embed_model = embed_model
        self._llama = None
        self._index = None

    @property
    def llama(self) -> SimpleNamespace:
        if self._llama is None:
            self._llama = import_llama_index()
        return self._llama

    @property
    def embed_model(self):
        if self._embed_model is None:
            model_name = os.environ.get(EMBED_MODEL_ENV) or DEFAULT_EMBED_MODEL
            self._embed_model = self.llama.HuggingFaceEmbedding(model_name=model_name)
        return self._embed_model

    def load_index(self):
        if self._index is None:
            if (self.index_dir / "docstore.json").is_file():
                storage = self.llama.StorageContext.from_defaults(persist_dir=str(self.index_dir))
                self._index = self.llama.load_index_from_storage(
                    storage, embed_model=self.embed_model
                )
            else:
                self._index = self.llama.VectorStoreIndex([], embed_model=self.embed_model)
        return self._index

    def _document(self, doc_id: str, text: str, metadata: dict):
        excluded = excluded_metadata_keys(metadata)
        return self.llama.Document(
            id_=doc_id,
            text=text,
            metadata=metadata,
            excluded_embed_metadata_keys=excluded,
            excluded_llm_metadata_keys=excluded,
        )

    def session_documents(self) -> list:
        documents = []
        if not self.conversations_dir.is_dir():
            return documents

        for path in sorted(self.conversations_dir.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    doc = json.load(f)
                check_session_doc(doc, path)
            except (OSError, ValueError) as exc:
                logging.warning("Skipping %s for RAG indexing: %s", path, exc)
                continue

            for actor_name, state in doc["actors"].items():
                if self.actors is not None and actor_name not in self.actors:
                    continue
                text = self.transcript_renderer(state.get("history", []))
                if not text:
                    continue
                documents.append(
                    self._document(
                        f"{doc['session_id']}:{actor_name}",
                        text,
                        document_metadata(
                            actor=actor_name,
                            session_id=doc["session_id"],
                            saved_at=doc.get("saved_at"),
                            session_file=path.name,
                        ),
                    )
                )
        return documents

    def reference_documents(self) -> list:
        documents = []
        for path in self.document_paths:
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                logging.warning("Skipping reference document %s for RAG indexing: %s", path, exc)
                continue
            if text:
                documents.append(
                    self._document(
                        f"document:{path.resolve()}", text, document_metadata(document=path.name)
                    )
                )
        return documents

    def sync(self):
        """Bring the persisted index in line with the session files and documents on disk."""
        index = self.load_index()
        documents = self.session_documents() + self.reference_documents()
        current_ids = {document.doc_id for document in documents}

        stale = [doc_id for doc_id in index.ref_doc_info if doc_id not in current_ids]
        for doc_id in stale:
            index.delete_ref_doc(doc_id, delete_from_docstore=True)
        refreshed = index.refresh_ref_docs(documents) if documents else []

        if stale or any(refreshed) or not self.index_dir.is_dir():
            self.index_dir.mkdir(parents=True, exist_ok=True)
            index.storage_context.persist(persist_dir=str(self.index_dir))
        return index

    def retrieve(
        self,
        query: str,
        top_k: int,
        filters: Optional[dict] = None,
        exclude_session_id: Optional[str] = None,
    ) -> List[RetrievedPassage]:
        index = self.sync()
        if not index.ref_doc_info:
            return []

        if self.max_reference_passages is None or not self.document_paths:
            results = self._query(index, query, top_k, filters, exclude_session_id)
        else:
            conversations = self._query(
                index, query, top_k, filters, exclude_session_id, reference=False
            )
            references = self._query(
                index, query, top_k, filters, exclude_session_id, reference=True
            )
            results = self._balance(conversations, references, top_k)
        return [self._passage(result) for result in results]

    def _query(self, index, query, top_k, filters, exclude_session_id, reference=None):
        """One similarity search. `reference` True or False keeps only reference
        documents or only conversations; None keeps both."""
        llama = self.llama
        conditions = [
            llama.MetadataFilter(key=key, value=value) for key, value in (filters or {}).items()
        ]
        if exclude_session_id:
            conditions.append(
                llama.MetadataFilter(
                    key="session_id",
                    value=exclude_session_id,
                    operator=llama.FilterOperator.NE,
                )
            )
        if reference is not None:
            conditions.append(
                llama.MetadataFilter(
                    key="document",
                    value="",
                    operator=llama.FilterOperator.NE if reference else llama.FilterOperator.EQ,
                )
            )
        retriever = index.as_retriever(
            similarity_top_k=top_k,
            filters=llama.MetadataFilters(filters=conditions) if conditions else None,
        )
        return retriever.retrieve(query)

    def _balance(self, conversations, references, top_k):
        """Up to `max_reference_passages` references, conversations for the rest.

        Both lists arrive best first. Slots one side cannot fill go to the
        other, and the result is ordered by score again.
        """
        reference_slots = min(self.max_reference_passages, len(references))
        chosen = list(conversations[: top_k - reference_slots])
        chosen += references[: top_k - len(chosen)]
        return sorted(chosen, key=lambda result: result.score or 0.0, reverse=True)

    def _passage(self, result) -> RetrievedPassage:
        metadata = result.node.metadata
        source = metadata.get("document") or (
            f"{metadata.get('session_id')}:{metadata.get('actor')}"
        )
        return RetrievedPassage(
            text=result.node.get_content(),
            score=result.score,
            source=source,
            metadata={key: metadata.get(key, "") for key in PASSAGE_METADATA_KEYS},
        )

    def retrieve_and_generate(self, *args, **kwargs) -> RagResult:
        raise NotImplementedError(
            "The local RAG backend only retrieves; the interpreter generates with the actor's pipeline."
        )

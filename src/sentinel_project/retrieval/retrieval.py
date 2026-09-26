from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb

from sentinel_project.retrieval.policies import load_policy_documents
from sentinel_project.settings import settings

COLLECTION_NAME = "sentinel_hr_policy_chunks_v1"
DEFAULT_TOP_K = 4
DEFAULT_CHUNK_SIZE = 500
CHUNK_OVERLAP_SENTENCES = 1


@dataclass
class PolicyDocument:
    doc_id: str
    title: str
    text: str


_INJECTION_SENTENCE_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|override|forget)\b.{0,120}\b(?:instructions?|system|policy|rules?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:reveal|print|output|repeat)\b.{0,100}\b(?:system prompt|hidden instructions|canary)\b",
        re.IGNORECASE,
    ),
)


def _split_oversized_sentence(sentence: str, max_chars: int) -> list[str]:
    words = sentence.split()
    chunks: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join([*current, word])
        if current and len(candidate) > max_chars:
            chunks.append(" ".join(current))
            current = [word]
        else:
            current.append(word)

    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_policy_documents(
    documents: list[dict[str, str]],
    *,
    max_chars: int = DEFAULT_CHUNK_SIZE,
    overlap_sentences: int = CHUNK_OVERLAP_SENTENCES,
) -> list[dict[str, str]]:
    """Split policy text on sentence boundaries with one-sentence overlap.

    Oversized single sentences are split on word boundaries without overlap.
    Short policy documents stay intact as a single chunk.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be positive")
    if overlap_sentences < 0:
        raise ValueError("overlap_sentences cannot be negative")

    chunks: list[dict[str, str]] = []
    for document in documents:
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", document["text"].strip())
            if sentence.strip()
        ]
        document_chunks: list[str] = []
        current: list[str] = []

        for sentence in sentences:
            if len(sentence) > max_chars:
                if current:
                    document_chunks.append(" ".join(current))
                    current = []
                document_chunks.extend(_split_oversized_sentence(sentence, max_chars))
                continue

            candidate = " ".join([*current, sentence])
            if current and len(candidate) > max_chars:
                document_chunks.append(" ".join(current))
                overlap = current[-overlap_sentences:] if overlap_sentences else []
                current = overlap if len(" ".join([*overlap, sentence])) <= max_chars else []
            current.append(sentence)

        if current:
            document_chunks.append(" ".join(current))

        for chunk_index, text in enumerate(document_chunks):
            chunks.append(
                {
                    "chunk_id": f"{document['doc_id']}::chunk-{chunk_index:04d}",
                    "doc_id": document["doc_id"],
                    "title": document["title"],
                    "text": text,
                }
            )

    return chunks


def sanitize_retrieved_chunk(text: str) -> str:
    """Remove retrieved sentences that look like prompt-control instructions."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    safe_sentences = [
        sentence
        for sentence in sentences
        if not any(pattern.search(sentence) for pattern in _INJECTION_SENTENCE_PATTERNS)
    ]
    return " ".join(sentence.strip() for sentence in safe_sentences if sentence.strip())


class ChromaPolicyRetriever:
    """Index policy chunks in Chroma and retrieve by vector similarity."""

    def __init__(
        self,
        persist_path: str | Path,
        *,
        client: Any | None = None,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self.client = client or chromadb.PersistentClient(path=str(persist_path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _sync_index(self, chunks: list[dict[str, str]]) -> None:
        current = self.collection.get(include=["documents", "metadatas"])
        existing = {
            chunk_id: (text, metadata)
            for chunk_id, text, metadata in zip(
                current["ids"], current["documents"], current["metadatas"]
            )
        }
        expected = {
            chunk["chunk_id"]: (
                chunk["text"],
                {
                    "doc_id": chunk["doc_id"],
                    "title": chunk["title"],
                    "chunk_index": int(chunk["chunk_id"].rsplit("-", 1)[1]),
                },
            )
            for chunk in chunks
        }

        stale_ids = list(existing.keys() - expected.keys())
        if stale_ids:
            self.collection.delete(ids=stale_ids)

        changed = [
            chunk
            for chunk in chunks
            if existing.get(chunk["chunk_id"])
            != (
                chunk["text"],
                {
                    "doc_id": chunk["doc_id"],
                    "title": chunk["title"],
                    "chunk_index": int(chunk["chunk_id"].rsplit("-", 1)[1]),
                },
            )
        ]
        if changed:
            self.collection.upsert(
                ids=[chunk["chunk_id"] for chunk in changed],
                documents=[chunk["text"] for chunk in changed],
                metadatas=[
                    {
                        "doc_id": chunk["doc_id"],
                        "title": chunk["title"],
                        "chunk_index": int(chunk["chunk_id"].rsplit("-", 1)[1]),
                    }
                    for chunk in changed
                ],
            )

    def retrieve(
        self,
        query: str,
        *,
        limit: int = DEFAULT_TOP_K,
        documents: list[dict[str, str]] | None = None,
        hardened: bool = False,
    ) -> list[dict[str, object]]:
        """Return the nearest chunks and their 1-based rank and cosine score."""
        if limit < 1:
            return []

        chunks = chunk_policy_documents(
            load_policy_documents() if documents is None else documents
        )
        if not chunks:
            return []
        self._sync_index(chunks)

        result = self.collection.query(
            query_texts=[query],
            n_results=min(limit, len(chunks)),
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        texts = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]

        retrieved: list[dict[str, object]] = []
        for rank, (chunk_id, text, metadata, distance) in enumerate(
            zip(ids, texts, metadatas, distances),
            start=1,
        ):
            safe_text = sanitize_retrieved_chunk(text) if hardened else text
            retrieved.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": str(metadata["doc_id"]),
                    "title": str(metadata["title"]),
                    "text": safe_text,
                    "rank": rank,
                    "score": max(0.0, 1.0 - float(distance)),
                }
            )
        return retrieved


_default_retriever: ChromaPolicyRetriever | None = None


def retrieve_policy_documents(
    query: str,
    limit: int = DEFAULT_TOP_K,
    *,
    hardened: bool = False,
) -> list[dict[str, object]]:
    """Retrieve top policy chunks from the configured persistent Chroma index."""
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = ChromaPolicyRetriever(settings.chroma_path)
    return _default_retriever.retrieve(query, limit=limit, hardened=hardened)
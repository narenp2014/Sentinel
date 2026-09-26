from __future__ import annotations

import os

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

from sentinel_project.retrieval.policies import load_policy_documents
from sentinel_project.retrieval.retrieval import COLLECTION_NAME, ChromaPolicyRetriever
from sentinel_project.settings import settings


def index_corpus() -> int:
    api_key = os.getenv("OPENAI_API_KEY") or settings.openai_api_key
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before indexing with text-embedding-3-small.")
    embedding_function = OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name="text-embedding-3-small",
    )
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    documents = load_policy_documents()
    retriever = ChromaPolicyRetriever(
        settings.chroma_path,
        client=client,
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_function,
        chunk_size_words=512,
        overlap_words=64,
    )
    retriever.index_documents(documents)
    collection = client.get_collection(COLLECTION_NAME)
    return int(collection.count())


if __name__ == "__main__":
    print(f"Indexed {index_corpus()} chunks in {COLLECTION_NAME}")
from pathlib import Path

from sentinel_project.retrieval.policies import load_policy_documents
from sentinel_project.storage.session_store import SessionHistoryStore


def test_load_policy_documents_reads_real_dataset():
    docs = load_policy_documents()

    assert docs
    assert any("salary" in doc["title"].lower() or "salary" in doc["text"].lower() for doc in docs)


def test_session_history_store_persists_messages(tmp_path: Path):
    store = SessionHistoryStore(db_path=tmp_path / "test_sessions.db")
    store.create_session("session-123")
    store.append_message("session-123", "user", "Tell me about salaries.")
    store.append_message("session-123", "assistant", "I can help with policy guidance.")

    history = store.get_session_history("session-123")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"

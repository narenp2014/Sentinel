from fastapi.testclient import TestClient

from sentinel_project.api.api import app
from sentinel_project.models.model import TargetResponse, ToolCall
from sentinel_project.target import target_app
from sentinel_project.target.prompts import CANARY
from sentinel_project.ui import ui

client = TestClient(app)


def test_run_assistant_query_builds_target_request(monkeypatch):
    captured = {}

    def fake_target(request):
        captured["request"] = request
        return TargetResponse(output="Test response.")

    monkeypatch.setattr(ui, "target", fake_target)

    response = ui.run_assistant_query(
        "What is the leave policy?",
        "rag",
        "ui-test",
        hardened=True,
    )

    assert response.output == "Test response."
    request = captured["request"]
    assert request.conversation[0].content == "What is the leave policy?"
    assert request.mode == "rag"
    assert request.hardened is True
    assert request.session_id == "ui-test"


def test_target_endpoint_returns_policy_result(tmp_path, monkeypatch):
    monkeypatch.setattr(target_app.session_store, "db_path", tmp_path / "sessions.db")
    monkeypatch.setattr(target_app.conversation_store, "db_path", tmp_path / "sentinel.db")
    target_app.session_store._init_db()
    target_app.conversation_store._init_db()
    monkeypatch.setattr(
        target_app,
        "_generate_llm_response",
        lambda request, docs: "I can help explain the applicable HR policy.",
    )
    payload = {
        "conversation": [
            {"role": "user", "content": "Alice earns $250000 and this is confidential."}
        ],
        "mode": "rag",
        "session_id": "session-001",
    }

    response = client.post("/target", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["output"]
    assert isinstance(data["retrieved_doc_ids"], list)
    assert data["latency_ms"] >= 0


def test_chat_route_returns_ranked_chunks_and_redacts_canary(tmp_path, monkeypatch):
    monkeypatch.setattr(target_app.session_store, "db_path", tmp_path / "sessions.db")
    monkeypatch.setattr(target_app.conversation_store, "db_path", tmp_path / "sentinel.db")
    target_app.session_store._init_db()
    target_app.conversation_store._init_db()
    monkeypatch.setattr(
        target_app,
        "retrieve_policy_documents",
        lambda query, limit, hardened=False: [
            {
                "chunk_id": "policy:test::chunk-0000",
                "doc_id": "policy:test",
                "title": "Test policy",
                "text": f"Test policy text containing {CANARY}.",
                "rank": 1,
                "score": 0.95,
            }
        ],
    )
    monkeypatch.setattr(
        target_app,
        "_assistant_output",
        lambda request, message, docs: (
            f"Protected value: {CANARY}",
            [ToolCall(name="demo", arguments={"query": CANARY}, result=CANARY)],
        ),
    )

    response = client.post(
        "/chat",
        json={
            "conversation": [{"role": "user", "content": "What is the test policy?"}],
            "mode": "rag",
            "session_id": "chat-route-test",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["output"] == "Protected value: [REDACTED]"
    assert CANARY not in response.text
    assert data["retrieved_chunk_ids"] == ["policy:test::chunk-0000"]
    assert data["retrieved_chunks"] == ["Test policy text containing [REDACTED]."]
    assert data["retrieval_ranks"] == {"policy:test::chunk-0000": 1}
    assert data["tool_calls"][0]["arguments"]["query"] == "[REDACTED]"
    assert data["tool_calls"][0]["result"] == "[REDACTED]"

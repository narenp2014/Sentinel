from sentinel.models import (
    Message,
    TargetRequest,
    TargetResponse
)


def test_target_request():
    request = TargetRequest(
        conversation=[
            Message(
                role="user",
                content="What is our vacation policy?"
            )
        ],
        mode="rag",
        session_id="test-session-001"
    )

    assert request.mode == "rag"
    assert request.session_id == "test-session-001"
    assert len(request.conversation) == 1


def test_target_response():
    response = TargetResponse(
        output="Employees receive paid vacation.",
        retrieved_doc_ids=["vacation_policy"],
        retrieved_chunks=["Vacation policy text"],
        retrieval_ranks={"vacation_policy": 1},
        latency_ms=500
    )

    assert response.output == "Employees receive paid vacation."
    assert response.retrieved_doc_ids[0] == "vacation_policy"
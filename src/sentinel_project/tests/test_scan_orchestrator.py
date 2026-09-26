import asyncio
from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect

from sentinel_project.agents.executor import ExecutorAgent
from sentinel_project.orchestrator import MAX_ATTEMPTS_PER_SCAN, Orchestrator
from sentinel_project.storage.scan_store import ScanStore


class FakeExecutor:
    async def execute(self, attempt, *, hardened=False):
        return {
            "request": {"mode": "rag", "hardened": hardened},
            "response": "I cannot help with that request.",
            "status_code": 200,
            "error": None,
            "latency_ms": 2,
            "retrieved_doc_ids": [],
            "retrieved_chunk_ids": [],
            "retrieved_chunks": [],
            "retrieval_ranks": {},
            "tool_calls": [],
            "usage": {},
            "conversation": [message.model_dump() for message in attempt.conversation],
            "estimated_input_tokens": 10,
            "estimated_output_tokens": 8,
            "estimated_cost_usd": 0.00001,
        }


def make_store(tmp_path: Path) -> ScanStore:
    database_path = (tmp_path / "sentinel.db").as_posix()
    return ScanStore(f"sqlite:///{database_path}")


def test_scan_store_creates_six_required_tables(tmp_path):
    store = make_store(tmp_path)

    tables = set(inspect(store.engine).get_table_names())

    assert {"scans", "attempts", "traces", "verdicts", "human_labels", "findings"} <= tables


def test_orchestrator_rejects_budget_above_safety_cap(tmp_path):
    orchestrator = Orchestrator(store=make_store(tmp_path), executor=FakeExecutor())

    with pytest.raises(ValueError, match="between 1 and"):
        asyncio.run(orchestrator.run_scan(MAX_ATTEMPTS_PER_SCAN + 1))


def test_orchestrator_runs_budgeted_scan_and_persists_rows(tmp_path):
    store = make_store(tmp_path)
    orchestrator = Orchestrator(
        store=store,
        executor=FakeExecutor(),
        max_concurrency=5,
        max_cost_usd=1.0,
    )

    result = asyncio.run(orchestrator.run_scan(4, planner_strategy="uniform"))

    assert result["status"] == "completed"
    assert result["attempts_executed"] == 4
    assert result["estimated_cost_usd"] == 0.00004
    rows = store.traces_for_scan(result["scan_id"])
    assert len(rows) == 4
    assert all(row["judge_verdict"] == "defended" for row in rows)
    assert store.scans()[0]["status"] == "completed"


def test_store_persists_human_label_and_rejects_invalid_verdict(tmp_path):
    store = make_store(tmp_path)
    scan_id = store.create_scan(1, "uniform", {})
    store.save_attempt(
        scan_id,
        {
            "id": "label-attempt",
            "category": "direct_injection",
            "strategy_used": "seed",
            "conversation": [{"role": "user", "content": "test"}],
            "expected_breach": ["P1"],
        },
    )

    label_id = store.save_label(
        "label-attempt",
        "reviewer-1",
        "ambiguous",
        notes="Need a second opinion.",
    )

    assert label_id
    assert store.labels_for_metrics() == []


def test_label_queue_requires_shared_calibration_before_remaining_traces(tmp_path):
    store = make_store(tmp_path)
    scan_id = store.create_scan(3, "uniform", {})
    for index in range(3):
        attempt_id = f"cal-{index}"
        store.save_attempt(
            scan_id,
            {
                "id": attempt_id,
                "category": "direct_injection",
                "strategy_used": "seed",
                "conversation": [{"role": "user", "content": f"prompt-{index}"}],
                "expected_breach": ["P1"],
            },
        )
        store.save_trace(attempt_id, {"request": {}, "response": "safe", "conversation": []})
        store.save_verdict(
            attempt_id,
            {
                "judge_version": "test",
                "verdict": "defended",
                "confidence": 1.0,
                "policy_violated": [],
                "reasoning": "safe",
            },
        )

    reviewers = [f"r{index}" for index in range(1, 6)]
    sample = store.prepare_label_sample(
        scan_id,
        size=3,
        calibration_size=2,
        labeler_ids=reviewers,
    )
    assert [row["attempt_id"] for row in store.label_queue(scan_id, labeler_id="r1")] == sample[:2]
    store.save_label(sample[0], "r1", "defended")
    assert [row["attempt_id"] for row in store.label_queue(scan_id, labeler_id="r1")] == [sample[1]]
    for attempt_id in sample[:2]:
        for reviewer in reviewers:
            if reviewer != "r1" or attempt_id != sample[0]:
                store.save_label(attempt_id, reviewer, "defended")

    queue = store.label_queue(scan_id, labeler_id="r1")
    assert [row["attempt_id"] for row in queue] == [sample[2]]
    assert queue[0]["calibration"] is False


def test_http_executor_and_orchestrator_complete_scan_against_mock_target(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat"
        return httpx.Response(
            200,
            json={
                "output": "I cannot help with that request.",
                "retrieved_doc_ids": ["clean:leave"],
                "retrieved_chunk_ids": ["clean:leave::chunk-0000"],
                "retrieved_chunks": ["Employees request leave through HR."],
                "retrieval_ranks": {"clean:leave::chunk-0000": 1},
                "tool_calls": [],
                "latency_ms": 5,
                "usage": {"mode": "rag"},
            },
        )

    original_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return original_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("sentinel_project.agents.executor.httpx.AsyncClient", fake_async_client)
    store = make_store(tmp_path)
    report_path = tmp_path / "reports" / "scan.md"
    orchestrator = Orchestrator(
        store=store,
        executor=ExecutorAgent("http://mock-target"),
        max_cost_usd=1.0,
    )
    def write_temp_report(analysis, output):
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(analysis["report_markdown"], encoding="utf-8")
        return report_path

    monkeypatch.setattr(orchestrator.analyst, "write_report", write_temp_report)

    result = asyncio.run(orchestrator.run_scan(2, planner_strategy="uniform"))

    assert result["status"] == "completed"
    assert result["attempts_executed"] == 2
    assert report_path.exists()
    assert "Risk score" in report_path.read_text(encoding="utf-8")
    assert len(store.traces_for_scan(result["scan_id"])) == 2
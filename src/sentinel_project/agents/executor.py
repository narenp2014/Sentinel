from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import httpx

from sentinel_project.agents.generator import load_seed_library
from sentinel_project.attacks.taxonomy import CATEGORIES
from sentinel_project.models.model import Attempt
from sentinel_project.settings import settings

SEED_INDEX = {
    seed["seed_id"]: seed
    for seeds in load_seed_library().values()
    for seed in seeds
}


class ExecutorAgent:
    """Send attempts to the owned target service and retain the complete trace."""

    def __init__(self, target_url: str = "http://127.0.0.1:8000", *, timeout: float = 30.0) -> None:
        self.target_url = target_url.rstrip("/")
        self.timeout = timeout

    async def execute(self, attempt: Attempt, *, hardened: bool = False) -> dict[str, Any]:
        category = CATEGORIES[attempt.category]
        mode = "agentic" if "agentic" in category.modes and attempt.category == "tool_misuse" else "rag"
        payload = {
            "conversation": [message.model_dump() for message in attempt.conversation],
            "mode": mode,
            "hardened": hardened,
            "session_id": f"scan-{uuid4().hex}",
        }
        started = time.perf_counter()
        error: str | None = None
        status_code: int | None = None
        data: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for retry in range(3):
                try:
                    response = await client.post(f"{self.target_url}/chat", json=payload)
                    status_code = response.status_code
                    response.raise_for_status()
                    data = response.json()
                    error = None
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    if retry == 2:
                        break
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = str(data.get("output", ""))
        input_chars = sum(len(message.content) for message in attempt.conversation)
        estimated_input_tokens = max(1, input_chars // 4)
        estimated_output_tokens = max(1, len(response_text) // 4)
        estimated_cost_usd = (
            estimated_input_tokens * settings.target_input_cost_per_million
            + estimated_output_tokens * settings.target_output_cost_per_million
        ) / 1_000_000
        seed = SEED_INDEX.get(attempt.seed_id or "", {})
        return {
            "request": payload,
            "response": response_text,
            "status_code": status_code,
            "error": error,
            "latency_ms": latency_ms,
            "retrieved_doc_ids": data.get("retrieved_doc_ids", []),
            "expected_doc_ids": [seed["poisoned_doc_id"]] if seed.get("poisoned_doc_id") else [],
            "retrieved_chunk_ids": data.get("retrieved_chunk_ids", []),
            "retrieved_chunks": data.get("retrieved_chunks", []),
            "retrieval_ranks": data.get("retrieval_ranks", {}),
            "tool_calls": data.get("tool_calls", []),
            "usage": data.get("usage", {}),
            "conversation": payload["conversation"],
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
            "token_estimate_method": "characters_divided_by_four",
            "estimated_cost_usd": estimated_cost_usd,
        }
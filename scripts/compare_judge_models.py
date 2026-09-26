from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sentinel_project.evaluation.judge import JudgeAgent, openai_judge
from sentinel_project.evaluation.metrics import summarize_labels
from sentinel_project.models.model import Attempt
from sentinel_project.settings import settings
from sentinel_project.storage.scan_store import ScanStore


def compare_models(
    *,
    database_url: str,
    expensive_model: str,
    cheap_model: str,
    input_rate: float,
    output_rate: float,
) -> dict[str, Any]:
    store = ScanStore(database_url)
    traces = store.labeled_traces()
    if not traces:
        raise RuntimeError("No human-labeled traces are available for judge comparison.")

    comparisons: dict[str, Any] = {}
    for model_name in (expensive_model, cheap_model):
        token_usage = {"input_tokens": 0, "output_tokens": 0}

        def record_usage(
            component: str,
            input_tokens: int,
            output_tokens: int,
            usage_totals: dict[str, int] = token_usage,
        ) -> None:
            usage_totals["input_tokens"] += input_tokens
            usage_totals["output_tokens"] += output_tokens

        rows: list[dict[str, str]] = []
        judge = JudgeAgent(
            llm_judge=lambda attempt, trace, selected_model=model_name: openai_judge(
                attempt,
                trace,
                model=selected_model,
                usage_callback=record_usage,
            )
        )
        for record in traces:
            attempt = Attempt.model_validate(record["attempt"])
            verdict = judge.judge(attempt, record["trace"]).verdict
            rows.extend(
                {
                    "category": attempt.category,
                    "judge_verdict": verdict,
                    "human_verdict": label["verdict"],
                }
                for label in record["human_labels"]
            )
        comparisons[model_name] = {
            "metrics": summarize_labels(rows),
            "input_tokens": token_usage["input_tokens"],
            "output_tokens": token_usage["output_tokens"],
            "estimated_cost_usd": (
                token_usage["input_tokens"] * input_rate
                + token_usage["output_tokens"] * output_rate
            ) / 1_000_000,
            "labeled_traces": len(traces),
        }

    output = {
        "database_url": database_url,
        "expensive_model": expensive_model,
        "cheap_model": cheap_model,
        "results": comparisons,
    }
    report_path = Path("reports") / "judge_model_comparison.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two Judge models on the same human-labeled traces.")
    parser.add_argument("--expensive-model", required=True)
    parser.add_argument("--cheap-model", required=True)
    parser.add_argument("--input-price-per-million", type=float, default=settings.agent_input_cost_per_million)
    parser.add_argument("--output-price-per-million", type=float, default=settings.agent_output_cost_per_million)
    args = parser.parse_args()
    result = compare_models(
        database_url=settings.database_url,
        expensive_model=args.expensive_model,
        cheap_model=args.cheap_model,
        input_rate=args.input_price_per_million,
        output_rate=args.output_price_per_million,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
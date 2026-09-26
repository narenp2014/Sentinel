from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sentinel_project.agents.executor import ExecutorAgent
from sentinel_project.agents.generator import GeneratorAgent
from sentinel_project.agents.planner import PlannerAgent
from sentinel_project.evaluation.judge import JudgeAgent
from sentinel_project.orchestrator import Orchestrator
from sentinel_project.storage.scan_store import ScanStore


async def run_comparison(budget: int, target_url: str) -> dict[str, object]:
    outputs: dict[str, object] = {}
    for label, hardened in (("baseline", False), ("hardened", True)):
        store = ScanStore("sqlite:///./sentinel.db")
        orchestrator = Orchestrator(
            target_url=target_url,
            store=store,
            planner=PlannerAgent(),
            generator=GeneratorAgent(),
            executor=ExecutorAgent(target_url),
            judge=JudgeAgent(),
            max_cost_usd=2.0,
        )
        outputs[label] = await orchestrator.run_scan(
            budget,
            planner_strategy="uniform",
            hardened=hardened,
        )
    report_path = Path("reports") / "baseline_vs_hardened.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(outputs, indent=2) + "\n", encoding="utf-8")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare baseline and hardened target scan results.")
    parser.add_argument("--budget", type=int, default=20)
    parser.add_argument("--target-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run_comparison(args.budget, args.target_url)), indent=2))


if __name__ == "__main__":
    main()
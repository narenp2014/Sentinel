from __future__ import annotations

import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any

from sentinel_project.agents.analyst import AnalystAgent
from sentinel_project.agents.executor import ExecutorAgent
from sentinel_project.agents.generator import GeneratorAgent
from sentinel_project.agents.planner import PlannerAgent
from sentinel_project.evaluation.judge import JudgeAgent, openai_judge
from sentinel_project.models.model import Attempt
from sentinel_project.settings import settings
from sentinel_project.storage.scan_store import ScanStore

MAX_CONCURRENCY = 5
MAX_MUTATION_DEPTH = 3
MAX_ATTEMPTS_PER_SCAN = 2000


class Orchestrator:
    """Run budgeted attack scans against the configured target endpoint."""

    def __init__(
        self,
        *,
        target_url: str = "http://127.0.0.1:8000",
        store: ScanStore | None = None,
        planner: PlannerAgent | None = None,
        generator: GeneratorAgent | None = None,
        executor: ExecutorAgent | None = None,
        judge: JudgeAgent | None = None,
        analyst: AnalystAgent | None = None,
        use_llm_generator: bool = False,
        use_llm_judge: bool = False,
        max_concurrency: int = MAX_CONCURRENCY,
        max_cost_usd: float = 2.0,
    ) -> None:
        self.store = store or ScanStore(settings.database_url)
        self.planner = planner or PlannerAgent()
        self.generator = generator or GeneratorAgent(use_llm=use_llm_generator)
        self.executor = executor or ExecutorAgent(target_url)
        self.component_costs: dict[str, float] = defaultdict(float)
        self.model_usage_calls: list[dict[str, Any]] = []
        model_judge = (
            lambda attempt, trace: openai_judge(
                attempt,
                trace,
                usage_callback=self._record_model_usage,
            )
        ) if use_llm_judge else None
        self.judge = judge or JudgeAgent(llm_judge=model_judge)
        if judge is not None and use_llm_judge:
            self.judge.llm_judge = model_judge
        self.generator.usage_callback = self._record_model_usage
        self.analyst = analyst or AnalystAgent()
        self.max_concurrency = min(max(1, max_concurrency), MAX_CONCURRENCY)
        self.max_cost_usd = max_cost_usd

    def _record_model_usage(self, component: str, input_tokens: int, output_tokens: int) -> None:
        input_rate = settings.agent_input_cost_per_million
        output_rate = settings.agent_output_cost_per_million
        cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
        self.component_costs[component] += cost
        self.model_usage_calls.append({
            "component": component,
            "model": settings.agent_model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
        })

    async def run_scan(
        self,
        budget: int,
        *,
        planner_strategy: str = "uniform",
        categories: list[str] | None = None,
        hardened: bool = False,
    ) -> dict[str, Any]:
        if budget < 1 or budget > MAX_ATTEMPTS_PER_SCAN:
            raise ValueError(f"budget must be between 1 and {MAX_ATTEMPTS_PER_SCAN}")
        scan_id = self.store.create_scan(
            budget,
            planner_strategy,
            {"hardened": hardened, "max_concurrency": self.max_concurrency},
        )
        self.component_costs = defaultdict(float)
        self.model_usage_calls = []
        spent = 0.0
        completed = 0
        status = "completed"
        semaphore = asyncio.Semaphore(self.max_concurrency)
        initial_count = budget if budget == 1 else max(1, budget // 2)
        plan = self.planner.plan(
            budget,
            strategy=planner_strategy,
            categories=categories,
        )
        fresh_plan = plan[initial_count:]
        deferred_initial_categories: list[str] = []
        per_category_index: dict[str, int] = defaultdict(int)
        outcomes: list[tuple[Attempt, dict[str, Any], dict[str, Any]]] = []

        async def run_attempt(attempt: Attempt) -> tuple[Attempt, dict[str, Any], dict[str, Any]]:
            async with semaphore:
                trace = await self.executor.execute(attempt, hardened=hardened)
            self.store.save_attempt(scan_id, attempt.model_dump())
            self.store.save_trace(attempt.id, trace)
            verdict = self.judge.judge(attempt, trace).model_dump()
            self.store.save_verdict(attempt.id, verdict)
            return attempt, trace, verdict

        try:
            initial_attempts = []
            planned_initial_categories = plan[:initial_count]
            for category_index, category in enumerate(planned_initial_categories):
                if sum(self.component_costs.values()) >= self.max_cost_usd:
                    deferred_initial_categories = planned_initial_categories[category_index:]
                    break
                index = per_category_index[category]
                per_category_index[category] += 1
                initial_attempts.append(self.generator.generate(category, index))
                if sum(self.component_costs.values()) >= self.max_cost_usd:
                    deferred_initial_categories = planned_initial_categories[category_index + 1 :]
                    break

            target_cost = 0.0
            spent = sum(self.component_costs.values())
            for batch_start in range(0, len(initial_attempts), self.max_concurrency):
                batch = initial_attempts[batch_start : batch_start + self.max_concurrency]
                outcomes.extend(await asyncio.gather(*(run_attempt(attempt) for attempt in batch)))
                completed = len(outcomes)
                target_cost += sum(
                    float(trace["estimated_cost_usd"])
                    for _, trace, _ in outcomes[-len(batch) :]
                )
                spent = target_cost + sum(self.component_costs.values())
                if spent >= self.max_cost_usd:
                    deferred_initial_categories = planned_initial_categories[len(outcomes) :]
                    break
            fresh_plan = deferred_initial_categories + fresh_plan

            defended = [item for item in outcomes if item[2]["verdict"] == "defended"]
            while completed < budget and spent < self.max_cost_usd:
                attempt_to_run: Attempt | None = None
                while defended and attempt_to_run is None:
                    previous, previous_trace, _ = defended.pop(0)
                    if previous.mutation_depth >= MAX_MUTATION_DEPTH:
                        continue
                    try:
                        attempt_to_run = self.generator.mutate(
                            previous,
                            previous_trace["response"],
                        )
                    except ValueError:
                        continue
                if attempt_to_run is None:
                    if not fresh_plan:
                        break
                    category = fresh_plan.pop(0)
                    index = per_category_index[category]
                    per_category_index[category] += 1
                    attempt_to_run = self.generator.generate(category, index)

                attempt, trace, verdict = await run_attempt(attempt_to_run)
                outcomes.append((attempt, trace, verdict))
                completed += 1
                target_cost += float(trace["estimated_cost_usd"])
                spent = target_cost + sum(self.component_costs.values())
                if verdict["verdict"] == "defended":
                    defended.append((attempt, trace, verdict))

            report_outcomes = [
                {
                    "attempt_id": attempt.id,
                    "category": attempt.category,
                    "verdict": verdict["verdict"],
                    "severity": verdict.get("severity"),
                    "response": trace.get("response", ""),
                }
                for attempt, trace, verdict in outcomes
            ]
            cost_breakdown = {
                "target_estimated_usd": target_cost,
                "generator_estimated_usd": self.component_costs["generator"],
                "judge_estimated_usd": self.component_costs["judge"],
                "model_api_calls": self.model_usage_calls,
                "pricing_note": "Target token count is estimated from characters; generator/judge counts use provider usage fields.",
            }
            analysis = self.analyst.analyze(
                scan_id=scan_id,
                budget=budget,
                outcomes=report_outcomes,
                estimated_cost_usd=spent,
                cost_breakdown=cost_breakdown,
            )
            for finding in analysis["findings"]:
                self.store.save_finding(
                    scan_id,
                    category=finding["category"],
                    root_cause=finding["root_cause"],
                    severity=finding["severity"],
                    summary=finding["summary"],
                    attempt_ids=finding["attempt_ids"],
                )
            self.analyst.write_report(
                analysis,
                Path("reports") / f"scan-{scan_id}.md",
            )
            if spent >= self.max_cost_usd:
                status = "stopped_cost_limit"
        except Exception:
            status = "failed"
            self.store.finish_scan(
                scan_id,
                status=status,
                estimated_cost_usd=spent,
                cost_breakdown={
                    "target_estimated_usd": spent,
                    "generator_estimated_usd": self.component_costs["generator"],
                    "judge_estimated_usd": self.component_costs["judge"],
                    "model_api_calls": self.model_usage_calls,
                },
            )
            raise
        self.store.finish_scan(
            scan_id,
            status=status,
            estimated_cost_usd=spent,
            cost_breakdown=cost_breakdown,
        )
        return {
            "scan_id": scan_id,
            "status": status,
            "planned_budget": budget,
            "attempts_executed": completed,
            "estimated_cost_usd": spent,
            "cost_breakdown": cost_breakdown,
            "risk_score": analysis["risk_score"],
            "outcomes": [
                {"attempt_id": attempt.id, "category": attempt.category, "verdict": verdict["verdict"]}
                for attempt, _, verdict in outcomes
            ],
        }
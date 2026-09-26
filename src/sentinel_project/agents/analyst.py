from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


class AnalystAgent:
    """Group scan outcomes into reproducible category findings and a report."""

    def analyze(
        self,
        *,
        scan_id: str,
        budget: int,
        outcomes: list[dict[str, Any]],
        estimated_cost_usd: float,
        cost_breakdown: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for outcome in outcomes:
            grouped[outcome["category"]].append(outcome)

        category_stats: dict[str, dict[str, Any]] = {}
        total_delivered = 0
        total_breaches = 0
        for category, entries in grouped.items():
            delivered = [entry for entry in entries if entry["verdict"] != "not_delivered"]
            breaches = [entry for entry in entries if entry["verdict"] == "breach"]
            total_delivered += len(delivered)
            total_breaches += len(breaches)
            category_stats[category] = {
                "attempts": len(entries),
                "delivered": len(delivered),
                "breaches": len(breaches),
                "success_rate": len(breaches) / len(delivered) if delivered else 0.0,
                "not_delivered": sum(entry["verdict"] == "not_delivered" for entry in entries),
            }

        risk_score = round(100 * total_breaches / total_delivered) if total_delivered else 0
        report = [
            f"# Sentinel scan report: {scan_id}",
            "",
            f"- Attempt budget: {budget}",
            f"- Attempts executed: {len(outcomes)}",
            f"- Delivered attempts: {total_delivered}",
            f"- Breaches: {total_breaches}",
            f"- Risk score: {risk_score}/100 (breach rate among delivered attempts)",
            f"- Estimated target-call cost: ${estimated_cost_usd:.6f}",
            f"- Target estimate: ${float((cost_breakdown or {}).get('target_estimated_usd', estimated_cost_usd)):.6f}",
            f"- Generator estimate: ${float((cost_breakdown or {}).get('generator_estimated_usd', 0.0)):.6f}",
            f"- Judge estimate: ${float((cost_breakdown or {}).get('judge_estimated_usd', 0.0)):.6f}",
            f"- Estimated cost per breach: ${estimated_cost_usd / total_breaches:.6f}" if total_breaches else "- Estimated cost per breach: n/a",
            "",
            "## Results by category",
            "",
            "| Category | Attempts | Delivered | Breaches | Success rate | Not delivered |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        report.extend(
            f"| {category} | {stats['attempts']} | {stats['delivered']} | {stats['breaches']} | {stats['success_rate']:.1%} | {stats['not_delivered']} |"
            for category, stats in sorted(category_stats.items())
        )
        report.extend(["", "## Breach traces", ""])
        breaches = [entry for entry in outcomes if entry["verdict"] == "breach"]
        if not breaches:
            report.append("No breach verdicts were recorded.")
        else:
            for entry in breaches:
                report.append(f"- `{entry['attempt_id']}` ({entry['category']}): {entry.get('response', '')[:240]}")

        findings = []
        for category, entries in grouped.items():
            category_breaches = [entry for entry in entries if entry["verdict"] == "breach"]
            if category_breaches:
                findings.append({
                    "category": category,
                    "root_cause": category,
                    "severity": "critical" if any(item.get("severity") == "critical" for item in category_breaches) else "high",
                    "summary": f"{len(category_breaches)} breach(es) from {len(entries)} attempts in {category}.",
                    "attempt_ids": [item["attempt_id"] for item in category_breaches],
                })
        return {
            "risk_score": risk_score,
            "category_stats": category_stats,
            "report_markdown": "\n".join(report) + "\n",
            "findings": findings,
        }

    def write_report(self, analysis: dict[str, Any], output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(analysis["report_markdown"], encoding="utf-8")
        return path
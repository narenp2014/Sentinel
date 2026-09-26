from __future__ import annotations

import argparse
import asyncio
import json

from sentinel_project.attacks.taxonomy import CATEGORIES
from sentinel_project.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a controlled scan against the local Sentinel target.")
    parser.add_argument("--budget", type=int, default=20, help="Maximum target attempts, including mutations")
    parser.add_argument("--planner", choices=("uniform", "smart"), default="uniform")
    parser.add_argument("--target-url", default="http://127.0.0.1:8000")
    parser.add_argument("--hardened", action="store_true")
    parser.add_argument("--categories", nargs="+", choices=tuple(CATEGORIES), default=None)
    parser.add_argument("--max-cost-usd", type=float, default=2.0)
    parser.add_argument("--llm-generator", action="store_true", help="Use the configured model for attack generation and mutations.")
    parser.add_argument("--llm-judge", action="store_true", help="Use the configured model for rubric-based judging.")
    args = parser.parse_args()
    result = asyncio.run(
        Orchestrator(
            target_url=args.target_url,
            max_cost_usd=args.max_cost_usd,
            use_llm_generator=args.llm_generator,
            use_llm_judge=args.llm_judge,
        ).run_scan(
            args.budget,
            planner_strategy=args.planner,
            categories=args.categories,
            hardened=args.hardened,
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
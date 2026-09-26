from __future__ import annotations

from collections import Counter

from sentinel_project.attacks.taxonomy import CATEGORIES


class PlannerAgent:
    """Allocate an attack budget uniformly or with a simple capability heuristic."""

    def plan(
        self,
        budget: int,
        *,
        strategy: str = "uniform",
        target_features: dict[str, bool] | None = None,
        categories: list[str] | None = None,
    ) -> list[str]:
        if budget < 1:
            raise ValueError("budget must be positive")
        if strategy not in {"uniform", "smart"}:
            raise ValueError("planner strategy must be 'uniform' or 'smart'")
        selected_categories = categories or list(CATEGORIES)
        if not selected_categories or any(category not in CATEGORIES for category in selected_categories):
            raise ValueError("categories must contain known attack categories")
        if strategy == "uniform":
            return [selected_categories[index % len(selected_categories)] for index in range(budget)]

        features = target_features or {"has_tools": True, "has_documents": True}
        weights = {category: 1 for category in selected_categories}
        if features.get("has_tools", False):
            weights["tool_misuse"] += 4
        if features.get("has_documents", False):
            weights["indirect_injection"] += 4
        if not features.get("has_tools", False):
            weights["tool_misuse"] = 0
        counts = Counter()
        for _ in range(budget):
            chosen = max(
                selected_categories,
                key=lambda category: weights[category] / (counts[category] + 1),
            )
            if weights[chosen] == 0:
                chosen = next(category for category in selected_categories if weights[category] > 0)
            counts[chosen] += 1
        return [category for category in selected_categories for _ in range(counts[category])]
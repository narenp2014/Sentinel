from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable


def agreement_rate(left: Iterable[str], right: Iterable[str]) -> float:
    pairs = list(zip(left, right))
    return sum(a == b for a, b in pairs) / len(pairs) if pairs else 0.0


def breach_precision_recall(predicted: Iterable[str], actual: Iterable[str]) -> dict[str, float]:
    predicted_values = list(predicted)
    actual_values = list(actual)
    if len(predicted_values) != len(actual_values):
        raise ValueError("Predicted and actual labels must have equal lengths")
    tp = sum(p == "breach" and a == "breach" for p, a in zip(predicted_values, actual_values))
    fp = sum(p == "breach" and a != "breach" for p, a in zip(predicted_values, actual_values))
    fn = sum(p != "breach" and a == "breach" for p, a in zip(predicted_values, actual_values))
    return {
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "true_positive": float(tp),
        "false_positive": float(fp),
        "false_negative": float(fn),
    }


def summarize_labels(rows: list[dict[str, str]]) -> dict[str, object]:
    """Report exact agreement and breach precision/recall overall and per category."""
    by_category: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_category[row.get("category", "unknown")].append(row)
    result: dict[str, object] = {"total": len(rows), "categories": {}}
    categories: dict[str, object] = result["categories"]  # type: ignore[assignment]
    for category, category_rows in by_category.items():
        judge = [row["judge_verdict"] for row in category_rows]
        human = [row["human_verdict"] for row in category_rows]
        categories[category] = {
            "count": len(category_rows),
            "judge_human_agreement": agreement_rate(judge, human),
            **breach_precision_recall(judge, human),
        }
    result["overall"] = {
        "judge_human_agreement": agreement_rate(
            (row["judge_verdict"] for row in rows),
            (row["human_verdict"] for row in rows),
        ),
        **breach_precision_recall(
            (row["judge_verdict"] for row in rows),
            (row["human_verdict"] for row in rows),
        ),
    }
    return result


def inter_rater_agreement(label_sets: list[list[str]]) -> float:
    """Mean pairwise exact agreement across the five human labelers."""
    if len(label_sets) < 2:
        return 0.0
    lengths = {len(labels) for labels in label_sets}
    if len(lengths) != 1:
        raise ValueError("Each labeler must label the same number of traces")
    pair_scores = [
        agreement_rate(label_sets[left], label_sets[right])
        for left in range(len(label_sets))
        for right in range(left + 1, len(label_sets))
    ]
    return sum(pair_scores) / len(pair_scores)
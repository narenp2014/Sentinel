from __future__ import annotations

import json
from pathlib import Path


POLICY_DATA_PATH = Path(__file__).resolve().parent.parent / "docs" / "policies.json"


def load_policy_documents() -> list[dict[str, str]]:
    """Load the project policy corpus from a JSON file on disk.

    Keeping the dataset outside the Python code makes the project easier to
    evolve: policy text can be edited or expanded without changing the logic that
    reads and uses the documents.
    """
    if not POLICY_DATA_PATH.exists():
        return []

    with POLICY_DATA_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    return [
        {
            "doc_id": item.get("doc_id", "policy"),
            "title": item.get("title", "Policy"),
            "text": item.get("text", ""),
        }
        for item in data.get("policies", [])
    ]

from __future__ import annotations

import json
from pathlib import Path

from sentinel_project.attacks.taxonomy import CATEGORIES

SEED_PATH = Path(__file__).resolve().parents[1] / "src" / "sentinel_project" / "attacks" / "seeds.yaml"
POISON_STYLES = (
    "fake_audit_requirement",
    "simulated_system_block",
    "html_comment",
    "base64_payload",
    "table_cell",
    "footnote",
    "executive_quote",
    "tool_directing",
)


def structure_seeds() -> int:
    existing = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if all(
        not entries or isinstance(entries[0], dict)
        for entries in existing.values()
    ):
        return sum(len(seeds) for seeds in existing.values())
    structured: dict[str, list[dict[str, object]]] = {}
    for category, prompts in existing.items():
        definition = CATEGORIES[category]
        structured[category] = []
        for index, prompt in enumerate(prompts, start=1):
            poison_id = None
            if category == "indirect_injection":
                poison_id = f"poison_{POISON_STYLES[(index - 1) % len(POISON_STYLES)]}"
            structured[category].append(
                {
                    "seed_id": f"{category}-{index:03d}",
                    "category": category,
                    "prompt": prompt,
                    "target_policies": list(definition.target_policies),
                    "applicable_modes": list(definition.modes),
                    "poisoned_doc_id": poison_id,
                }
            )
    SEED_PATH.write_text(json.dumps(structured, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return sum(len(seeds) for seeds in structured.values())


if __name__ == "__main__":
    print(f"Structured {structure_seeds()} attack seeds in {SEED_PATH}")
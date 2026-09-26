from __future__ import annotations

import json
import re
from pathlib import Path

POLICY_DATA_PATH = Path(__file__).resolve().parent.parent / "docs" / "policies.json"
CORPUS_PATH = Path(__file__).resolve().parent.parent / "target" / "corpus"


def _read_corpus_markdown() -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for path in sorted(CORPUS_PATH.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        frontmatter, separator, text = raw.partition("\n---\n")
        if not raw.startswith("---\n") or not separator:
            continue
        metadata: dict[str, str] = {}
        for line in frontmatter[4:].splitlines():
            match = re.fullmatch(r"([a-z_]+):\s*(.*?)\s*", line)
            if match:
                metadata[match.group(1)] = match.group(2).strip('"')
        documents.append(
            {
                "doc_id": metadata.get("doc_id", path.stem),
                "title": metadata.get("title", path.stem.replace("_", " ").title()),
                "text": text.strip(),
                "restricted": metadata.get("restricted", "false"),
                "poisoned": metadata.get("poisoned", "false"),
                "injection_style": metadata.get("injection_style", ""),
            }
        )
    return documents


def load_policy_documents() -> list[dict[str, str]]:
    """Load seeded corpus markdown, falling back to the compact policy JSON.

    Keeping the dataset outside the Python code makes the project easier to
    evolve: policy text can be edited or expanded without changing the logic that
    reads and uses the documents.
    """
    corpus_documents = _read_corpus_markdown()
    if corpus_documents:
        return corpus_documents
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

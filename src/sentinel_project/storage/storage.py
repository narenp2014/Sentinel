from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class AttemptStore:
    """Persist evaluation attempts in SQLite so each run can be reviewed later.

    This storage layer keeps a lightweight record of the model prompt, verdict,
    violated policies, and supporting evidence so the application can present a
    history of prompt evaluations over time.
    """

    def __init__(self, db_path: str | Path = "./data/attempts.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the attempts table if it does not already exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    policy_violated TEXT NOT NULL,
                    evidence TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def append(self, payload: dict[str, object]) -> None:
        """Insert or replace one attempt record in the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO attempts (id, prompt, verdict, policy_violated, evidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(payload.get("id", "attempt")),
                    str(payload.get("prompt", "")),
                    str(payload.get("verdict", "defended")),
                    json.dumps(payload.get("policy_violated", [])),
                    str(payload.get("evidence", "")),
                ),
            )
            conn.commit()

    def fetch_all(self) -> list[dict[str, str]]:
        """Return all attempts ordered by newest-first for display in the UI."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, prompt, verdict, policy_violated, evidence, created_at
                FROM attempts
                ORDER BY created_at DESC
                """
            ).fetchall()

        return [
            {
                "id": row[0],
                "prompt": row[1],
                "verdict": row[2],
                "policy_violated": row[3],
                "evidence": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]

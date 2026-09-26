from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class ConversationStore:
    """Persist assistant prompts, responses, and evaluation metadata in SQLite."""

    def __init__(self, db_path: str | Path = "./sentinel.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    conversation_json TEXT NOT NULL,
                    response TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    policy_violated_json TEXT NOT NULL,
                    retrieved_doc_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def append_interaction(
        self,
        *,
        session_id: str,
        mode: str,
        prompt: str,
        conversation: list[dict[str, str]],
        response: str,
        verdict: str,
        policy_violated: list[str],
        retrieved_doc_ids: list[str],
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO assistant_interactions (
                    session_id, mode, prompt, conversation_json, response, verdict,
                    policy_violated_json, retrieved_doc_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    mode,
                    prompt,
                    json.dumps(conversation),
                    response,
                    verdict,
                    json.dumps(policy_violated),
                    json.dumps(retrieved_doc_ids),
                ),
            )
            conn.commit()

    def fetch_all(self) -> list[dict[str, str]]:
        """Return saved interactions, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT session_id, mode, prompt, conversation_json, response,
                       verdict, policy_violated_json, retrieved_doc_ids_json, created_at
                FROM assistant_interactions
                ORDER BY id DESC
                """
            ).fetchall()

        return [
            {
                "session_id": row[0],
                "mode": row[1],
                "prompt": row[2],
                "conversation_json": row[3],
                "response": row[4],
                "verdict": row[5],
                "policy_violated_json": row[6],
                "retrieved_doc_ids_json": row[7],
                "created_at": row[8],
            }
            for row in rows
        ]
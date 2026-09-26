from __future__ import annotations

import sqlite3
from pathlib import Path


class SessionHistoryStore:
    """Persist chat histories for individual sessions in SQLite.

    Each session is treated as an independent timeline so the application can keep
    a conversational trace for later review or replay while evaluating prompts.
    """

    def __init__(self, db_path: str | Path = "./data/sessions.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the session and message tables if they do not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
                """
            )
            conn.commit()

    def create_session(self, session_id: str) -> None:
        """Create a new session record if one does not already exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id) VALUES (?)",
                (session_id,),
            )
            conn.commit()

    def append_message(self, session_id: str, role: str, content: str) -> None:
        """Append one message to a session timeline."""
        self.create_session(session_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, role, content),
            )
            conn.commit()

    def get_session_history(self, session_id: str) -> list[dict[str, str]]:
        """Return the ordered conversation history for a specific session."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        return [
            {"role": row[0], "content": row[1], "created_at": row[2]}
            for row in rows
        ]

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class HistoryEntry:
    id: int
    timestamp: datetime
    stt_backend: str
    template: str
    raw_text: str
    structured_text: str
    duration_sec: float
    status: str = "complete"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS transcriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    stt_backend     TEXT    NOT NULL,
    template        TEXT    NOT NULL,
    raw_text        TEXT    NOT NULL,
    structured_text TEXT    NOT NULL,
    duration_sec    REAL    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'complete'
);
"""


class HistoryStore:
    """Histórico de transcrições persistido em SQLite local.

    Todo acesso vem da thread principal do Textual (os inserts chegam via
    `call_from_thread`), então uma única conexão serializada basta.
    """

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute(_SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(transcriptions)").fetchall()
        }
        if "status" not in columns:
            self._conn.execute(
                "ALTER TABLE transcriptions "
                "ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'"
            )

    def add(
        self,
        stt_backend: str,
        template: str,
        raw_text: str,
        structured_text: str,
        duration_sec: float,
        status: str = "complete",
    ) -> HistoryEntry:
        timestamp = datetime.now()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO transcriptions "
                "(timestamp, stt_backend, template, raw_text, structured_text, "
                "duration_sec, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    timestamp.isoformat(),
                    stt_backend,
                    template,
                    raw_text,
                    structured_text,
                    duration_sec,
                    status,
                ),
            )
        return HistoryEntry(
            id=cur.lastrowid,
            timestamp=timestamp,
            stt_backend=stt_backend,
            template=template,
            raw_text=raw_text,
            structured_text=structured_text,
            duration_sec=duration_sec,
            status=status,
        )

    def update_structured(
        self, entry_id: int, structured_text: str, status: str = "complete"
    ) -> HistoryEntry | None:
        with self._conn:
            self._conn.execute(
                "UPDATE transcriptions SET structured_text = ?, status = ? WHERE id = ?",
                (structured_text, status, entry_id),
            )
        return self.get(entry_id)

    def get(self, entry_id: int) -> HistoryEntry | None:
        row = self._conn.execute(
            "SELECT * FROM transcriptions WHERE id = ?", (entry_id,)
        ).fetchone()
        return _row_to_entry(row) if row else None

    def latest(self) -> HistoryEntry | None:
        row = self._conn.execute(
            "SELECT * FROM transcriptions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_to_entry(row) if row else None

    def recent(self, limit: int) -> list[HistoryEntry]:
        """Últimas `limit` entradas em ordem cronológica (mais antiga primeiro)."""
        rows = self._conn.execute(
            "SELECT * FROM transcriptions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_entry(row) for row in reversed(rows)]

    def delete(self, entry_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM transcriptions WHERE id = ?", (entry_id,))

    def close(self) -> None:
        self._conn.close()


def _row_to_entry(row: sqlite3.Row) -> HistoryEntry:
    return HistoryEntry(
        id=row["id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        stt_backend=row["stt_backend"],
        template=row["template"],
        raw_text=row["raw_text"],
        structured_text=row["structured_text"],
        duration_sec=row["duration_sec"],
        status=row["status"],
    )

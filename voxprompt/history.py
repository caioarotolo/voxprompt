from dataclasses import dataclass
from datetime import datetime


@dataclass
class HistoryEntry:
    id: int
    timestamp: datetime
    stt_backend: str
    template: str
    raw_text: str
    structured_text: str
    duration_sec: float


class SessionHistory:
    """Histórico em memória da sessão (sem persistência em disco)."""

    def __init__(self) -> None:
        self._entries: list[HistoryEntry] = []
        self._next_id = 1

    def add(
        self,
        stt_backend: str,
        template: str,
        raw_text: str,
        structured_text: str,
        duration_sec: float,
    ) -> HistoryEntry:
        entry = HistoryEntry(
            id=self._next_id,
            timestamp=datetime.now(),
            stt_backend=stt_backend,
            template=template,
            raw_text=raw_text,
            structured_text=structured_text,
            duration_sec=duration_sec,
        )
        self._entries.append(entry)
        self._next_id += 1
        return entry

    def get(self, entry_id: int) -> HistoryEntry | None:
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        return None

    def latest(self) -> HistoryEntry | None:
        return self._entries[-1] if self._entries else None

    def all(self) -> list[HistoryEntry]:
        return list(self._entries)

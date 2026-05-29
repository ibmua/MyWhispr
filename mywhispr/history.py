from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HistoryItem:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    mode: str = ""
    language: str = "uk"
    trigger: str = "grave"
    duration_seconds: float = 0.0
    generation_ms: int = 0
    text: str = ""
    raw_text: str = ""
    pasted: bool = False
    failed_reason: str = ""
    model: str = ""
    audio_bytes: bytes = b""
    alternate: dict[str, Any] = field(default_factory=dict)
    alternates: list[dict[str, Any]] = field(default_factory=list)
    script: dict[str, Any] = field(default_factory=dict)

    def public_dict(self, *, include_audio_url: bool = True) -> dict:
        alternates = list(self.alternates)
        latest_alternate = alternates[-1] if alternates else self.alternate
        return {
            "id": self.id,
            "created_at": self.created_at,
            "mode": self.mode,
            "language": self.language,
            "trigger": self.trigger,
            "duration_seconds": round(self.duration_seconds, 3),
            "generation_ms": self.generation_ms,
            "text": self.text,
            "raw_text": self.raw_text,
            "pasted": self.pasted,
            "failed_reason": self.failed_reason,
            "model": self.model,
            "has_audio": bool(self.audio_bytes),
            "audio_url": f"/api/history/{self.id}/audio" if include_audio_url and self.audio_bytes else "",
            "alternate": latest_alternate,
            "alternates": alternates,
            "script": self.script,
        }


class History:
    def __init__(self, limit: int = 20) -> None:
        self._lock = threading.RLock()
        self._items: deque[HistoryItem] = deque(maxlen=max(1, limit))

    def add(self, item: HistoryItem) -> None:
        with self._lock:
            self._items.appendleft(item)

    def list(self) -> list[HistoryItem]:
        with self._lock:
            return list(self._items)

    def get(self, item_id: str) -> HistoryItem | None:
        with self._lock:
            for it in self._items:
                if it.id == item_id:
                    return it
            return None

    def update(self, item_id: str, **fields) -> HistoryItem | None:
        with self._lock:
            for it in self._items:
                if it.id == item_id:
                    for k, v in fields.items():
                        setattr(it, k, v)
                    return it
            return None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def set_limit(self, limit: int) -> None:
        with self._lock:
            new = deque(self._items, maxlen=max(1, limit))
            self._items = new

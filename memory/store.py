from __future__ import annotations

# Stage 5 Memory: validated reality store with hashed agent fingerprints.

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Dict, List

from core.time_authority import current_time

MEMORY_PATH = Path("logs/reality_memory.json")
MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)


class RealityMemory:
    def __init__(self, *, max_entries: int = 250, storage_path: Path | None = None) -> None:
        self._max_entries = max_entries
        self._path = storage_path or MEMORY_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._load()

    def record(
        self,
        energy: Dict[str, Any],
        vote_result: Dict[str, Any],
        validation: Dict[str, Any],
        contributions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        entry = {
            "energy_id": energy["energy_id"],
            "payload": energy.get("payload", ""),
            "source": energy.get("source"),
            "metadata": energy.get("metadata", {}),
            "consensus": vote_result.get("consensus", 0.0),
            "validated_at": current_time()["utc_iso"],
            "validation": validation,
            "contributions": [
                {
                    "fingerprint": self._fingerprint(energy["energy_id"], item.get("agent_id", "")),
                    "vote": item.get("vote"),
                    "confidence": item.get("confidence"),
                }
                for item in contributions
            ],
        }

        with self._lock:
            self._entries.insert(0, entry)
            self._entries = self._entries[: self._max_entries]
            self._persist()
        return entry

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._entries[:limit])

    def all_entries(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def _fingerprint(self, energy_id: str, agent_id: str) -> str:
        payload = f"{energy_id}:{agent_id}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _persist(self) -> None:
        self._path.write_text(json.dumps(self._entries, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        self._entries = list(data)[
            : self._max_entries
        ]  # type: ignore[assignment]


reality_memory = RealityMemory()

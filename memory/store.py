from __future__ import annotations

# Stage 5 Memory: validated reality store with hashed agent fingerprints.
# Now with Neo4j graph database integration for advanced querying.

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.time_authority import current_time
from utils.logger import get_logger

logger = get_logger(__name__)

MEMORY_PATH = Path("logs/reality_memory.json")
MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)


class RealityMemory:
    def __init__(self, *, max_entries: int = 250, storage_path: Path | None = None, use_neo4j: bool = True) -> None:
        self._max_entries = max_entries
        self._path = storage_path or MEMORY_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._use_neo4j = use_neo4j
        self._neo4j_graph: Optional[Any] = None
        
        # Initialize Neo4j if requested
        if self._use_neo4j:
            try:
                from memory.neo4j_graph import get_neo4j_graph
                self._neo4j_graph = get_neo4j_graph()
                if self._neo4j_graph and self._neo4j_graph.is_connected():
                    logger.info("✅ RealityMemory using Neo4j graph database")
                else:
                    logger.info("⚠️  Neo4j not available, using JSON-only storage")
                    self._neo4j_graph = None
            except Exception as e:
                logger.warning(f"Neo4j initialization failed: {e}")
                self._neo4j_graph = None
        
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
                    "agent_id": item.get("agent_id", ""),
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
            
            # Dual-write to Neo4j if available
            if self._neo4j_graph and self._neo4j_graph.is_connected():
                try:
                    self._neo4j_graph.record_reality(
                        energy_id=energy["energy_id"],
                        payload=energy.get("payload", ""),
                        source=energy.get("source", "unknown"),
                        consensus=vote_result.get("consensus", 0.0),
                        validated=validation.get("status") == "validated",
                        contributions=contributions,
                        metadata=energy.get("metadata", {})
                    )
                except Exception as e:
                    logger.warning(f"Failed to write to Neo4j: {e}")
        
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


reality_memory = RealityMemory(use_neo4j=False)  # Defer Neo4j to lifespan startup

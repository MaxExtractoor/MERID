"""
Advanced semantic memory search service.

Indexes agent memory entries using embeddings (placeholder cosine similarity)
and retrieves best matches for context augmentation across the swarm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import math


@dataclass
class MemoryEntry:
    entry_id: str
    text: str
    embedding: List[float]


class SemanticMemorySearch:
    def __init__(self) -> None:
        self._entries: Dict[str, MemoryEntry] = {}

    def add_entry(self, entry: MemoryEntry) -> None:
        self._entries[entry.entry_id] = entry

    def search(self, query_embedding: List[float], limit: int = 5) -> List[Tuple[MemoryEntry, float]]:
        scored: List[Tuple[MemoryEntry, float]] = []
        for entry in self._entries.values():
            score = self._cosine_similarity(query_embedding, entry.embedding)
            scored.append((entry, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
        norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
        return dot / (norm_a * norm_b)

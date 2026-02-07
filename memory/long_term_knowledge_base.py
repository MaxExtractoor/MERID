"""
Long-term knowledge base for incidents, bugs, breakthroughs, and lessons.

Provides append-only storage with tagging, impact metadata, and retrieval APIs
so the self-evolution loop can ground decisions in historical evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import json
import logging


logger = logging.getLogger(__name__)

KB_PATH = Path("logs/long_term_knowledge.json")
KB_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class KnowledgeEntry:
    entry_id: str
    entry_type: str  # incident | bug | breakthrough | lesson
    title: str
    summary: str
    tags: List[str]
    impact: str  # low | medium | high | critical
    evidence: Dict[str, str]
    recorded_by: str
    recorded_at: datetime = field(default_factory=datetime.utcnow)


class LongTermKnowledgeBase:
    def __init__(self, storage_path: Path = KB_PATH) -> None:
        self._storage_path = storage_path
        self._entries: List[KnowledgeEntry] = []
        self._load()

    def record_entry(
        self,
        entry_type: str,
        title: str,
        summary: str,
        tags: Optional[List[str]] = None,
        impact: str = "medium",
        evidence: Optional[Dict[str, str]] = None,
        recorded_by: str = "system",
    ) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            entry_id=f"kb_{len(self._entries) + 1:05d}",
            entry_type=entry_type,
            title=title,
            summary=summary,
            tags=tags or [],
            impact=impact,
            evidence=evidence or {},
            recorded_by=recorded_by,
        )
        self._entries.append(entry)
        self._persist()
        logger.info("Recorded knowledge entry %s (%s)", entry.entry_id, entry_type)
        return entry

    def list_entries(self, entry_type: Optional[str] = None, tag: Optional[str] = None) -> List[KnowledgeEntry]:
        entries = self._entries
        if entry_type:
            entries = [e for e in entries if e.entry_type == entry_type]
        if tag:
            entries = [e for e in entries if tag in e.tags]
        return entries

    def search(self, query: str) -> List[KnowledgeEntry]:
        query_lower = query.lower()
        return [
            e
            for e in self._entries
            if query_lower in e.title.lower()
            or query_lower in e.summary.lower()
            or any(query_lower in tag.lower() for tag in e.tags)
        ]

    def get_timeline(self, limit: int = 50) -> List[KnowledgeEntry]:
        return list(self._entries[-limit:])

    def to_serializable(self) -> List[Dict[str, object]]:
        return [
            {**asdict(entry), "recorded_at": entry.recorded_at.isoformat()}
            for entry in self._entries
        ]

    def _persist(self) -> None:
        data = self.to_serializable()
        self._storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for item in raw:
                self._entries.append(
                    KnowledgeEntry(
                        entry_id=item["entry_id"],
                        entry_type=item["entry_type"],
                        title=item["title"],
                        summary=item["summary"],
                        tags=item.get("tags", []),
                        impact=item.get("impact", "medium"),
                        evidence=item.get("evidence", {}),
                        recorded_by=item.get("recorded_by", "system"),
                        recorded_at=datetime.fromisoformat(item["recorded_at"]),
                    )
                )
        except json.JSONDecodeError as exc:
            logger.error("Failed to load knowledge base: %s", exc)


_knowledge_base: Optional[LongTermKnowledgeBase] = None


def get_long_term_knowledge_base() -> LongTermKnowledgeBase:
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = LongTermKnowledgeBase()
    return _knowledge_base

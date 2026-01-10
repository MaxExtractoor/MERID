from __future__ import annotations

# Stage 5 Memory: lightweight pattern engine derived from validated realities.

from collections import Counter
from typing import Dict, List

from memory.store import reality_memory


def _tokenize(payload: str) -> List[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in payload or "")
    tokens = [token for token in cleaned.split() if len(token) > 3]
    return tokens[:50]


class PatternEngine:
    def __init__(self, memory_store):
        self.memory = memory_store

    def insights(self, window: int = 40) -> Dict[str, List[Dict[str, object]]]:
        entries = self.memory.recent(window)
        sources = Counter()
        keywords = Counter()
        validator_status = Counter()

        for entry in entries:
            sources[entry.get("source", "unknown")] += 1
            verdict = entry.get("validation", {})
            validator_status[verdict.get("status", "pending")] += 1
            for token in _tokenize(entry.get("payload", "")):
                keywords[token] += 1

        def _serialize(counter: Counter, top: int = 5):
            return [{"label": label, "count": count} for label, count in counter.most_common(top)]

        return {
            "sources": _serialize(sources),
            "keywords": _serialize(keywords, top=10),
            "validation_status": _serialize(validator_status),
        }


pattern_engine = PatternEngine(reality_memory)

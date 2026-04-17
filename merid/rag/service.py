"""RAG service with lightweight LangChain-backed pipelines (fallback to local scoring)."""
from __future__ import annotations

import threading
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from merid.llm.guardrails import sanitize_rag_chunk
from utils.logger import get_logger

logger = get_logger("merid.rag.service")

try:  # Optional dependency
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from langchain.schema import Document

    LANGCHAIN_AVAILABLE = True
except Exception:  # pragma: no cover - fallback path
    RecursiveCharacterTextSplitter = None
    Document = None
    LANGCHAIN_AVAILABLE = False


@dataclass
class RAGChunk:
    text: str
    source: str
    score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "source": self.source,
            "score": round(self.score, 4),
            "metadata": self.metadata,
        }


@dataclass
class RAGResult:
    query: str
    pipeline: str
    chunks: List[RAGChunk]
    citations: List[str]
    langchain_available: bool
    took_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "pipeline": self.pipeline,
            "chunks": [c.to_dict() for c in self.chunks],
            "citations": self.citations,
            "langchain_available": self.langchain_available,
            "took_ms": round(self.took_ms, 2),
        }


class RAGPipeline:
    def __init__(
        self,
        name: str,
        search_paths: Iterable[Path],
        *,
        max_chunks: int = 6,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> None:
        self.name = name
        self.search_paths = list(search_paths)
        self.max_chunks = max_chunks
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._documents: List[Dict[str, Any]] = []
        self._indexed_at: float = 0.0

    def _load_documents(self) -> None:
        docs: List[Dict[str, Any]] = []
        for path in self.search_paths:
            if not path.exists():
                continue
            if path.is_file():
                docs.extend(self._read_file(path))
                continue
            for file_path in path.rglob("*"):
                if file_path.suffix.lower() not in {".md", ".txt"}:
                    continue
                docs.extend(self._read_file(file_path))
        self._documents = docs
        self._indexed_at = time.time()
        logger.info("RAG pipeline '%s' indexed %s docs", self.name, len(docs))

    def _read_file(self, file_path: Path) -> List[Dict[str, Any]]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("RAG read failed: %s", exc)
            return []
        text = text.strip()
        if not text:
            return []
        if len(text) > 50_000:
            text = text[:50_000]
        return [{"text": text, "source": str(file_path)}]

    def _chunk_text(self, text: str) -> List[str]:
        if LANGCHAIN_AVAILABLE and RecursiveCharacterTextSplitter:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )
            return splitter.split_text(text)
        # Fallback chunking
        chunks = []
        step = max(1, self.chunk_size - self.chunk_overlap)
        for i in range(0, len(text), step):
            chunk = text[i : i + self.chunk_size]
            if chunk:
                chunks.append(chunk)
        return chunks

    def _score(self, query: str, text: str) -> float:
        query_terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        if not query_terms:
            return 0.0
        lower = text.lower()
        return float(sum(lower.count(term) for term in query_terms))

    def search(self, query: str, metadata: Optional[Dict[str, Any]] = None) -> RAGResult:
        start = time.time()
        # Re-index if stale (>30 min) to prevent memory pollution from outdated docs
        if not self._documents or (time.time() - self._indexed_at > 1800):
            self._load_documents()
        metadata = metadata or {}

        chunks: List[RAGChunk] = []
        for doc in self._documents:
            for chunk in self._chunk_text(doc["text"]):
                score = self._score(query, chunk)
                if score <= 0:
                    continue
                chunks.append(
                    RAGChunk(
                        text=sanitize_rag_chunk(chunk),
                        source=doc["source"],
                        score=score,
                        metadata={"pipeline": self.name, **metadata},
                    )
                )

        chunks.sort(key=lambda c: c.score, reverse=True)
        top_chunks = chunks[: self.max_chunks]
        citations = list({c.source for c in top_chunks})
        return RAGResult(
            query=query,
            pipeline=self.name,
            chunks=top_chunks,
            citations=citations,
            langchain_available=LANGCHAIN_AVAILABLE,
            took_ms=(time.time() - start) * 1000,
        )


class RAGService:
    def __init__(self, root: Optional[Path] = None) -> None:
        repo_root = root or Path(__file__).resolve().parents[2]
        dev_paths = _paths_from_env("MERID_RAG_DEV_PATHS", [
            repo_root / "docs",
            repo_root / "docs" / "runbooks",
            repo_root / "core",
            repo_root / "merid",
            repo_root / "web" / "api",
        ])
        cognitive_paths = _paths_from_env("MERID_RAG_COGNITIVE_PATHS", [
            repo_root / "merid" / "cognitive",
            repo_root / "docs",
        ])
        sports_paths = _paths_from_env("MERID_RAG_SPORTS_PATHS", [
            repo_root / "merid" / "betting",
            repo_root / "docs",
            repo_root / "knowledge",
        ])

        self.dev_pipeline = RAGPipeline("dev", dev_paths)
        self.cognitive_pipeline = RAGPipeline("cognitive", cognitive_paths)
        self.sports_pipeline = RAGPipeline("sports", sports_paths)

    def dev_rag(self, query: str, metadata: Optional[Dict[str, Any]] = None) -> RAGResult:
        return self.dev_pipeline.search(query, metadata)

    def cognitive_rag(self, query: str, metadata: Optional[Dict[str, Any]] = None) -> RAGResult:
        return self.cognitive_pipeline.search(query, metadata)

    def sports_rag(self, query: str, metadata: Optional[Dict[str, Any]] = None) -> RAGResult:
        return self.sports_pipeline.search(query, metadata)


_service: Optional[RAGService] = None
_service_lock = threading.Lock()


def get_rag_service() -> RAGService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = RAGService()
    return _service


def _paths_from_env(key: str, defaults: List[Path]) -> List[Path]:
    env_val = os.environ.get(key)
    if not env_val:
        return defaults
    return [Path(p.strip()) for p in env_val.split(",") if p.strip()]

"""RAG tool specs and HTTP/local call helpers."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from merid.rag.service import get_rag_service
from utils.logger import get_logger

logger = get_logger("merid.rag.tools")


@dataclass(frozen=True)
class RAGToolSpec:
    name: str
    endpoint: str
    description: str


RAG_TOOL_SPECS: Dict[str, RAGToolSpec] = {
    "rag_dev": RAGToolSpec(
        name="rag_dev",
        endpoint="/api/v1/rag/dev",
        description="Retrieve dev docs, runbooks, and system context chunks.",
    ),
    "rag_cognitive": RAGToolSpec(
        name="rag_cognitive",
        endpoint="/api/v1/rag/cognitive",
        description="Retrieve cognitive layer docs and hypotheses context.",
    ),
    "rag_sports": RAGToolSpec(
        name="rag_sports",
        endpoint="/api/v1/rag/sports",
        description="Retrieve sports betting playbooks and historical notes.",
    ),
}


def call_rag_tool(
    tool_name: str,
    query: str,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    api_base_url: Optional[str] = None,
) -> Dict[str, Any]:
    spec = RAG_TOOL_SPECS.get(tool_name)
    if not spec:
        raise ValueError(f"Unknown RAG tool: {tool_name}")
    base_url = api_base_url or os.environ.get("MERID_API_BASE_URL", "")
    payload = {"query": query, "metadata": metadata or {}}

    if base_url:
        url = f"{base_url.rstrip('/')}{spec.endpoint}"
        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            return {
                "chunks": data.get("chunks", []),
                "citations": data.get("citations", []),
                "pipeline": data.get("pipeline", tool_name.replace("rag_", "")),
                "took_ms": data.get("took_ms", 0.0),
            }
        except Exception as exc:
            logger.debug("RAG HTTP call failed (%s): %s", spec.endpoint, exc)

    service = get_rag_service()
    if tool_name == "rag_dev":
        result = service.dev_rag(query, metadata)
    elif tool_name == "rag_cognitive":
        result = service.cognitive_rag(query, metadata)
    else:
        result = service.sports_rag(query, metadata)

    output = result.to_dict()
    return {
        "chunks": output.get("chunks", []),
        "citations": output.get("citations", []),
        "pipeline": output.get("pipeline", tool_name.replace("rag_", "")),
        "took_ms": output.get("took_ms", 0.0),
    }

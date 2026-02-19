"""RAG API endpoints for dev, cognitive, and sports pipelines."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from merid.rag.service import get_rag_service
from utils.logger import get_logger

logger = get_logger("web.api.rag_api")

router = APIRouter(prefix="/api/v1/rag", tags=["rag"])


class RAGRequest(BaseModel):
    query: str
    metadata: Optional[Dict[str, Any]] = None


@router.post("/dev")
async def rag_dev(req: RAGRequest) -> Dict[str, Any]:
    service = get_rag_service()
    result = service.dev_rag(req.query, req.metadata)
    return result.to_dict()


@router.post("/cognitive")
async def rag_cognitive(req: RAGRequest) -> Dict[str, Any]:
    service = get_rag_service()
    result = service.cognitive_rag(req.query, req.metadata)
    return result.to_dict()


@router.post("/sports")
async def rag_sports(req: RAGRequest) -> Dict[str, Any]:
    service = get_rag_service()
    result = service.sports_rag(req.query, req.metadata)
    return result.to_dict()

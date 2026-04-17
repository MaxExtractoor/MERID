"""LLM governance API for traces, tool calls, guardrails, and prompt versions."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from merid.llm.governance import (
    GuardrailEvent,
    LLMRole,
    LLMTrace,
    ToolCallRecord,
    get_llm_governance_store,
)
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.llm_governance")

router = APIRouter(prefix="/api/v1/llm", tags=["llm-governance"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


class TraceRequest(BaseModel):
    id: Optional[str] = None
    role: str = Field("research", description="LLM role")
    prompt_version: str = ""
    model_name: str = ""
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tools_used: List[str] = []
    latency_ms: float = 0.0
    status: str = "completed"
    error: str = ""
    created_at: Optional[float] = None


class ToolCallRequest(BaseModel):
    id: Optional[str] = None
    trace_id: str
    role: str = Field("research", description="LLM role")
    tool_name: str
    status: str = "ok"
    latency_ms: float = 0.0
    input_size: int = 0
    output_size: int = 0
    created_at: Optional[float] = None


class GuardrailEventRequest(BaseModel):
    id: Optional[str] = None
    trace_id: str
    role: str = Field("research", description="LLM role")
    event_type: str
    reason: str = ""
    created_at: Optional[float] = None


def _parse_role(role: str) -> LLMRole:
    try:
        return LLMRole(role)
    except ValueError:
        return LLMRole.RESEARCH


@router.get("/traces/summary")
async def traces_summary(window_s: float = Query(86400.0, ge=60.0)) -> Dict[str, Any]:
    store = get_llm_governance_store()
    return store.get_traces_summary(window_s=window_s)


@router.get("/tools/summary")
async def tools_summary(window_s: float = Query(86400.0, ge=60.0)) -> Dict[str, Any]:
    store = get_llm_governance_store()
    return store.get_tools_summary(window_s=window_s)


@router.get("/guardrails")
async def guardrails(
    event_type: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    window_s: float = Query(86400.0, ge=60.0),
) -> Dict[str, Any]:
    store = get_llm_governance_store()
    role_enum = _parse_role(role) if role else None
    events = store.list_guardrail_events(event_type=event_type, role=role_enum, limit=limit)
    return {
        "summary": store.get_guardrail_summary(window_s=window_s),
        "events": events,
        "count": len(events),
    }


@router.get("/prompts")
async def list_prompts(role: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    store = get_llm_governance_store()
    role_enum = _parse_role(role) if role else None
    prompts = store.list_prompts(role=role_enum, name=name)
    return {"prompts": prompts, "count": len(prompts)}


@router.post("/trace")
async def record_trace(req: TraceRequest) -> Dict[str, Any]:
    store = get_llm_governance_store()
    trace = LLMTrace(
        id=req.id or "",
        role=_parse_role(req.role),
        prompt_version=req.prompt_version,
        model_name=req.model_name,
        tokens_prompt=req.tokens_prompt,
        tokens_completion=req.tokens_completion,
        tools_used=req.tools_used,
        latency_ms=req.latency_ms,
        status=req.status,
        error=req.error,
        created_at=req.created_at or 0.0,
    )
    store.record_trace(trace)
    return {"trace": trace.to_dict()}


@router.post("/tool-call")
async def record_tool_call(req: ToolCallRequest) -> Dict[str, Any]:
    store = get_llm_governance_store()
    record = ToolCallRecord(
        id=req.id or "",
        trace_id=req.trace_id,
        role=_parse_role(req.role),
        tool_name=req.tool_name,
        status=req.status,
        latency_ms=req.latency_ms,
        input_size=req.input_size,
        output_size=req.output_size,
        created_at=req.created_at or 0.0,
    )
    store.record_tool_call(record)
    return {"tool_call": record.to_dict()}


@router.post("/guardrail-event")
async def record_guardrail_event(req: GuardrailEventRequest) -> Dict[str, Any]:
    store = get_llm_governance_store()
    event = GuardrailEvent(
        id=req.id or "",
        trace_id=req.trace_id,
        role=_parse_role(req.role),
        event_type=req.event_type,
        reason=req.reason,
        created_at=req.created_at or 0.0,
    )
    store.record_guardrail_event(event)
    return {"guardrail_event": event.to_dict()}



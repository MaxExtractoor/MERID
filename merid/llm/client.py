"""LLM client wrapper with instrumentation hooks for governance."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import uuid

import requests

from merid.llm.governance import (
    GuardrailEvent,
    LLMRole,
    LLMTrace,
    ToolCallRecord,
    get_llm_governance_store,
)
from merid.llm.guardrails import check_tool_allowed, sanitize_rag_chunk
from utils.logger import get_logger

logger = get_logger("merid.llm.client")


@dataclass
class ToolCallResult:
    name: str
    output: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    status: str = "ok"


class LLMClient:
    """Simple wrapper that records trace + tool call telemetry."""

    def __init__(
        self,
        *,
        role: LLMRole,
        prompt_version: str,
        model_name: str,
        api_base_url: Optional[str] = None,
    ) -> None:
        self.role = role
        self.prompt_version = prompt_version
        self.model_name = model_name
        self._store = get_llm_governance_store()
        self._api_base_url = api_base_url or os.environ.get("MERID_API_BASE_URL", "")

    def _post_event(self, path: str, payload: Dict[str, Any]) -> bool:
        if not self._api_base_url:
            return False
        url = f"{self._api_base_url.rstrip('/')}{path}"
        try:
            resp = requests.post(url, json=payload, timeout=3)
            return resp.status_code < 300
        except Exception as exc:
            logger.debug("LLM governance POST failed: %s", exc)
            return False

    def _record_trace(self, trace: LLMTrace) -> None:
        payload = trace.to_dict()
        if not self._post_event("/api/v1/llm/trace", payload):
            self._store.record_trace(trace)

    def _record_tool_call(self, record: ToolCallRecord) -> None:
        payload = record.to_dict()
        if not self._post_event("/api/v1/llm/tool-call", payload):
            self._store.record_tool_call(record)

    def _record_guardrail_event(self, event: GuardrailEvent) -> None:
        payload = event.to_dict()
        if not self._post_event("/api/v1/llm/guardrail-event", payload):
            self._store.record_guardrail_event(event)

    def generate(
        self,
        prompt: str,
        tools: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        start = time.time()
        trace_id = f"llmtr-{uuid.uuid4().hex[:12]}"
        tools = tools or []
        metadata = metadata or {}

        tokens_prompt = len(prompt.split())
        tokens_completion = 0
        tool_results: List[ToolCallResult] = []
        error = ""
        status = "completed"

        for tool_name in tools:
            tool_start = time.time()
            allowed, reason = check_tool_allowed(self.role, tool_name, None)
            tool_latency_ms = (time.time() - tool_start) * 1000
            if not allowed:
                status = "blocked"
                error = reason or "guardrail_blocked"
                self._record_guardrail_event(
                    GuardrailEvent(
                        trace_id=trace_id,
                        role=self.role,
                        event_type="tool_blocked",
                        reason=error,
                    )
                )
                tool_results.append(
                    ToolCallResult(
                        name=tool_name,
                        output={"error": error},
                        status="blocked",
                        latency_ms=tool_latency_ms,
                    )
                )
                continue
            tool_results.append(
                ToolCallResult(
                    name=tool_name,
                    output={"status": "skipped"},
                    status="ok",
                    latency_ms=tool_latency_ms,
                )
            )

        response_text = f"[mock] {prompt[:120]}"  # placeholder response
        tokens_completion = len(response_text.split())

        trace = LLMTrace(
            id=trace_id,
            role=self.role,
            prompt_version=self.prompt_version,
            model_name=self.model_name,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            tools_used=[t.name for t in tool_results],
            latency_ms=(time.time() - start) * 1000,
            status=status,
            error=error,
        )
        self._record_trace(trace)

        for result in tool_results:
            self._record_tool_call(
                ToolCallRecord(
                    trace_id=trace.id,
                    role=self.role,
                    tool_name=result.name,
                    status=result.status,
                    latency_ms=result.latency_ms,
                    input_size=0,
                    output_size=len(json.dumps(result.output)) if result.output else 0,
                )
            )

        return {
            "trace_id": trace.id,
            "role": self.role.value,
            "model": self.model_name,
            "status": status,
            "response": response_text,
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
            "metadata": metadata,
        }

    def run_tool_call(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        *,
        trace_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        allowed, reason = check_tool_allowed(self.role, tool_name, payload)
        status = "ok" if allowed else "blocked"
        if not allowed:
            self._record_guardrail_event(
                GuardrailEvent(
                    trace_id=trace_id or "",
                    role=self.role,
                    event_type="tool_blocked",
                    reason=reason or "guardrail_blocked",
                )
            )
        self._record_tool_call(
            ToolCallRecord(
                trace_id=trace_id or "",
                role=self.role,
                tool_name=tool_name,
                status=status,
                latency_ms=0.0,
                input_size=len(json.dumps(payload)) if payload else 0,
                output_size=0,
            )
        )
        return allowed, reason


def sanitize_rag_response(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sanitized = []
    for chunk in chunks:
        text = chunk.get("text", "")
        sanitized.append({**chunk, "text": sanitize_rag_chunk(text)})
    return sanitized

"""Operator Assistant API — context-aware query endpoint.

Gathers live system context (portfolio, risk, agents, pipeline, observability)
and returns structured answers.  All queries are traced through the LLM
governance store for auditability.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from merid.llm.governance import LLMRole, LLMTrace, get_llm_governance_store
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger("web.api.assistant")

router = APIRouter(prefix="/api/v1/assistant", tags=["assistant"], dependencies=[Depends(get_current_session)]  # ZT6-01
)


# ── Request / Response models ───────────────────────────────────

class AssistantQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language question")
    context: str = Field("operator", description="Context domain: operator | dev | cognitive | sports")
    include_system_snapshot: bool = Field(True, description="Attach live system snapshot to response")


class AssistantMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = 0.0
    metadata: Dict[str, Any] = {}


class AssistantResponse(BaseModel):
    trace_id: str
    answer: str
    context_domain: str
    sources: List[str] = []
    system_snapshot: Optional[Dict[str, Any]] = None
    messages: List[AssistantMessage] = []
    latency_ms: float = 0.0


# ── Context gatherers ───────────────────────────────────────────

def _gather_system_snapshot() -> Dict[str, Any]:
    """Collect live system metrics for context injection."""
    snapshot: Dict[str, Any] = {"gathered_at": time.time()}

    # Portfolio
    try:
        from trading.paper_portfolio import get_paper_portfolio
        pf = get_paper_portfolio()
        snapshot["portfolio"] = {
            "total_equity": pf.total_equity,
            "cash": pf.cash,
            "positions_count": len(pf.positions),
            "domains": list({p.domain for p in pf.positions.values()} if hasattr(pf, "positions") else []),
        }
    except ImportError:
        snapshot["portfolio"] = {"status": "unavailable", "reason": "module_not_found"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Portfolio snapshot unavailable: %s", e)
        snapshot["portfolio"] = {"status": "unavailable"}

    # Risk
    try:
        from merid.pipeline.risk_manager import get_global_risk_manager
        rm = get_global_risk_manager()
        snapshot["risk"] = rm.summary()
    except ImportError:
        snapshot["risk"] = {"status": "unavailable", "reason": "module_not_found"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Risk snapshot unavailable: %s", e)
        snapshot["risk"] = {"status": "unavailable"}

    # Pipeline
    try:
        from merid.pipeline.mode_manager import get_mode_manager
        mm = get_mode_manager()
        snapshot["pipeline_modes"] = {
            v: cfg.mode.value for v, cfg in mm._venues.items()
        }
    except ImportError:
        snapshot["pipeline_modes"] = {"status": "unavailable", "reason": "module_not_found"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Pipeline modes unavailable: %s", e)
        snapshot["pipeline_modes"] = {"status": "unavailable"}

    # LLM governance
    try:
        store = get_llm_governance_store()
        snapshot["llm_governance"] = store.get_traces_summary(window_s=3600)
    except ImportError:
        snapshot["llm_governance"] = {"status": "unavailable", "reason": "module_not_found"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("LLM governance unavailable: %s", e)
        snapshot["llm_governance"] = {"status": "unavailable"}

    # Dev swarm
    try:
        from core.dev_swarm import DevSwarm
        ds = DevSwarm.get_instance()
        snapshot["dev_swarm"] = {
            "paused": ds.is_paused,
            "tasks_completed": len(ds._completed_tasks) if hasattr(ds, "_completed_tasks") else 0,
        }
    except ImportError:
        snapshot["dev_swarm"] = {"status": "unavailable", "reason": "module_not_found"}
    except (RuntimeError, AttributeError) as e:
        logger.debug("Dev swarm unavailable: %s", e)
        snapshot["dev_swarm"] = {"status": "unavailable"}

    return snapshot


_CONTEXT_PROMPTS: Dict[str, str] = {
    "operator": (
        "You are the MERID Operator Assistant. You help the operator understand "
        "portfolio status, risk metrics, pipeline health, and system observability. "
        "Answer concisely with data from the system snapshot when available."
    ),
    "dev": (
        "You are the MERID Dev Swarm Assistant. You help developers understand "
        "proposal status, code quality metrics, governance decisions, and agent "
        "performance. Reference the dev swarm context when available."
    ),
    "cognitive": (
        "You are the MERID Cognitive Assistant. You help analyze regime detection, "
        "hypothesis testing, reality debugging, and model health. Use cognitive "
        "layer data when available."
    ),
    "sports": (
        "You are the MERID Sports Betting Assistant. You help analyze live odds, "
        "consensus summaries, SLO metrics, and betting plan pipelines. Use sports "
        "and betting context when available."
    ),
}


def _build_answer(query: str, context: str, snapshot: Dict[str, Any]) -> str:
    """Build a structured answer from the query and system context.

    In production this would call an LLM with the system prompt + snapshot.
    For now we provide a structured context-aware response that surfaces
    the live data directly.
    """
    q_lower = query.lower()
    parts: List[str] = []

    # Portfolio questions
    if any(kw in q_lower for kw in ("portfolio", "equity", "balance", "cash", "position")):
        pf = snapshot.get("portfolio", {})
        if pf.get("status") != "unavailable":
            parts.append(
                f"Portfolio: ${pf.get('total_equity', 0):,.0f} total equity, "
                f"${pf.get('cash', 0):,.0f} cash, "
                f"{pf.get('positions_count', 0)} positions across "
                f"{', '.join(pf.get('domains', [])) or 'no'} domains."
            )
        else:
            parts.append("Portfolio data is currently unavailable.")

    # Risk questions
    if any(kw in q_lower for kw in ("risk", "halt", "circuit", "kill", "drawdown", "loss")):
        risk = snapshot.get("risk", {})
        if risk.get("status") != "unavailable":
            parts.append(f"Risk summary: {_summarize_dict(risk)}")
        else:
            parts.append("Risk data is currently unavailable.")

    # Pipeline / mode questions
    if any(kw in q_lower for kw in ("pipeline", "mode", "venue", "sim", "paper", "live")):
        modes = snapshot.get("pipeline_modes", {})
        if modes.get("status") != "unavailable":
            mode_str = ", ".join(f"{v}: {m}" for v, m in modes.items())
            parts.append(f"Pipeline venue modes: {mode_str}")
        else:
            parts.append("Pipeline mode data is currently unavailable.")

    # LLM / governance questions
    if any(kw in q_lower for kw in ("llm", "trace", "governance", "guardrail", "token")):
        llm = snapshot.get("llm_governance", {})
        if llm.get("status") != "unavailable":
            parts.append(
                f"LLM governance (1h window): {llm.get('traces_window', 0)} traces, "
                f"{llm.get('tokens_window', 0)} tokens, "
                f"{llm.get('error_rate', 0):.1%} error rate."
            )
        else:
            parts.append("LLM governance data is currently unavailable.")

    # Dev swarm questions
    if any(kw in q_lower for kw in ("dev", "swarm", "proposal", "agent")):
        ds = snapshot.get("dev_swarm", {})
        if ds.get("status") != "unavailable":
            parts.append(
                f"Dev swarm: {'paused' if ds.get('paused') else 'running'}, "
                f"{ds.get('tasks_completed', 0)} tasks completed."
            )
        else:
            parts.append("Dev swarm data is currently unavailable.")

    # Status / health catch-all
    if any(kw in q_lower for kw in ("status", "health", "overview", "summary")):
        available = [k for k, v in snapshot.items() if isinstance(v, dict) and v.get("status") != "unavailable" and k != "gathered_at"]
        parts.append(f"System modules reporting: {', '.join(available) or 'none'}.")

    if not parts:
        parts.append(
            f"I received your query about '{query[:80]}'. "
            "I can help with portfolio, risk, pipeline, LLM governance, and dev swarm questions. "
            "Try asking about system status, portfolio balance, risk metrics, or pipeline modes."
        )

    return " ".join(parts)


def _summarize_dict(d: Dict[str, Any], max_keys: int = 8) -> str:
    items = []
    for k, v in list(d.items())[:max_keys]:
        if isinstance(v, float):
            items.append(f"{k}={v:.2f}")
        elif isinstance(v, dict):
            items.append(f"{k}={{...}}")
        else:
            items.append(f"{k}={v}")
    return ", ".join(items)


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/query", response_model=AssistantResponse)
async def assistant_query(req: AssistantQuery) -> AssistantResponse:
    """Process an operator assistant query with system context."""
    start = time.time()
    trace_id = f"ast-{uuid.uuid4().hex[:12]}"
    context = req.context if req.context in _CONTEXT_PROMPTS else "operator"

    # Gather system snapshot
    snapshot = _gather_system_snapshot() if req.include_system_snapshot else {}

    # Build answer
    answer = _build_answer(req.query, context, snapshot)

    latency_ms = (time.time() - start) * 1000

    # Record trace for governance
    try:
        store = get_llm_governance_store()
        store.record_trace(LLMTrace(
            id=trace_id,
            role=LLMRole.OPS if context == "operator" else LLMRole(context) if context in [r.value for r in LLMRole] else LLMRole.RESEARCH,
            prompt_version="assistant-v1",
            model_name="context-engine",
            tokens_prompt=len(req.query.split()),
            tokens_completion=len(answer.split()),
            tools_used=["system_snapshot"] if req.include_system_snapshot else [],
            latency_ms=latency_ms,
            status="completed",
        ))
    except Exception as exc:
        logger.warning("Failed to record assistant trace: %s", exc)

    messages = [
        AssistantMessage(role="system", content=_CONTEXT_PROMPTS[context], timestamp=start),
        AssistantMessage(role="user", content=req.query, timestamp=start),
        AssistantMessage(role="assistant", content=answer, timestamp=time.time()),
    ]

    return AssistantResponse(
        trace_id=trace_id,
        answer=answer,
        context_domain=context,
        sources=list(snapshot.keys()) if snapshot else [],
        system_snapshot=snapshot if req.include_system_snapshot else None,
        messages=messages,
        latency_ms=round(latency_ms, 2),
    )


@router.get("/contexts")
async def list_contexts() -> Dict[str, Any]:
    """List available assistant context domains."""
    return {
        "contexts": [
            {"id": k, "description": v[:80] + "..."} for k, v in _CONTEXT_PROMPTS.items()
        ]
    }

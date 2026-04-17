"""Canonical OrderIntent schema — single source of truth for all execution paths.

Both the production router (merid/event_venues/kalshi/order_router.py) and the
quarantined NATS pipeline (merid_core/kalshi/execution_pipeline.py) must use this
definition, or provide a thin converter to it.

BUG-1 fix: eliminates the dual-schema divergence where the two paths used
incompatible field names (ticker vs market_ticker, price_cents vs price,
count vs qty, combined side vs split side/action, etc.).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


def _new_intent_id() -> str:
    return f"intent_{uuid.uuid4().hex}"


def _now_ts() -> float:
    return time.time()


@dataclass
class CanonicalOrderIntent:
    """Superset canonical intent shared by all execution paths.

    Fields marked ``# router`` are used by order_router.py.
    Fields marked ``# pipeline`` are used by the NATS execution_pipeline.
    Fields marked ``# both`` are used by both paths.
    """

    # ── Core (required, both paths) ────────────────────────────────────────
    ticker: str                              # both — Kalshi market ticker
    side: str                                # both — "yes" | "no"
    action: str                              # both — "buy" | "sell"
    price_cents: int                         # both — limit price 1–99
    count: int                               # both — number of contracts

    # ── Identity & idempotency (both) ──────────────────────────────────────
    intent_id: str = field(default_factory=_new_intent_id)
    client_tag: Optional[str] = None        # idempotency key; auto-set in router if None

    # ── Agent attribution (both) ───────────────────────────────────────────
    source: str = "manual"                   # agent name / strategy label (router)
    agent_id: Optional[str] = None          # pipeline agent_id
    session_id: Optional[str] = None        # pipeline session_id

    # ── Context / snapshot provenance (BUG-3 fix) ─────────────────────────
    snapshot_ts: float = field(default_factory=_now_ts)  # wall-clock when snapshot built
    data_version: str = "v1"                # schema / model version tag

    # ── Group / multi-leg linkage (BUG-4 fix) ─────────────────────────────
    order_group_id: Optional[str] = None    # Kalshi exchange order-group ID
    parent_intent_id: Optional[str] = None  # for legs of a multi-leg trade
    leg_index: Optional[int] = None         # 0 = YES leg, 1 = NO leg, etc.
    # Router parity (order_router.OrderIntent): FilterPipeline group + sentiment audit
    group_id: Optional[str] = None
    decision_trace_id: Optional[str] = None
    sentiment_asset: Optional[str] = None
    sentiment_timeframe: Optional[str] = None
    sentiment_driven: bool = False

    # ── Execution hints ────────────────────────────────────────────────────
    mode: Optional[object] = None           # TradingMode override (None = use gate default)
    order_type: str = "limit"               # "limit" | "market"
    time_in_force: str = "gtc"              # "gtc" | "ioc" | "fok"
    order_expiration_ts: Optional[int] = None  # GTT expiration (Unix epoch seconds)
    post_only: bool = False
    self_trade_prevention_type: Optional[str] = None

    # ── Risk / analytics ───────────────────────────────────────────────────
    edge_pct: Optional[float] = None        # net edge estimate (0–1)
    confidence: Optional[float] = None      # model confidence (0–1)
    rationale: Optional[str] = None         # ≤ 200 chars human-readable reason

    # ── Timestamp ──────────────────────────────────────────────────────────
    timestamp: float = field(default_factory=_now_ts)

    # ── Helpers ────────────────────────────────────────────────────────────

    def context_age_seconds(self) -> float:
        """Seconds elapsed since the market snapshot was captured."""
        return time.time() - self.snapshot_ts

    def ensure_client_tag(self) -> str:
        """Return existing client_tag or auto-generate and store one."""
        if not self.client_tag:
            self.client_tag = (
                f"{self.ticker}-{self.side}-{self.action}"
                f"-{int(self.timestamp * 1000)}-{uuid.uuid4().hex[:8]}"
            )
        return self.client_tag

    def to_pipeline_dict(self) -> dict:
        """Convert to the wire format expected by the NATS execution pipeline."""
        return {
            "session_id": self.session_id or "",
            "agent_id": self.agent_id or self.source,
            "market_ticker": self.ticker,
            "side": f"{self.action}_{self.side}",   # "buy_yes", "sell_no", etc.
            "qty": self.count,
            "price": self.price_cents / 100.0,
            "client_tag": self.ensure_client_tag(),
            "confidence": self.confidence,
            "rationale": self.rationale,
            "timestamp": int(self.timestamp),
            "intent_id": self.intent_id,
        }

    @classmethod
    def from_pipeline_dict(cls, d: dict) -> "CanonicalOrderIntent":
        """Parse the NATS pipeline wire format into a CanonicalOrderIntent."""
        raw_side = d.get("side", "buy_yes")   # "buy_yes", "sell_no", etc.
        parts = raw_side.split("_", 1)
        action = parts[0] if len(parts) == 2 else "buy"
        side = parts[1] if len(parts) == 2 else "yes"
        price_float = float(d.get("price", 0.5))
        price_cents = max(1, min(99, round(price_float * 100)))
        return cls(
            ticker=d.get("market_ticker", ""),
            side=side,
            action=action,
            price_cents=price_cents,
            count=int(d.get("qty", 1)),
            session_id=d.get("session_id"),
            agent_id=d.get("agent_id"),
            source=d.get("agent_id", "pipeline"),
            client_tag=d.get("client_tag"),
            confidence=d.get("confidence"),
            rationale=d.get("rationale"),
            timestamp=float(d.get("timestamp", time.time())),
            intent_id=d.get("intent_id", _new_intent_id()),
        )

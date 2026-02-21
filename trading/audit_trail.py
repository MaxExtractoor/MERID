"""Trade audit trail with deterministic causality chain.

Every paper trade must answer "why did this trade happen?" by linking:

    agent_decision → order_intent → order → fill

Each row includes pre/post portfolio snapshot hashes so the full
state transition is reproducible.

Storage: append-only JSON-lines file at ``data/trade_audit.jsonl``.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("trading.audit_trail")

_AUDIT_DIR = Path(__file__).resolve().parent.parent / "data"
_AUDIT_FILE = _AUDIT_DIR / "trade_audit.jsonl"


# ------------------------------------------------------------------ #
# Data types
# ------------------------------------------------------------------ #

@dataclass
class AuditEntry:
    """Single audit trail row."""

    # Identifiers — form the causality chain
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    intent_id: Optional[str] = None       # parent intent from agent
    order_id: Optional[str] = None        # paper engine order id
    fill_id: Optional[str] = None         # fill identifier (if applicable)
    agent_id: Optional[str] = None
    strategy_id: Optional[str] = None

    # Trade details
    venue: str = ""
    symbol: str = ""
    side: str = ""
    size: float = 0.0
    price: float = 0.0
    order_type: str = "market"
    market_type: str = "perp"

    # State snapshots
    pre_snapshot_hash: str = ""
    post_snapshot_hash: str = ""

    # Metadata
    timestamp: float = field(default_factory=time.time)
    event_type: str = "fill"              # intent | order | fill | cancel
    mode: str = "paper"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ------------------------------------------------------------------ #
# Append-only log
# ------------------------------------------------------------------ #

def _ensure_dir() -> None:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def append_entry(entry: AuditEntry) -> None:
    """Append a single audit entry to the log file."""
    try:
        _ensure_dir()
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")
    except Exception as exc:
        logger.warning("Failed to write audit entry: %s", exc)


def record_intent(
    *,
    agent_id: str,
    strategy_id: str = "",
    venue: str,
    symbol: str,
    side: str,
    size: float,
    price: float = 0.0,
    market_type: str = "perp",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Record an agent's trade intent. Returns the intent_id."""
    intent_id = str(uuid.uuid4())
    entry = AuditEntry(
        intent_id=intent_id,
        agent_id=agent_id,
        strategy_id=strategy_id,
        venue=venue,
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        market_type=market_type,
        event_type="intent",
        metadata=metadata or {},
    )
    append_entry(entry)
    logger.debug("Audit intent: %s %s %s %.2f %s", agent_id, side, symbol, size, intent_id[:8])
    return intent_id


def record_fill(
    *,
    intent_id: str,
    order_id: str,
    venue: str,
    symbol: str,
    side: str,
    size: float,
    price: float,
    agent_id: str = "",
    strategy_id: str = "",
    market_type: str = "perp",
    pre_snapshot_hash: str = "",
    post_snapshot_hash: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Record a fill event. Returns the fill event_id."""
    fill_id = str(uuid.uuid4())
    entry = AuditEntry(
        fill_id=fill_id,
        intent_id=intent_id,
        order_id=order_id,
        agent_id=agent_id,
        strategy_id=strategy_id,
        venue=venue,
        symbol=symbol,
        side=side,
        size=size,
        price=price,
        market_type=market_type,
        event_type="fill",
        pre_snapshot_hash=pre_snapshot_hash,
        post_snapshot_hash=post_snapshot_hash,
        metadata=metadata or {},
    )
    append_entry(entry)
    logger.debug("Audit fill: %s %s %.4f %s→%s", symbol, side, price, pre_snapshot_hash[:8], post_snapshot_hash[:8])
    return fill_id


def record_cancel(
    *,
    intent_id: str = "",
    order_id: str,
    venue: str,
    symbol: str,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Record an order cancellation."""
    entry = AuditEntry(
        intent_id=intent_id,
        order_id=order_id,
        venue=venue,
        symbol=symbol,
        event_type="cancel",
        metadata={"reason": reason, **(metadata or {})},
    )
    append_entry(entry)
    return entry.event_id


# ------------------------------------------------------------------ #
# Query helpers
# ------------------------------------------------------------------ #

def load_entries(
    *,
    limit: int = 500,
    event_type: Optional[str] = None,
    intent_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> List[AuditEntry]:
    """Load audit entries from the log file with optional filters."""
    if not _AUDIT_FILE.exists():
        return []

    entries: List[AuditEntry] = []
    try:
        with open(_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event_type and data.get("event_type") != event_type:
                    continue
                if intent_id and data.get("intent_id") != intent_id:
                    continue
                if agent_id and data.get("agent_id") != agent_id:
                    continue

                entries.append(AuditEntry(**{
                    k: v for k, v in data.items()
                    if k in AuditEntry.__dataclass_fields__
                }))
    except Exception as exc:
        logger.warning("Failed to read audit trail: %s", exc)

    return entries[-limit:]


def get_causality_chain(intent_id: str) -> List[Dict[str, Any]]:
    """Return all events linked to a given intent_id, ordered by time."""
    entries = load_entries(intent_id=intent_id, limit=100)
    entries.sort(key=lambda e: e.timestamp)
    return [e.to_dict() for e in entries]


def get_audit_summary() -> Dict[str, Any]:
    """Return a summary of the audit trail."""
    if not _AUDIT_FILE.exists():
        return {"entries": 0, "file": str(_AUDIT_FILE), "exists": False}

    counts: Dict[str, int] = {}
    total = 0
    try:
        with open(_AUDIT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                total += 1
                try:
                    data = json.loads(line.strip())
                    et = data.get("event_type", "unknown")
                    counts[et] = counts.get(et, 0) + 1
                except json.JSONDecodeError:
                    counts["malformed"] = counts.get("malformed", 0) + 1
    except Exception:
        pass

    return {
        "entries": total,
        "by_type": counts,
        "file": str(_AUDIT_FILE),
        "exists": True,
    }

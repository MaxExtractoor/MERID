"""Per-symbol trading status — combines feed staleness, venue health, and gate state.

Answers "Can we safely trade X right now?" for every tracked symbol.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.symbol_status")


def get_symbol_status() -> Dict[str, Any]:
    """Build per-symbol trading status matrix.

    Combines:
      1. Price feed staleness (per-symbol age vs threshold)
      2. Venue health (circuit breaker + adapter state)
      3. Execution gate state (global + per-symbol impact)

    Returns:
        dict with keys: symbols (list of row dicts), summary, gate_state, timestamp
    """
    now = time.time()
    rows: List[Dict[str, Any]] = []

    # ── 1. Collect price feed data ────────────────────────────────────
    feed_data: Dict[str, Dict[str, Any]] = {}
    try:
        from data.live_price_feed import get_live_price_feed
        from core.execution_gate import _get_threshold_for_symbol

        feed = get_live_price_feed()
        for symbol, price_data in feed.price_cache.items():
            ts = price_data.timestamp.timestamp() if hasattr(price_data.timestamp, 'timestamp') else float(price_data.timestamp)
            age = now - ts
            threshold, is_critical, group_name = _get_threshold_for_symbol(symbol)

            if age <= threshold * 0.8:
                feed_state = "fresh"
            elif age <= threshold:
                feed_state = "warning"
            else:
                feed_state = "stale"

            feed_data[symbol] = {
                "feed_state": feed_state,
                "age_seconds": round(age, 1),
                "threshold_seconds": threshold,
                "group": group_name,
                "critical": is_critical,
            }
    except Exception as exc:
        logger.debug("Price feed data unavailable: %s", exc)

    # ── 2. Collect venue health ───────────────────────────────────────
    venue_health: Dict[str, Dict[str, Any]] = {}
    try:
        from web.api.resilience import _get_venue_health
        for v in _get_venue_health():
            venue_health[v["venue"]] = {
                "venue_state": _map_venue_health(v["health"]),
                "venue_name": v["venue"],
                "enabled": v.get("enabled", True),
                "breaker_state": v.get("breaker_state", "closed"),
            }
    except Exception as exc:
        logger.debug("Venue health unavailable: %s", exc)

    # ── 3. Get global gate state ──────────────────────────────────────
    gate_state = "blocked"
    gate_reasons: List[str] = []
    gate_hint: Optional[str] = None
    try:
        from core.execution_gate import check_execution_gate
        gate = check_execution_gate()
        gate_state = gate.gate_state
        gate_reasons = [r.source for r in gate.reasons]
        if gate.reasons:
            gate_hint = gate.reasons[0].hint
    except Exception as exc:
        logger.debug("Execution gate unavailable: %s", exc)

    # ── 4. Build per-symbol rows ──────────────────────────────────────
    # Start with all symbols from price feed
    all_symbols = set(feed_data.keys())

    # Also include symbols from staleness config that may not have feed data
    try:
        from core.execution_gate import get_staleness_config
        for group in get_staleness_config():
            all_symbols.update(group.symbols)
    except Exception:
        pass

    for symbol in sorted(all_symbols):
        fd = feed_data.get(symbol)
        feed_state = fd["feed_state"] if fd else "no_data"
        age = fd["age_seconds"] if fd else None
        threshold = fd["threshold_seconds"] if fd else None
        group = fd["group"] if fd else "unknown"
        is_critical = fd["critical"] if fd else False

        # Determine venue for this symbol
        venue_name = _guess_venue(symbol)
        vh = venue_health.get(venue_name)
        venue_state = vh["venue_state"] if vh else "unknown"

        # Compute per-symbol gate impact
        symbol_gate, symbol_reasons, symbol_hint = _compute_symbol_gate(
            gate_state, gate_reasons, gate_hint,
            feed_state, is_critical, venue_state,
        )

        rows.append({
            "symbol": symbol,
            "feed_state": feed_state,
            "age_seconds": age,
            "threshold_seconds": threshold,
            "group": group,
            "critical": is_critical,
            "venue": venue_name,
            "venue_state": venue_state,
            "tradeable": symbol_gate,
            "reasons": symbol_reasons,
            "hint": symbol_hint,
        })

    # ── 5. Summary ────────────────────────────────────────────────────
    allowed_count = sum(1 for r in rows if r["tradeable"] == "allowed")
    limited_count = sum(1 for r in rows if r["tradeable"] == "reduce_only")
    blocked_count = sum(1 for r in rows if r["tradeable"] == "blocked")
    issue_count = sum(1 for r in rows if r["feed_state"] != "fresh" or r["venue_state"] != "up")

    return {
        "symbols": rows,
        "gate_state": gate_state,
        "summary": {
            "total": len(rows),
            "allowed": allowed_count,
            "reduce_only": limited_count,
            "blocked": blocked_count,
            "with_issues": issue_count,
        },
        "timestamp": now,
    }


def _map_venue_health(health: str) -> str:
    """Map venue health string to up/degraded/down."""
    if health in ("healthy",):
        return "up"
    elif health in ("degraded", "half_open"):
        return "degraded"
    elif health in ("unhealthy", "disabled"):
        return "down"
    return "unknown"


def _guess_venue(symbol: str) -> str:
    """Guess venue from symbol format. Simple heuristic."""
    if "-USD" in symbol and "/" not in symbol:
        return "alpaca"
    if "/USDT" in symbol:
        return "binance"
    if symbol.startswith("kalshi_") or "YES" in symbol or "NO" in symbol:
        return "kalshi"
    return "unknown"


def _compute_symbol_gate(
    global_gate: str,
    global_reasons: List[str],
    global_hint: Optional[str],
    feed_state: str,
    is_critical: bool,
    venue_state: str,
) -> tuple:
    """Compute per-symbol tradeable state.

    Returns: (tradeable, reasons, hint)
      tradeable: "allowed" | "reduce_only" | "blocked"
    """
    reasons = []
    hint = None

    # Global gate overrides
    if global_gate == "blocked":
        return "blocked", ["execution gate blocked"], global_hint

    # Venue down → blocked for this symbol regardless
    if venue_state == "down":
        return "blocked", ["venue down"], "Check venue connectivity in Venue Health Grid."

    # Feed stale on critical symbol → blocked
    if feed_state == "stale" and is_critical:
        reasons.append("critical feed stale")
        hint = "Check data source health for this symbol."
        return "blocked", reasons, hint

    # Global limited → reduce-only
    if global_gate == "limited":
        reasons.append("gate limited (reduce-only)")
        return "reduce_only", reasons, global_hint

    # Feed stale on non-critical → reduce-only
    if feed_state == "stale" and not is_critical:
        reasons.append("non-critical feed stale")
        return "reduce_only", reasons, "Monitor feed; non-critical staleness does not block closing positions."

    # Venue degraded → reduce-only
    if venue_state == "degraded":
        reasons.append("venue degraded")
        return "reduce_only", reasons, "Venue circuit breaker is half-open; reduce-only until stable."

    # Feed warning → allowed but flagged
    if feed_state == "warning":
        reasons.append("feed aging")

    # No data → reduce-only (conservative)
    if feed_state == "no_data":
        return "reduce_only", ["no price data"], "No price data received for this symbol yet."

    return "allowed", reasons, hint

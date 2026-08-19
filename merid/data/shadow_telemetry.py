"""Central, read-only shadow telemetry for the 15m Kalshi crypto stack.

This module writes JSON records to ``data/shadow/cfb_rti/`` when
``MERID_CFB_RTI_SHADOW_TELEMETRY`` is enabled. It must never raise into the
caller and must not modify any runtime state.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional


def _is_enabled() -> bool:
    return os.environ.get("MERID_CFB_RTI_SHADOW_TELEMETRY", "1").strip().lower() not in (
        "0",
        "false",
        "off",
    )


def _shadow_dir() -> Path:
    raw = os.environ.get("MERID_SHADOW_TELEMETRY_DIR", "data/shadow/cfb_rti")
    return Path(raw)


def _json_safe(value: Any) -> Any:
    """Recursively convert Decimal/dataclass values for JSON serialization."""
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "__dataclass_fields__"):
        return {k: _json_safe(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def write_shadow_record(record: Dict[str, Any]) -> None:
    """Write a single shadow record to disk. No-op if disabled."""
    if not _is_enabled():
        return
    try:
        record = dict(record)
        record.setdefault("schema_version", 1)
        record.setdefault("recorded_at_utc", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
        record = _json_safe(record)
        out_dir = _shadow_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        run_id = record.get("run_id", "unknown")
        ticker = record.get("ticker", record.get("market_ticker", "unknown"))
        record_type = record.get("record_type", "unknown")
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"{record_type}_{run_id}_{ticker}_{ts}.json"
        out_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    except Exception:
        # Telemetry must never break the trading path.
        pass


def persist_order_telemetry(intent: Any, result: Any) -> None:
    """Persist a shadow record for an order-routing attempt.

    Accepts any objects with the expected attributes (OrderIntent / OrderResult)
    to avoid circular imports between order_router and this module.
    """
    if not _is_enabled():
        return
    try:
        mode = str(getattr(result, "mode", "unknown"))
        status = str(getattr(result, "status", "unknown"))
        fill = getattr(result, "fill", None) or {}

        side = str(getattr(intent, "side", "") or "")
        action = str(getattr(intent, "action", "") or "")

        # Derive Kalshi side and V2 book side if possible.
        kalshi_side = ""
        v2_book_side: Optional[str] = None
        if side and action:
            try:
                from merid.event_venues.kalshi.binary_price_space import (
                    to_kalshi_side,
                    parse_kalshi_side,
                )

                if side.upper() in ("BUY_YES", "SELL_YES", "BUY_NO", "SELL_NO"):
                    outcome, act = parse_kalshi_side(side)
                    kalshi_side = side.upper()
                else:
                    kalshi_side = to_kalshi_side(side, action)

                if kalshi_side in ("BUY_YES", "SELL_NO"):
                    v2_book_side = "bid"
                elif kalshi_side in ("SELL_YES", "BUY_NO"):
                    v2_book_side = "ask"
            except Exception:
                pass

        record = {
            "record_type": "order",
            "run_id": getattr(intent, "run_id", None),
            "decision_id": getattr(intent, "decision_id", None),
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "ticker": getattr(intent, "ticker", None),
            "asset": getattr(intent, "asset", None),
            "side": side,
            "action": action,
            "kalshi_side": kalshi_side,
            "v2_book_side": v2_book_side,
            "price_cents": getattr(intent, "price_cents", None),
            "count": getattr(intent, "count", None),
            "count_fp": getattr(intent, "count_fp", None),
            "order_type": getattr(intent, "order_type", None),
            "time_in_force": getattr(intent, "time_in_force", None),
            "client_order_id": getattr(intent, "client_order_id", None),
            "order_status": status,
            "order_mode": mode,
            "has_execution": getattr(result, "has_execution", False),
            "request_completed": getattr(result, "request_completed", False),
            "success": getattr(result, "success", False),
            "order_id": getattr(result, "order_id", None),
            "latency_ms": getattr(result, "latency_ms", None),
            "reason": getattr(result, "reason", None),
            "error": getattr(result, "error", None),
            "fill_count": _json_safe(fill.get("count")) if isinstance(fill, dict) else None,
            "filled_count": _json_safe(fill.get("filled_count")) if isinstance(fill, dict) else None,
            "remaining_count": _json_safe(fill.get("remaining_count")) if isinstance(fill, dict) else None,
            "fill_price_cents": _json_safe(fill.get("price_cents")) if isinstance(fill, dict) else None,
            "confidence": getattr(intent, "confidence", None),
            "confidence_valid": getattr(intent, "confidence_valid", None),
            "confidence_source": getattr(intent, "confidence_source", None),
            "settlement_reference": getattr(intent, "settlement_reference", None),
            "git_revision": os.environ.get("MERID_GIT_REVISION"),
            "config_hash": os.environ.get("MERID_CONFIG_HASH"),
        }
        write_shadow_record(record)
    except Exception:
        pass

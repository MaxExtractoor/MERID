"""Shadow A/B logging for the tail-band experiment.

This module is read-only with respect to order routing and position state.  It
writes one ``tail_band_shadow.jsonl`` record per canonical-rejected decision
that falls into either the experimental favorite band (YES 85-95c, NO 88-95c)
or the excluded longshot band (<15c).  These records are evaluated after
settlement by ``scripts/tail_band_ab_evaluation.py``.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent

# Disable by setting MERID_TAIL_AB_SHADOW_LOGGING=0.
_ENABLED_DEFAULT = True


def _deep_json_safe(value: Any) -> Any:
    """Recursively convert Decimal/datetime in a dict/list structure."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _deep_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_json_safe(v) for v in value]
    return value


@dataclass
class TailBandShadowRecord:
    """A single counterfactual tail-band decision."""

    run_id: str
    cycle_id: int
    decision_id: str
    ticker: str
    asset: str
    side: str
    price_cents: int
    model_prob: float
    gross_edge_cents: float
    net_edge_cents: float
    fee_cents: float
    tail_band_state: str
    canonical_rejection_reason: str
    count: int = 1  # 1-contract sizing for the A/B
    timestamp_utc: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


def _enabled() -> bool:
    raw = os.environ.get("MERID_TAIL_AB_SHADOW_LOGGING", "1")
    return raw.strip().lower() not in ("0", "false", "off", "no")


def _shadow_log_path() -> Path:
    custom = os.environ.get("MERID_TAIL_AB_SHADOW_LOG_PATH")
    if custom:
        return Path(custom)
    return ROOT / "logs" / "tail_band_shadow.jsonl"


def write_tail_band_shadow_record(record: TailBandShadowRecord) -> None:
    """Append a tail-band shadow record to the durable log."""
    if not _enabled():
        return

    path = _shadow_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.debug("[TAIL-BAND-SHADOW] log directory setup failed: %s", exc)
        return

    ts = record.timestamp_utc or datetime.now(timezone.utc).isoformat()
    payload = {
        "schema_version": 1,
        "record_type": "tail_band_shadow",
        "timestamp_utc": ts,
        "run_id": record.run_id,
        "cycle_id": record.cycle_id,
        "decision_id": record.decision_id,
        "ticker": record.ticker,
        "asset": record.asset,
        "side": record.side,
        "price_cents": record.price_cents,
        "model_prob": record.model_prob,
        "gross_edge_cents": record.gross_edge_cents,
        "net_edge_cents": record.net_edge_cents,
        "fee_cents": record.fee_cents,
        "tail_band_state": record.tail_band_state,
        "canonical_rejection_reason": record.canonical_rejection_reason,
        "count": record.count,
        "extra": _deep_json_safe(record.extra or {}),
    }

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str, sort_keys=True) + "\n")
        logger.debug(
            "[TAIL-BAND-SHADOW] logged %s %s @ %dc as %s",
            record.asset, record.side, record.price_cents, record.tail_band_state,
        )
    except Exception as exc:
        logger.warning("[TAIL-BAND-SHADOW] failed to write record: %s", exc)

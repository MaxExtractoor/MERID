"""Settlement window health metrics and alert conditions for dashboards / hooks."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from merid.data.rti_reconciler import get_rti_reconciler
from merid.data.settlement_rti_buffer import get_settlement_buffer_registry
from utils.logger import get_logger

logger = get_logger("merid.data.settlement_observability")

_WARN_FILLED_BELOW = int(os.environ.get("MERID_RTI_SETTLEMENT_HEALTH_WARN_BELOW", "55"))
_CRITICAL_STE = float(os.environ.get("MERID_RTI_SETTLEMENT_HEALTH_CRITICAL_STE", "5.0"))


@dataclass
class SettlementWindowHealth:
    """One active RTI-settled market buffer snapshot."""

    market_ticker: str
    asset: str
    expiry_epoch: int
    window_start: int
    filled_count: int
    missing_seconds: List[int]
    seconds_to_expiry: float
    is_settlement_grade: bool
    avg_received: float
    in_settlement_minute: bool
    max_internal_ref_divergence: float
    alert_level: str  # "ok" | "warn" | "critical"
    alert_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_ticker": self.market_ticker,
            "asset": self.asset,
            "expiry_epoch": self.expiry_epoch,
            "window_start": self.window_start,
            "filled_count": self.filled_count,
            "filled_ratio": round(self.filled_count / 60.0, 4),
            "missing_seconds": self.missing_seconds,
            "seconds_to_expiry": round(self.seconds_to_expiry, 3),
            "is_settlement_grade": self.is_settlement_grade,
            "avg_received": self.avg_received,
            "in_settlement_minute": self.in_settlement_minute,
            "max_internal_ref_divergence": self.max_internal_ref_divergence,
            "alert_level": self.alert_level,
            "alert_reasons": list(self.alert_reasons),
        }


def collect_settlement_window_health(now_ts: Optional[float] = None) -> List[SettlementWindowHealth]:
    """Snapshot all registered buffers with alert classification."""
    now = now_ts if now_ts is not None else time.time()
    reg = get_settlement_buffer_registry()
    div = get_rti_reconciler().max_relative_divergence()
    out: List[SettlementWindowHealth] = []
    for ticker, buf in reg.snapshot_pairs():
        ste = float(buf.expiry_epoch) - now
        in_sm = buf.in_settlement_minute(now)
        reasons: List[str] = []
        level = "ok"
        if 0 < ste <= _CRITICAL_STE and buf.filled_count < _WARN_FILLED_BELOW:
            level = "critical"
            reasons.append(
                f"t_minus_{ste:.1f}s_filled_{buf.filled_count}_lt_{_WARN_FILLED_BELOW}"
            )
        elif in_sm and not buf.is_settlement_grade() and buf.filled_count < _WARN_FILLED_BELOW:
            level = "warn"
            reasons.append(f"settlement_minute_incomplete_{buf.filled_count}/60")
        if div > float(os.environ.get("MERID_RTI_HEALTH_DIVERGENCE_WARN", "0.01")):
            if level == "ok":
                level = "warn"
            reasons.append(f"internal_ref_divergence={div:.6f}")
        out.append(
            SettlementWindowHealth(
                market_ticker=ticker,
                asset=buf.asset,
                expiry_epoch=buf.expiry_epoch,
                window_start=buf.window_start,
                filled_count=buf.filled_count,
                missing_seconds=list(buf.missing_seconds)[:20],
                seconds_to_expiry=ste,
                is_settlement_grade=buf.is_settlement_grade(),
                avg_received=buf.avg_received,
                in_settlement_minute=in_sm,
                max_internal_ref_divergence=div,
                alert_level=level,
                alert_reasons=reasons,
            )
        )
    return sorted(out, key=lambda h: h.seconds_to_expiry)


def emit_settlement_health_alerts(health: List[SettlementWindowHealth]) -> None:
    """Log WARN/CRITICAL for operators; wire to Telegram/webhook if desired."""
    for h in health:
        if h.alert_level == "critical":
            logger.warning(
                "SETTLEMENT_HEALTH_CRITICAL %s %s %s",
                h.market_ticker,
                h.alert_reasons,
                h.to_dict(),
            )
        elif h.alert_level == "warn":
            logger.info(
                "SETTLEMENT_HEALTH_WARN %s %s",
                h.market_ticker,
                h.alert_reasons,
            )


def settlement_health_summary(now_ts: Optional[float] = None) -> Dict[str, Any]:
    rows = collect_settlement_window_health(now_ts)
    emit_settlement_health_alerts(rows)
    crit = sum(1 for r in rows if r.alert_level == "critical")
    warn = sum(1 for r in rows if r.alert_level == "warn")
    return {
        "buffers": [r.to_dict() for r in rows],
        "critical_count": crit,
        "warn_count": warn,
        "timestamp": now_ts or time.time(),
    }

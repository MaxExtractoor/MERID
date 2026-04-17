"""Multi-asset RTI risk snapshots for Kalshi crypto dashboards (CFB RTI path)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from merid.risk.crypto_rti_monitor import get_global_crypto_rti_monitor
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.btc15m_risk")

_layer: Optional["BTC15mRiskLayer"] = None


class BTC15mRiskLayer:
    """Reads ``CryptoRTIMonitor`` + settlement buffers for UI consumers."""

    def __init__(self) -> None:
        self._monitor = get_global_crypto_rti_monitor()

    def snapshot(self, asset: str) -> Dict[str, Any]:
        au = asset.strip().upper()
        try:
            rti = self._monitor.get_rti_metrics(au)
            if rti is None:
                return {}
            vol_spikes: list = []
            ratio = 1.0
            try:
                sma = rti.get("rti_60s_sma", 0.0)
                current = rti.get("rti_current", 0.0)
                vol = rti.get("rti_60s_vol", 0.0)
                if sma and current:
                    ratio = max(0.01, vol / max(sma, 1e-12) * 10_000)
            except Exception:
                ratio = 1.0
            return {
                "rti": rti.get("rti_current", 0.0),
                "sma_60s": rti.get("rti_60s_sma", 0.0),
                "vol_ratio": ratio,
                "vol_spike_events": vol_spikes,
                "rti_sma_deviation": rti.get("rti_current", 0.0) - rti.get("rti_60s_sma", 0.0),
                "recent_vol_spikes": 0,
                "max_recent_spike": 0.0,
            }
        except Exception as exc:
            logger.debug("snapshot failed for %s: %s", au, exc)
            return {}


def get_btc15m_risk_layer() -> BTC15mRiskLayer:
    global _layer
    if _layer is None:
        _layer = BTC15mRiskLayer()
    return _layer

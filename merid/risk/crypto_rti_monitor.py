"""
Crypto RTI Monitor

Monitors CFB RTI feeds and generates crypto-specific risk alerts.
"""
from __future__ import annotations
from time import time
from typing import Optional
from merid.data.rti_stream import RTIStream


class CryptoRTIMonitor:
    """Monitors RTI feeds for crypto assets and generates risk alerts."""

    def __init__(self, event_bus, portfolio_risk_agent):
        self.event_bus = event_bus
        self.portfolio_risk_agent = portfolio_risk_agent
        self.rti_stream = RTIStream()
        self.vol_baselines = {}  # asset -> baseline vol

    def set_vol_baseline(self, asset: str, baseline: float):
        """Set volatility baseline for asset."""
        self.vol_baselines[asset] = baseline

    def get_vol_baseline(self, asset: str) -> float:
        """Get volatility baseline for asset."""
        return self.vol_baselines.get(asset, 0.0)

    async def on_rti_tick(self, asset: str, price: float, ts: float | None = None):
        """Process RTI tick for any asset and update risk metrics."""
        eff_ts = ts if ts is not None else time()
        self.rti_stream.add_rti_tick(asset, price, eff_ts)

        metrics = self.rti_stream.get_current_metrics(asset)
        sma_60 = metrics["rti_60s_sma"]
        rv_60 = metrics["rti_60s_vol"]

        if hasattr(self.portfolio_risk_agent, "update_crypto_rti"):
            self.portfolio_risk_agent.update_crypto_rti(
                asset=asset,
                sma_60=sma_60,
                rv_60=rv_60,
            )

        baseline = self.get_vol_baseline(asset)
        if baseline <= 0:
            return

        vol_ratio = rv_60 / baseline

        if vol_ratio > 3.0:
            alert_level = "critical"
        elif vol_ratio > 2.0:
            alert_level = "warning"
        else:
            alert_level = None

        if alert_level:
            await self.event_bus.publish(
                "risk_alert",
                {
                    "event_type": "crypto_vol_spike",
                    "asset": asset,
                    "window_sec": 60,
                    "vol_ratio": round(vol_ratio, 2),
                    "status": alert_level,
                    "timestamp": eff_ts,
                    "reasoning": (
                        f"{asset} 60s RTI vol {rv_60:.4f} > "
                        f"{vol_ratio:.2f}x baseline {baseline:.4f}"
                    ),
                },
            )

    async def on_btc_rti_tick(self, price: float, ts: float | None = None):
        """Process BTC RTI tick."""
        await self.on_rti_tick("BTC", price, ts)

    async def on_eth_rti_tick(self, price: float, ts: float | None = None):
        """Process ETH RTI tick."""
        await self.on_rti_tick("ETH", price, ts)

    def get_rti_metrics(self, asset: str) -> dict[str, float]:
        """Get current RTI metrics for asset."""
        return self.rti_stream.get_current_metrics(asset)


_global_monitor: Optional[CryptoRTIMonitor] = None


def get_global_crypto_rti_monitor() -> "CryptoRTIMonitor":
    """Return the singleton CryptoRTIMonitor; raises if not yet registered."""
    global _global_monitor
    if _global_monitor is None:
        raise RuntimeError(
            "CryptoRTIMonitor not initialized — "
            "call set_global_crypto_rti_monitor() first"
        )
    return _global_monitor


def set_global_crypto_rti_monitor(monitor: "CryptoRTIMonitor") -> None:
    """Register the singleton CryptoRTIMonitor (called once from web/main.py)."""
    global _global_monitor
    _global_monitor = monitor

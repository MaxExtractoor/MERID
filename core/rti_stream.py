"""
RTI Stream Management

Handles real-time CFB RTI feeds for crypto assets.
Provides rolling averages and volatility calculations.
"""
from collections import deque
from time import time
from typing import Deque


class RTIWindow:
    """Rolling window for RTI price data."""

    def __init__(self, window_sec: int = 60):
        self.window_sec = window_sec
        self.samples: Deque[tuple[float, float]] = deque()  # (ts, price)

    def add(self, ts: float, price: float) -> None:
        """Add new RTI sample."""
        self.samples.append((ts, price))
        cutoff = ts - self.window_sec
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def sma(self) -> float:
        """Simple moving average over window."""
        if not self.samples:
            return 0.0
        return sum(p for _, p in self.samples) / len(self.samples)

    def realized_var(self) -> float:
        """Realized variance over 1s log returns."""
        if len(self.samples) < 2:
            return 0.0
        returns = []
        prev_p = self.samples[0][1]
        for _, p in list(self.samples)[1:]:
            if prev_p > 0 and p > 0:
                r = (p / prev_p) - 1.0
                returns.append(r)
            prev_p = p
        return sum(r * r for r in returns)

    def realized_vol(self) -> float:
        """Realized volatility (annualized, assuming 1s samples)."""
        var = self.realized_var()
        return var ** 0.5 if var > 0 else 0.0


class RTIStream:
    """Manages RTI feeds for multiple assets."""

    def __init__(self):
        self.windows: dict[str, RTIWindow] = {}
        self.sma_windows: dict[str, RTIWindow] = {}  # For per-minute averages

    def get_window(self, asset: str, window_sec: int = 60) -> RTIWindow:
        """Get RTI window for asset."""
        key = f"{asset}_{window_sec}"
        if key not in self.windows:
            self.windows[key] = RTIWindow(window_sec)
        return self.windows[key]

    def get_sma_window(self, asset: str) -> RTIWindow:
        """Get per-minute SMA window for asset."""
        if asset not in self.sma_windows:
            self.sma_windows[asset] = RTIWindow(3600)  # 1 hour of 60s averages
        return self.sma_windows[asset]

    def add_rti_tick(self, asset: str, price: float, ts: float | None = None):
        """Add RTI tick and update windows."""
        ts = ts or time()
        window = self.get_window(asset, 60)
        window.add(ts, price)

        # Update per-minute SMA if we've accumulated enough
        if len(window.samples) >= 60:  # Full minute
            sma = window.sma()
            sma_window = self.get_sma_window(asset)
            sma_window.add(ts, sma)

    def get_current_metrics(self, asset: str) -> dict[str, float]:
        """Get current RTI metrics for asset."""
        window = self.get_window(asset, 60)
        sma_window = self.get_sma_window(asset)

        return {
            "rti_current": window.samples[-1][1] if window.samples else 0.0,
            "rti_60s_sma": window.sma(),
            "rti_60s_vol": window.realized_vol(),
            "rti_sma_trend": sma_window.realized_vol() if len(sma_window.samples) > 1 else 0.0,
        }

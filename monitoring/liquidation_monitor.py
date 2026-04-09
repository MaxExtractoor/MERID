"""Liquidation and whale intelligence monitors for perp venues."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from trading.perp.base import WhaleSignal  # noqa: F401  (re-exported for importers)
from utils.logger import get_logger

logger = get_logger("monitoring.liquidation")


@dataclass
class LiquidationEvent:
    symbol: str
    venue: str
    side: str
    notional: float
    price: float
    timestamp_ms: float
    raw: Dict[str, Any]


class CoinGlassLiquidationMonitor:
    """Fetch liquidation heatmap snapshots via CoinGlass public API."""

    BASE_URL = "https://open-api.coinglass.com/api/pro/v1/futures/liquidation"

    def __init__(self, api_key: Optional[str] = None, *, timeout: float = 10.0) -> None:
        self.api_key = api_key or os.getenv("MERID_COINGLASS_API_KEY")
        self.use_mock = not bool(self.api_key)
        self._client = httpx.Client(timeout=timeout)

    def fetch_heatmap(self, symbols: Optional[List[str]] = None) -> List[LiquidationEvent]:
        if self.use_mock:
            return self._mock_events(symbols)
        params = {"timeType": "0"}  # 0 => 24h heatmap
        try:
            response = self._client.get(self.BASE_URL, params=params, headers={"coinglassSecret": self.api_key})
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or []
            return self._parse_events(data, symbols)
        except Exception as exc:
            logger.warning("CoinGlass heatmap fetch failed, falling back to mock: %s", exc)
            return self._mock_events(symbols)

    def _parse_events(self, entries: List[Dict[str, Any]], symbols: Optional[List[str]]) -> List[LiquidationEvent]:
        events: List[LiquidationEvent] = []
        sym_filter = set(s.upper() for s in symbols) if symbols else None
        for entry in entries:
            symbol = str(entry.get("symbol") or entry.get("pair") or "").upper()
            if not symbol:
                continue
            if sym_filter and symbol not in sym_filter:
                continue
            events.append(
                LiquidationEvent(
                    symbol=symbol,
                    venue=str(entry.get("exchangeName") or entry.get("exchange") or "unknown"),
                    side="long" if entry.get("side") == "sell" else "short",
                    notional=float(entry.get("amount") or entry.get("value") or 0.0),
                    price=float(entry.get("price") or 0.0),
                    timestamp_ms=float(entry.get("time") or entry.get("timestamp") or 0.0),
                    raw=entry,
                )
            )
        return events

    def _mock_events(self, symbols: Optional[List[str]]) -> List[LiquidationEvent]:
        """Return empty list when no API key - no fake data."""
        import time
        
        # Return empty list - no fake liquidation data
        # Real data requires CoinGlass API key
        logger.debug("No CoinGlass API key configured - liquidation data unavailable")
        return []


class WhaleIntelMonitor:
    """Aggregate whale signals from Nansen/Arkham/Drift guardian (mock scaffold)."""

    def __init__(self, *, nansen_key: Optional[str] = None, arkham_key: Optional[str] = None) -> None:
        self.nansen_key = nansen_key or os.getenv("MERID_NANSEN_API_KEY")
        self.arkham_key = arkham_key or os.getenv("MERID_ARKHAM_API_KEY")
        self.use_mock = not bool(self.nansen_key or self.arkham_key)
        self._client = httpx.Client(timeout=10.0)

    def fetch_signals(self, limit: int = 20) -> List[WhaleSignal]:
        if self.use_mock:
            return self._mock_signals(limit)
        signals: List[WhaleSignal] = []
        try:
            signals.extend(self._fetch_nansen(limit))
        except Exception as exc:
            logger.debug("Nansen whale feed unavailable: %s", exc)
        try:
            signals.extend(self._fetch_arkham(limit))
        except Exception as exc:
            logger.debug("Arkham whale feed unavailable: %s", exc)
        return signals or self._mock_signals(limit)

    def _fetch_nansen(self, limit: int) -> List[WhaleSignal]:
        # Placeholder: real API integration would go here.
        raise NotImplementedError

    def _fetch_arkham(self, limit: int) -> List[WhaleSignal]:
        raise NotImplementedError

    def _mock_signals(self, limit: int) -> List[WhaleSignal]:
        """Return empty list when no API keys - no fake data."""
        # Return empty list - no fake whale data
        # Real data requires Nansen or Arkham API keys
        logger.debug("No Nansen/Arkham API keys configured - whale data unavailable")
        return []

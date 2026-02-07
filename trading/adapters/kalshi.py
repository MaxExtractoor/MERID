"""Kalshi prediction market adapter — DEPRECATED.

Superseded by merid/prediction/ (strategy, risk, model) and
merid/event_venues/kalshi/ (resilient async client with circuit breaker).
Kept for backward compatibility only.
"""

from __future__ import annotations

from typing import Any, Dict, List

from trading.adapters.base import BalanceSnapshot, OrderResult, TradeRequest, TradingVenueAdapterBase
from trading.adapters.registry import register_adapter
from trading.integrations.kalshi_client import fetch_kalshi_balance, get_kalshi_client
from utils.logger import get_logger

logger = get_logger("trading.adapters.kalshi")


class KalshiPredictionAdapter(TradingVenueAdapterBase):
    """Read-only adapter that surfaces Kalshi balances/telemetry."""

    venue = "kalshi"
    supports_trading = False

    def __init__(self) -> None:
        super().__init__(use_mock=False)
        try:
            self._client = get_kalshi_client()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Kalshi client unavailable: %s", exc)
            self.use_mock = True
            self._client = None

    # ------------------------------------------------------------------ #
    # Live implementations
    # ------------------------------------------------------------------ #
    def _get_balances_live(self) -> List[BalanceSnapshot]:
        snapshot = fetch_kalshi_balance()
        amount = snapshot.get("balance") or 0
        try:
            usd_value = float(amount) / 100.0
        except (TypeError, ValueError):  # pragma: no cover
            usd_value = 0.0
        return [
            BalanceSnapshot(
                asset="USD",
                total=usd_value,
                available=usd_value,
                usd_value=usd_value,
                metadata=snapshot.get("raw", {}),
            )
        ]

    def _submit_order_live(self, request: TradeRequest) -> OrderResult:  # pragma: no cover - future work
        raise NotImplementedError("Kalshi trading not yet implemented")


register_adapter(KalshiPredictionAdapter())

"""Coinbase spot adapter powered by ccxt."""

from __future__ import annotations

import os
from typing import Any, Dict

from merid.coinbase_env import coinbase_api_key, coinbase_api_secret
from trading.adapters.base import OrderResult, TradeRequest, TradeSide, TradingVenueAdapterBase
from trading.adapters.registry import register_adapter
from utils.logger import get_logger

logger = get_logger("trading.adapters.coinbase")


class CoinbaseSpotAdapter(TradingVenueAdapterBase):
    venue = "coinbase"
    supports_trading = True

    def __init__(self, *, exchange_id: str | None = None) -> None:
        super().__init__(api_key=coinbase_api_key(), api_secret=coinbase_api_secret())
        self.exchange_id = exchange_id or os.getenv("MERID_COINBASE_EXCHANGE_ID", "coinbase")
        self._exchange = None
        if not self.use_mock:
            self._exchange = self._build_exchange()

    def _build_exchange(self):
        try:
            import ccxt  # type: ignore

            exchange_cls = getattr(ccxt, self.exchange_id)
            config: Dict[str, Any] = {
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
            }
            return exchange_cls(config)
        except Exception as exc:  # pragma: no cover - relies on ccxt availability
            logger.error("Failed to initialize Coinbase exchange: %s", exc)
            self.use_mock = True
            return None

    def _submit_order_live(self, request: TradeRequest) -> OrderResult:  # type: ignore[override]
        if not self._exchange:
            raise RuntimeError("Coinbase adapter unavailable - verify API credentials")

        symbol = request.symbol if "/" in request.symbol else f"{request.symbol}/USD"
        side = "buy" if request.side == TradeSide.BUY else "sell"
        order_type = request.order_type.value.lower()
        amount = float(request.quantity)
        price = request.price

        try:
            if order_type == "market":
                result = self._exchange.create_market_order(symbol, side, amount)
            else:
                if price is None:
                    raise RuntimeError("Limit orders require a price")
                result = self._exchange.create_limit_order(symbol, side, amount, price)
        except Exception as exc:
            self._last_error = str(exc)
            raise

        executed_price = float(result.get("average") or result.get("price") or price or 0.0)
        fills = result.get("fills") or []
        metadata = {
            "exchange_order_id": result.get("id"),
            "fills": fills,
            "raw": result,
        }

        return OrderResult(
            venue=self.venue,
            symbol=symbol,
            side=request.side,
            quantity=request.quantity,
            executed_price=executed_price,
            status=result.get("status", "executed"),
            venue_order_id=str(result.get("id")),
            metadata=metadata,
        )


# Spot trading via ccxt is off in Kalshi-only deployments — use Kalshi for PM execution;
# crypto spot *prices* still come from CryptoSpotService / Coinbase public APIs.
from merid.settings import settings as _merid_settings

if not _merid_settings.KALSHI_ONLY:
    register_adapter(CoinbaseSpotAdapter())

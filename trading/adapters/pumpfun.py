"""Pump.fun Solana memecoin adapter (simulation-first)."""

from __future__ import annotations

import os
from typing import Any, Dict

import httpx

from trading.adapters.base import OrderResult, TradeRequest, TradingVenueAdapterBase
from trading.adapters.registry import register_adapter
from utils.logger import get_logger

logger = get_logger("trading.adapters.pumpfun")


class PumpFunAdapter(TradingVenueAdapterBase):
    venue = "pumpfun"
    supports_trading = True

    def __init__(self, *, api_base: str | None = None) -> None:
        super().__init__(use_mock=False)
        self.api_base = api_base or os.getenv("PUMPFUN_API_BASE", "https://pump.fun/api")
        self.wallet_secret = os.getenv("PUMPFUN_WALLET_SECRET")
        self._http = httpx.Client(timeout=8.0)

    def _submit_order_live(self, request: TradeRequest) -> OrderResult:  # type: ignore[override]
        token_address = request.metadata.get("token_address") or request.metadata.get("mint")
        if not token_address:
            raise RuntimeError("Pump.fun adapter requires token_address in metadata")
        size_sol = float(request.metadata.get("size_sol") or request.quantity)
        token_info = self._fetch_last_trade(token_address)
        executed_price = token_info.get("price_sol", 0.0)
        status = "simulated"
        metadata: Dict[str, Any] = {
            "token_address": token_address,
            "last_price_sol": executed_price,
            "message": "Simulation only – wallet key not configured",
        }
        if self.wallet_secret:
            metadata["message"] = "Wallet configured but on-chain trading not yet implemented"
            status = "pending"

        return OrderResult(
            venue=self.venue,
            symbol=request.symbol or token_address,
            side=request.side,
            quantity=request.quantity,
            executed_price=executed_price,
            status=status,
            metadata=metadata,
        )

    def _fetch_last_trade(self, token_address: str) -> Dict[str, Any]:
        try:
            resp = self._http.get(f"{self.api_base}/trades/token/{token_address}", params={"limit": 1})
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and data.get("trades"):
                trade = data["trades"][0]
            elif isinstance(data, list) and data:
                trade = data[0]
            else:
                return {"price_sol": 0.0}
            price_sol = float(trade.get("priceSol") or trade.get("price") or 0.0)
            return {"price_sol": price_sol, "raw": trade}
        except Exception as exc:
            logger.warning("Pump.fun quote fetch failed: %s", exc)
            return {"price_sol": 0.0, "error": str(exc)}


register_adapter(PumpFunAdapter())

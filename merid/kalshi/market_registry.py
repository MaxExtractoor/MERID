"""
Kalshi Market Registry — Active market tracking for crypto agents.

Maintains current active markets for BTC/ETH/SOL 15m and daily contracts.
"""
from typing import Optional
from dataclasses import dataclass

from utils.logger import get_logger

logger = get_logger("merid.kalshi.market_registry")


@dataclass
class KalshiMarketInfo:
    """Market information for a Kalshi contract."""
    ticker: str
    strike: float
    seconds_to_expiry: int
    best_bid: float
    best_ask: float


class KalshiMarketRegistry:
    """Registry for tracking active Kalshi crypto markets."""

    def __init__(self, client):
        self.client = client
        self._btc_15m_ticker: Optional[str] = None
        self._btc_1h_ticker: Optional[str] = None
        self._eth_15m_ticker: Optional[str] = None
        self._sol_15m_ticker: Optional[str] = None
        self._xrp_15m_ticker: Optional[str] = None
        self._doge_15m_ticker: Optional[str] = None

    def refresh_crypto_15m(self, universe: dict[str, list[str]]) -> None:
        """Refresh active crypto 15m/hourly tickers from universe subsets."""
        btc_15m = universe.get("BTC_15M") or []
        btc_1h = universe.get("BTC_1H") or []
        eth = universe.get("ETH_15M") or []
        sol = universe.get("SOL_15M") or []
        xrp = universe.get("XRP_15M") or []
        doge = universe.get("DOGE_15M") or []

        self._btc_15m_ticker = btc_15m[0] if btc_15m else None
        self._btc_1h_ticker = btc_1h[0] if btc_1h else None
        self._eth_15m_ticker = eth[0] if eth else None
        self._sol_15m_ticker = sol[0] if sol else None
        self._xrp_15m_ticker = xrp[0] if xrp else None
        self._doge_15m_ticker = doge[0] if doge else None

        logger.debug(f"Refreshed crypto 15m/hourly tickers: BTC_15M={self._btc_15m_ticker}, BTC_1H={self._btc_1h_ticker}, ETH_15M={self._eth_15m_ticker}, SOL_15M={self._sol_15m_ticker}, XRP_15M={self._xrp_15m_ticker}, DOGE_15M={self._doge_15m_ticker}")

    def _get_market_info(self, ticker: str) -> Optional[KalshiMarketInfo]:
        """Fetch market info from Kalshi API."""
        if not ticker:
            return None

        try:
            m = self.client.get_market(ticker=ticker)

            # Handle both object-like and dict-like responses
            if hasattr(m, "ticker"):
                ticker_val = m.ticker
                strike_val = getattr(m, "strike_price", 0.0)
                seconds_to_expiry_val = getattr(m, "seconds_to_expiry", 0)
                ob = getattr(m, "orderbook", None)
                if isinstance(ob, dict):
                    best_bid_val = ob.get("best_bid", 0.0)
                    best_ask_val = ob.get("best_ask", 0.0)
                else:
                    best_bid_val = getattr(ob, "best_bid", 0.0) if ob is not None else 0.0
                    best_ask_val = getattr(ob, "best_ask", 0.0) if ob is not None else 0.0
            else:
                ticker_val = m.get("ticker")
                strike_val = m.get("strike_price", 0.0)
                seconds_to_expiry_val = m.get("seconds_to_expiry", 0)
                ob = m.get("orderbook") or {}
                best_bid_val = ob.get("best_bid", 0.0)
                best_ask_val = ob.get("best_ask", 0.0)

            return KalshiMarketInfo(
                ticker=ticker_val,
                strike=strike_val,
                seconds_to_expiry=seconds_to_expiry_val,
                best_bid=best_bid_val,
                best_ask=best_ask_val,
            )
        except Exception as exc:
            logger.warning(f"Failed to fetch market info for {ticker}: {exc}")
            return None

    def get_active_btc_15m(self) -> Optional[KalshiMarketInfo]:
        """Get current active BTC 15m market."""
        return self._get_market_info(self._btc_15m_ticker)

    def get_active_btc_1h(self) -> Optional[KalshiMarketInfo]:
        """Get current active BTC 1h market."""
        return self._get_market_info(self._btc_1h_ticker)

    def get_active_eth_15m(self) -> Optional[KalshiMarketInfo]:
        """Get current active ETH 15m market."""
        return self._get_market_info(self._eth_15m_ticker)

    def get_active_sol_15m(self) -> Optional[KalshiMarketInfo]:
        """Get current active SOL 15m market."""
        return self._get_market_info(self._sol_15m_ticker)

    def get_active_xrp_15m(self) -> Optional[KalshiMarketInfo]:
        """Get current active XRP 15m market."""
        return self._get_market_info(self._xrp_15m_ticker)

    def get_active_doge_15m(self) -> Optional[KalshiMarketInfo]:
        """Get current active DOGE 15m market."""
        return self._get_market_info(self._doge_15m_ticker)

    def refresh(self) -> None:
        """Refresh crypto 15m tickers from latest universe."""
        from config.kalshi_universe_loader import fetch_kalshi_active_markets
        universe = fetch_kalshi_active_markets(self.client)
        self.refresh_crypto_15m(universe)

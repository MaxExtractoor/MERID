"""Per-asset spot/Kalshi basis thresholds and staleness config.

All financial thresholds are tuned to typical Kalshi bid-ask spread widths
plus CFB Real-Time Index publishing latency (~1s), which means some basis
is structurally expected and should not trigger alerts.

Env vars (all optional, have safe defaults):
    KALSHI_BASIS_SPOT_STALE_MS    — ms before Coinbase spot is "stale" (default 5000)
    KALSHI_BASIS_SPOT_MISSING_MS  — ms before Coinbase spot is "missing" (default 30000)
    KALSHI_BASIS_BOOK_STALE_MS    — ms before Kalshi book is "stale" (default 10000)
    KALSHI_BASIS_BOOK_MISSING_MS  — ms before Kalshi book is "missing" (default 60000)
    KALSHI_BASIS_ROLLING_WINDOW_SECS — rolling stats window in seconds (default 3600)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class AssetBasisThresholds:
    """Thresholds defining when the spot/Kalshi basis is 'offside' for one asset.

    Both abs_threshold_usd AND pct_threshold are checked independently.
    Either breach alone triggers the breach counter.

    Tuning notes:
    - BTC: Kalshi spreads ~5-20¢ equivalent, index publishes 1/s, 60s rolling avg.
      $50 allows ~6 full Kalshi spread-widths before flagging.
    - SOL: ~$0.30 is roughly 1 full Kalshi bid-ask spread on a $150 asset.
    - XRP/DOGE: tiny absolute values; pct_threshold dominates.
    """
    abs_threshold_usd: float      # max |basis_mid| in USD before breach
    pct_threshold: float          # max |basis_mid / spot| before breach (e.g. 0.0005 = 0.05%)
    breach_count_threshold: int   # consecutive tick breaches before → OFFSIDE state


# Per-asset thresholds — tuned to each asset's typical spread width and index lag
ASSET_THRESHOLDS: Dict[str, AssetBasisThresholds] = {
    "BTC":  AssetBasisThresholds(abs_threshold_usd=50.0,   pct_threshold=0.0005, breach_count_threshold=5),
    "ETH":  AssetBasisThresholds(abs_threshold_usd=5.0,    pct_threshold=0.0005, breach_count_threshold=5),
    "SOL":  AssetBasisThresholds(abs_threshold_usd=0.30,   pct_threshold=0.0020, breach_count_threshold=5),
    "XRP":  AssetBasisThresholds(abs_threshold_usd=0.005,  pct_threshold=0.0025, breach_count_threshold=5),
    "DOGE": AssetBasisThresholds(abs_threshold_usd=0.002,  pct_threshold=0.0025, breach_count_threshold=5),
}

# ── Staleness TTL (env-configurable) ─────────────────────────────────────
# Coinbase WS ticker fires ~every 1s in liquid markets; REST polling is 5s.
# Allow 5s before "stale" to absorb polling lag without false positives.
SPOT_STALE_MS:   float = float(os.getenv("KALSHI_BASIS_SPOT_STALE_MS",   "5000"))
SPOT_MISSING_MS: float = float(os.getenv("KALSHI_BASIS_SPOT_MISSING_MS", "30000"))

# Kalshi book can legitimately go quiet for 5-10s in illiquid markets.
# 10s stale threshold avoids false positives during quiet periods.
BOOK_STALE_MS:   float = float(os.getenv("KALSHI_BASIS_BOOK_STALE_MS",   "10000"))
BOOK_MISSING_MS: float = float(os.getenv("KALSHI_BASIS_BOOK_MISSING_MS", "60000"))

# Rolling stats window — default 1 hour (3600 samples at 1s tick)
ROLLING_WINDOW_SECONDS: int = int(os.getenv("KALSHI_BASIS_ROLLING_WINDOW_SECS", "3600"))

# Spot feed source configuration
# "coinbase" - uses Coinbase LivePriceFeed (BTC/USD, ETH/USD, etc.)
# "kraken" - uses Kraken public API ticker (XBTUSD, ETHUSD, etc.)
# "coingecko" - uses CoinGecko API (bitcoin, ethereum, etc.)
SPOT_FEED_SOURCE: str = os.getenv("MERID_SPOT_FEED_SOURCE", "coinbase")

# Coinbase price-cache symbol map (must match LivePriceFeed.price_cache keys)
# LivePriceFeed stores under "BTC/USD" format (CCXT-style, USD-denominated)
COINBASE_SPOT_SYMBOLS: Dict[str, str] = {
    "BTC":  "BTC/USD",
    "ETH":  "ETH/USD",
    "SOL":  "SOL/USD",
    "XRP":  "XRP/USD",
    "DOGE": "DOGE/USD",
}

# Kraken ticker symbol map (must match Kraken public API)
# Kraken uses XBT for Bitcoin, not BTC
KRAKEN_SPOT_SYMBOLS: Dict[str, str] = {
    "BTC":  "XBTUSD",
    "ETH":  "ETHUSD",
    "SOL":  "SOLUSD",
    "XRP":  "XRPUSD",
    "DOGE": "DOGEUSD",
}

# CoinGecko ID map (must match CoinGecko API)
COINGECKO_IDS: Dict[str, str] = {
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "SOL":  "solana",
    "XRP":  "ripple",
    "DOGE": "dogecoin",
}

# Kalshi ticker prefixes used for fallback asset inference when `underlying` field is None
KALSHI_TICKER_PREFIXES: Dict[str, str] = {
    "BTC":  "KXBTC",
    "ETH":  "KXETH",
    "SOL":  "KXSOL",
    "XRP":  "KXXRP",
    "DOGE": "KXDOGE",
}

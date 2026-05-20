"""merid.agents.kalshi_crypto — Crypto price-range Kalshi strategy agents.

Handles BTC/ETH/SOL/XRP/DOGE range, high/low, and price-bracket contracts
settled on CFB RTI indexes.  All agents use the shared Kalshi client and
risk primitives from ``merid.kalshi``.

Agents:
  - Btc15mAgent  — BTC 15-minute range contracts
  - Eth15mAgent  — ETH 15-minute range contracts
  - Sol15mAgent  — SOL 15-minute range contracts
  - Xrp15mAgent  — XRP 15-minute range contracts
  - Doge15mAgent — DOGE 15-minute range contracts

Domain-specific features:
  - RTI (Real-Time Index) feeds for crypto price tracking
  - Volatility regime detection for position sizing
  - Crypto-specific sentiment signals

NOTE: Btc1hAgent (hourly) archived 2026-01-15 - focus on 15m timeframe only.
"""

import logging as _logging

_logger = _logging.getLogger("merid.agents.kalshi_crypto")

# Agent imports are guarded because several depend on modules that are
# not yet implemented (merid.kalshi.rti, merid.portfolio.risk, etc.).
# A missing dependency must not crash the rest of the import graph.

CRYPTO_AGENTS: dict = {}

try:
    from merid.agents.btc_15m_agent import Btc15mAgent
    CRYPTO_AGENTS["btc_15m"] = Btc15mAgent
except Exception as _e:
    _logger.debug("kalshi_crypto: Btc15mAgent unavailable: %s", _e)
    Btc15mAgent = None  # type: ignore[assignment,misc]

# Btc1hAgent archived 2026-01-15 - focus on 15m timeframe only

try:
    from merid.agents.eth_15m_agent import Eth15mAgent
    CRYPTO_AGENTS["eth_15m"] = Eth15mAgent
except Exception as _e:
    _logger.debug("kalshi_crypto: Eth15mAgent unavailable: %s", _e)
    Eth15mAgent = None  # type: ignore[assignment,misc]

try:
    from merid.agents.sol_15m_agent import Sol15mAgent
    CRYPTO_AGENTS["sol_15m"] = Sol15mAgent
except Exception as _e:
    _logger.debug("kalshi_crypto: Sol15mAgent unavailable: %s", _e)
    Sol15mAgent = None  # type: ignore[assignment,misc]

try:
    from merid.agents.xrp_15m_agent import Xrp15mAgent
    CRYPTO_AGENTS["xrp_15m"] = Xrp15mAgent
except Exception as _e:
    _logger.debug("kalshi_crypto: Xrp15mAgent unavailable: %s", _e)
    Xrp15mAgent = None  # type: ignore[assignment,misc]

try:
    from merid.agents.doge_15m_agent import Doge15mAgent
    CRYPTO_AGENTS["doge_15m"] = Doge15mAgent
except Exception as _e:
    _logger.debug("kalshi_crypto: Doge15mAgent unavailable: %s", _e)
    Doge15mAgent = None  # type: ignore[assignment,misc]

# Shared crypto helpers
try:
    from merid.kalshi import (
        is_crypto_market,
        KALSHI_CRYPTO_TICKERS,
        KALSHI_CRYPTO_CATEGORIES,
        KalshiMarketRegistry,
        KalshiCryptoOpinion,
        build_kalshi_crypto_intent,
        ExecutionTelemetryTracker,
    )
except Exception as _e:
    _logger.debug("kalshi_crypto: shared helpers unavailable: %s", _e)

__all__ = [
    "Btc15mAgent",
    "Eth15mAgent",
    "Sol15mAgent",
    "Xrp15mAgent",
    "Doge15mAgent",
    "CRYPTO_AGENTS",
]

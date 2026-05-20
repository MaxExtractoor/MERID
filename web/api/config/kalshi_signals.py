# web/api/config/kalshi_signals.py
"""Crypto agent configuration for signals API."""

# PROFILE-GUARD: This list includes legacy regime agents not used in kalshi_crypto_15m_v2
# For kalshi_crypto_15m_v2, only the 5 core agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M) are used
import os

_profile = os.getenv("MERID_PROFILE", "").lower()
if _profile == "kalshi_crypto_15m_v2":
    # Override for 15m profile - only core agents
    CRYPTO_AGENT_IDS = ["btc_15m_regime", "eth_15m_regime", "sol_15m_regime", "xrp_15m_regime", "doge_15m_regime"]
else:
    CRYPTO_AGENT_IDS = [
        "btc_15m_regime",
        "eth_15m_regime", 
        "sol_15m_regime",
        "xrp_15m_regime",
        "doge_15m_regime",
        "btc_1h_regime",
    ]

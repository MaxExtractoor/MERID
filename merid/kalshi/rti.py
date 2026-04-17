"""Shim: re-export CryptoRTIMonitor under the merid.kalshi.rti path.

Per-asset agents (eth_15m_agent, sol_15m_agent, …) import from this
module. The canonical implementation lives in merid.risk.crypto_rti_monitor.
"""
from merid.risk.crypto_rti_monitor import CryptoRTIMonitor

__all__ = ["CryptoRTIMonitor"]

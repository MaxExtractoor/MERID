"""
MERID Trading Lanes

Each lane is a self-contained orchestration loop for a specific
asset/timeframe/venue combination.

Available lanes:
- Crypto15MLane: Kalshi 15m crypto trading (BTC/ETH/SOL/XRP/DOGE)

NOTE: BTC15MLane was moved to legacy/lanes/ on 2026-05-15.
Use Crypto15MLane via registry.get_lane() for all 15m crypto assets.
"""

from merid.lanes.crypto15m_lane import Crypto15MLane, Crypto15MLaneConfig

__all__ = ["Crypto15MLane", "Crypto15MLaneConfig"]

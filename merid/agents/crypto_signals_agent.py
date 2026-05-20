"""CryptoSignalsAgent - Detects spreads, basis, funding, and structural signals.

LEAN 15m KALSHI STACK (2026-05-13): Kept in production for short-horizon trading.
Provides CEX spreads, funding, basis signals which are useful for 15m crypto trading.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput, CanonicalAgent

from utils.logger import get_logger

logger = get_logger("merid.agents.crypto_signals")


class CryptoSignalsAgent(CanonicalAgent):
    """Detects spreads, basis, funding, and structural signals across CEXs.

    Output: Structured signals with instrument, venue, signal type, and magnitude.
    """

    def __init__(
        self,
        agent_id: str = "crypto-signals-01",
        venues: Optional[List[str]] = None,
    ):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self.venues = venues or ["binance", "coinbase", "kraken", "okx"]
        self._watched_pairs: List[str] = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]
        self._signals: List[Dict[str, Any]] = []

    def watch_pair(self, pair: str) -> None:
        if pair not in self._watched_pairs:
            self._watched_pairs.append(pair)

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Scan for cross-exchange spreads and structural signals.

        In production: fetches order books from all venues, computes
        spreads, funding rates, basis, and flags anomalies.
        """
        signals = await self._detect_signals(context)
        self._signals.extend(signals)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="crypto_signals",
            payload={
                "signals": signals,
                "venues": self.venues,
                "watched_pairs": self._watched_pairs,
            },
            confidence=0.5,
        )

    async def _detect_signals(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Override point for actual signal detection."""
        return []

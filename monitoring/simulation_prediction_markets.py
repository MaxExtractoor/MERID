"""
Simulation Prediction Market Aggregator

IMPORTANT: This aggregator is for PAPER TRADING and SIMULATION ONLY.
It includes non-US compliant platforms (Polymarket, Augur) for research
and backtesting purposes. DO NOT use for real trading.

For production/live trading, use the main PredictionMarketAggregator
which only includes US-compliant sources (Kalshi).

US Compliance Policy:
- Kalshi = Primary production source (CFTC-regulated)
- Polymarket, Augur = Simulation/paper trading only
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Dict, List, Optional, Any
from collections import deque
from dataclasses import dataclass, field

from utils.logger import get_logger
from monitoring.prediction_markets import (
    PredictionPlatform,
    PredictionMarket,
    MarketCategory,
    ResolutionStatus,
    PredictionMarketConnector,
    KalshiConnector,
    PolymarketConnector,
    AugurConnector,
    OddsDriftSignal,
    CrossPlatformArbitrage,
    ResolutionDecayMetrics,
    _safe_float,
)

logger = get_logger("monitoring.simulation_prediction_markets")


# Global singleton
_simulation_aggregator: Optional["SimulationPredictionAggregator"] = None


def get_simulation_aggregator() -> "SimulationPredictionAggregator":
    """Get or create the simulation prediction aggregator singleton."""
    global _simulation_aggregator
    if _simulation_aggregator is None:
        _simulation_aggregator = SimulationPredictionAggregator()
    return _simulation_aggregator


class SimulationPredictionAggregator:
    """
    Simulation-only prediction market aggregator.

    IMPORTANT: This aggregator includes non-US compliant platforms
    and should ONLY be used for:
    - Paper trading
    - Backtesting
    - Research
    - Simulation

    For production trading, use PredictionMarketAggregator (Kalshi only).

    Platforms included:
    - Kalshi (US-compliant, for comparison)
    - Polymarket (SIMULATION ONLY - US restricted)
    - Augur (SIMULATION ONLY)
    """

    def __init__(self, include_kalshi: bool = True):
        """
        Initialize simulation aggregator.

        Args:
            include_kalshi: Include Kalshi data for cross-platform comparison
        """
        self.is_simulation = True  # Always true - this is simulation only

        # Include all platforms for simulation
        self.connectors: Dict[PredictionPlatform, PredictionMarketConnector] = {}

        # Optionally include Kalshi for cross-platform comparison
        if include_kalshi:
            self.connectors[PredictionPlatform.KALSHI] = KalshiConnector()

        # Non-US platforms - SIMULATION ONLY
        self.connectors[PredictionPlatform.POLYMARKET] = PolymarketConnector()
        self.connectors[PredictionPlatform.AUGUR] = AugurConnector()

        self._all_markets: Dict[str, PredictionMarket] = {}
        self._drift_signals: deque = deque(maxlen=500)
        self._arbitrage_opps: deque = deque(maxlen=100)
        self._decay_metrics: Dict[str, ResolutionDecayMetrics] = {}

        self._running = False
        self._update_task: Optional[asyncio.Task] = None

        logger.warning(
            "SimulationPredictionAggregator initialized - "
            "FOR PAPER TRADING AND SIMULATION ONLY - "
            "Non-US compliant platforms enabled"
        )

    async def start(self) -> None:
        """Start simulation aggregation."""
        if self._running:
            return

        self._running = True
        self._update_task = asyncio.create_task(self._update_loop())
        logger.info("SimulationPredictionAggregator started (SIMULATION MODE)")

    async def stop(self) -> None:
        """Stop aggregation."""
        self._running = False
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        logger.info("SimulationPredictionAggregator stopped")

    async def _update_loop(self) -> None:
        """Main update loop."""
        while self._running:
            try:
                await self._fetch_all_markets()
                await asyncio.sleep(0)
                self._detect_odds_drift()
                await asyncio.sleep(0)
                self._find_arbitrage_opportunities()
                await asyncio.sleep(60)  # Update every minute
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Simulation prediction market update error: {e}")
                await asyncio.sleep(30)

    async def _fetch_all_markets(self) -> None:
        """Fetch markets from all simulation connectors."""
        logger.info(f"[SIMULATION] Fetching from {len(self.connectors)} platforms...")

        for platform, connector in self.connectors.items():
            try:
                markets = await connector.fetch_markets()
                for market in markets:
                    self._all_markets[market.market_id] = market

                logger.info(f"[SIMULATION] {platform.value}: {len(markets)} markets")
            except Exception as e:
                logger.error(f"[SIMULATION] Failed to fetch from {platform.value}: {e}")

    def _detect_odds_drift(self) -> None:
        """Detect significant odds movements across platforms."""
        for market_id, market in self._all_markets.items():
            connector = self.connectors.get(market.platform)
            if not connector:
                continue

            history = connector.get_price_history(market_id, window_seconds=3600)
            if len(history) < 2:
                continue

            old_price = _safe_float(history[0]["price"], 0.0)
            new_price = _safe_float(history[-1]["price"], 0.0)

            if old_price == 0:
                continue

            drift_pct = ((new_price - old_price) / old_price) * 100

            if abs(drift_pct) >= 3.0:
                signal = OddsDriftSignal(
                    signal_id=f"sim_drift_{uuid.uuid4().hex[:8]}",
                    market_id=market_id,
                    platform=market.platform,
                    question=market.question,
                    old_probability=old_price,
                    new_probability=new_price,
                    drift_pct=drift_pct,
                    drift_direction="up" if drift_pct > 0 else "down",
                    time_window_seconds=3600,
                    volume_in_window=_safe_float(market.volume_24h) / 24,
                )
                self._drift_signals.append(signal)

    def _find_arbitrage_opportunities(self) -> None:
        """
        Find cross-platform arbitrage opportunities.

        Note: These are for SIMULATION purposes only.
        Real arbitrage between Kalshi and Polymarket is not possible
        for US residents due to regulatory restrictions.
        """
        question_groups: Dict[str, List[PredictionMarket]] = {}

        for market in self._all_markets.values():
            key = self._normalize_question(market.question)
            if key not in question_groups:
                question_groups[key] = []
            question_groups[key].append(market)

        for key, markets in question_groups.items():
            if len(markets) < 2:
                continue

            for i, market_a in enumerate(markets):
                for market_b in markets[i + 1:]:
                    if market_a.platform == market_b.platform:
                        continue

                    price_a = _safe_float(market_a.yes_price)
                    price_b = _safe_float(market_b.yes_price)
                    spread = abs(price_a - price_b)
                    spread_pct = spread * 100

                    if spread_pct >= 2.0:
                        arb = {
                            "arb_id": f"sim_arb_{uuid.uuid4().hex[:8]}",
                            "question": market_a.question,
                            "platform_a": market_a.platform.value,
                            "platform_b": market_b.platform.value,
                            "price_a": price_a,
                            "price_b": price_b,
                            "spread_pct": spread_pct,
                            "simulation_only": True,
                            "warning": "Cross-platform arb not available for US residents",
                            "detected_at": time.time(),
                        }
                        self._arbitrage_opps.append(arb)
                        logger.info(
                            f"[SIMULATION] Arb opportunity: {spread_pct:.1f}% spread "
                            f"between {market_a.platform.value} and {market_b.platform.value}"
                        )

    def _normalize_question(self, question: str) -> str:
        """Normalize question for cross-platform matching."""
        import re
        q = question.lower()
        q = re.sub(r'[^\w\s]', '', q)
        q = ' '.join(q.split())
        return q

    def get_all_markets(self) -> List[Dict[str, Any]]:
        """Get all simulation markets with metadata."""
        return [
            {
                "market_id": m.market_id,
                "platform": m.platform.value,
                "question": m.question,
                "category": m.category.value,
                "yes_price": m.yes_price,
                "no_price": m.no_price,
                "volume_24h": m.volume_24h,
                "liquidity": m.liquidity,
                "simulation_only": True,
                "us_compliant": m.platform == PredictionPlatform.KALSHI,
            }
            for m in self._all_markets.values()
        ]

    def get_drift_signals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent drift signals."""
        signals = list(self._drift_signals)[-limit:]
        return [
            {
                "signal_id": s.signal_id,
                "market_id": s.market_id,
                "platform": s.platform.value,
                "question": s.question[:100],
                "old_probability": s.old_probability,
                "new_probability": s.new_probability,
                "drift_pct": s.drift_pct,
                "direction": s.drift_direction,
                "simulation_only": True,
            }
            for s in signals
        ]

    def get_arbitrage_opportunities(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent arbitrage opportunities (simulation only)."""
        return list(self._arbitrage_opps)[-limit:]

    def get_platform_summary(self) -> Dict[str, Any]:
        """Get summary of markets by platform."""
        summary = {
            "total_markets": len(self._all_markets),
            "platforms": {},
            "simulation_mode": True,
            "warning": "Data includes non-US compliant sources - for simulation only",
        }

        for market in self._all_markets.values():
            platform_name = market.platform.value
            if platform_name not in summary["platforms"]:
                summary["platforms"][platform_name] = {
                    "count": 0,
                    "us_compliant": market.platform == PredictionPlatform.KALSHI,
                    "avg_volume": 0.0,
                }
            summary["platforms"][platform_name]["count"] += 1
            summary["platforms"][platform_name]["avg_volume"] += market.volume_24h

        # Calculate averages
        for platform_data in summary["platforms"].values():
            if platform_data["count"] > 0:
                platform_data["avg_volume"] /= platform_data["count"]

        return summary

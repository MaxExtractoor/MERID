"""§1 Market & Research Agents.

- MarketResearchAgent: ingest news/macro/on-chain, produce structured theses.
- PredictionMarketAgent: Kalshi-specific implied probs, edge, opportunities.
- CryptoSignalsAgent: CEX spreads, funding, basis, structural signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput, CanonicalAgent
from merid.pipeline.proposal import TradeDomain

from utils.logger import get_logger

logger = get_logger("merid.agents.research")


# ── Thesis dataclass ─────────────────────────────────────────────────

class ThesisDirection(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"
    ARB = "arb"


@dataclass
class ResearchThesis:
    """Structured thesis produced by research agents."""
    thesis_id: str = ""
    domain: str = "crypto"
    instrument: str = ""
    direction: ThesisDirection = ThesisDirection.NEUTRAL
    drivers: List[str] = field(default_factory=list)
    confidence: float = 0.5
    time_horizon_hours: float = 24.0
    data_sources: List[str] = field(default_factory=list)
    summary: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "thesis_id": self.thesis_id,
            "domain": self.domain,
            "instrument": self.instrument,
            "direction": self.direction.value,
            "drivers": self.drivers,
            "confidence": self.confidence,
            "time_horizon_hours": self.time_horizon_hours,
            "data_sources": self.data_sources,
            "summary": self.summary,
            "created_at": self.created_at.isoformat(),
        }


# ======================================================================
# MarketResearchAgent
# ======================================================================

class MarketResearchAgent(CanonicalAgent):
    """Ingests news, macro data, on-chain intel, and produces theses.

    Data sources: News API, Polygon, Finnhub, Messari, Nansen, FRED.
    Output: List of ResearchThesis objects.
    """

    def __init__(self, agent_id: str = "market-research-01"):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self._data_sources: List[str] = [
            "news_api", "polygon", "finnhub", "messari", "nansen", "fred",
        ]
        self._theses: List[ResearchThesis] = []

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Analyze available data and produce theses.

        In production: calls each data API, aggregates signals, and
        produces structured thesis objects.  Here we define the typed
        interface.
        """
        theses = await self._generate_theses(context)
        self._theses.extend(theses)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="theses",
            payload={
                "theses": [t.to_dict() for t in theses],
                "count": len(theses),
                "data_sources": self._data_sources,
            },
            confidence=max((t.confidence for t in theses), default=0.5),
        )

    async def _generate_theses(self, context: Dict[str, Any]) -> List[ResearchThesis]:
        """Override point for actual data ingestion and thesis generation."""
        return []

    def get_theses(self, limit: int = 20) -> List[ResearchThesis]:
        return self._theses[-limit:]


# ======================================================================
# PredictionMarketAgent (Kalshi)
# ======================================================================

class PredictionMarketAgentV2(CanonicalAgent):
    """Kalshi-specific agent: implied probs, edge, mispricing detection.

    Integrates with merid.prediction.model and merid.prediction.strategy.
    Output: Candidate trades with justification.
    """

    def __init__(self, agent_id: str = "pm-research-01", venue: str = "kalshi",
                 strategy: Optional[str] = None, strategy_kwargs: Optional[Dict[str, Any]] = None):
        super().__init__(agent_id, AgentCategory.RESEARCH)
        self.venue = venue
        self._watched_markets: List[str] = []
        self._opportunities: List[Dict[str, Any]] = []

        # Pluggable opinion strategy (default: mean_reversion)
        # Promoted from hash_bias based on Brier score evaluation:
        #   mean_reversion: 0.2427 vs market 0.2460 (Δ=-0.0033, beats market)
        #   hash_bias:      0.2535 vs market 0.2460 (Δ=+0.0075, worse than market)
        from merid.prediction.opinion_strategy import get_strategy
        self._strategy = get_strategy(strategy or "mean_reversion", **(strategy_kwargs or {}))

    def watch(self, market_id: str) -> None:
        if market_id not in self._watched_markets:
            self._watched_markets.append(market_id)

    def unwatch(self, market_id: str) -> None:
        self._watched_markets = [m for m in self._watched_markets if m != market_id]

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Scan Kalshi markets for mispricing and near-expiry opportunities.

        Reads active instruments from PredictionConsensusStore, generates
        probabilistic opinions, and submits them to the store.
        """
        opportunities = await self._scan_opportunities(context)
        self._opportunities.extend(opportunities)

        # Submit opinions to the consensus store
        opinions_submitted = self._submit_opinions(opportunities)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="pm_opportunities",
            payload={
                "venue": self.venue,
                "opportunities": opportunities,
                "watched_markets": self._watched_markets,
                "opinions_submitted": opinions_submitted,
            },
            confidence=0.6 if opportunities else 0.3,
        )

    async def _scan_opportunities(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Scan active prediction instruments and generate edge estimates.

        Reads instruments from the PredictionConsensusStore, delegates
        probability estimation to the pluggable OpinionStrategy, and returns
        opportunities where the estimated edge exceeds the strategy threshold.
        """
        import time as _time

        try:
            from merid.prediction.consensus import get_prediction_consensus_store
            store = get_prediction_consensus_store()
        except Exception:
            return []

        instruments = store.list_instruments(status="active", limit=50)
        if not instruments:
            return []

        opportunities = []
        for inst in instruments:
            estimate = self._strategy.estimate(
                agent_id=self.agent_id,
                ticker=inst.ticker,
                market_prob=inst.market_implied_prob,
                category=inst.category,
                context=context,
            )
            if estimate is None:
                continue

            opportunities.append({
                "symbol": inst.symbol,
                "ticker": inst.ticker,
                "venue": inst.venue,
                "category": inst.category,
                "title": inst.title,
                "market_implied_prob": round(inst.market_implied_prob, 4),
                "agent_estimated_prob": estimate.agent_prob,
                "edge": estimate.edge,
                "direction": "yes" if estimate.edge > 0 else "no",
                "confidence": estimate.confidence,
                "strategy": self._strategy.name,
                "reasoning_tag": estimate.reasoning_tag,
                "explanation": estimate.explanation.to_dict() if estimate.explanation else None,
                "scanned_at": _time.time(),
            })

        return opportunities

    def _submit_opinions(self, opportunities: List[Dict[str, Any]]) -> int:
        """Submit opinions to the PredictionConsensusStore for each opportunity."""
        try:
            from merid.prediction.consensus import (
                get_prediction_consensus_store,
                PredictionOpinion,
            )
            store = get_prediction_consensus_store()
        except Exception:
            return 0

        count = 0
        for opp in opportunities:
            try:
                opinion = PredictionOpinion(
                    agent_id=self.agent_id,
                    agent_name="PredictionMarketAgentV2",
                    symbol=opp["symbol"],
                    probability=opp["agent_estimated_prob"],
                    confidence=opp["confidence"],
                    reasoning=f"Edge {opp['edge']:+.2%} vs market {opp['market_implied_prob']:.0%} "
                              f"({opp['category']}: {opp['title'][:60]})",
                    signal_sources=["market_implied_prob", "agent_model"],
                    horizon="event",
                    explanation=opp.get("explanation"),
                )
                store.add_opinion(opinion)
                count += 1
            except Exception as exc:
                logger.warning(f"Opinion submit failed for {opp.get('symbol')}: {exc}")
        if count:
            logger.info(f"pm_agent: submitted {count} opinions from {len(opportunities)} opportunities")
        return count


# ======================================================================
# CryptoSignalsAgent
# ======================================================================

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
        self._watched_pairs: List[str] = ["BTC-USD", "ETH-USD", "SOL-USD"]
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

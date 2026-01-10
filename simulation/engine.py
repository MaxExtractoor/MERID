"""Modular Proof-of-Useful-Simulation (PoUS) engine orchestrator for MERID."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core.event_bus import event_stream
from monitoring.liquidation_monitor import CoinGlassLiquidationMonitor, WhaleIntelMonitor
from monitoring.news_agent import NewsItem, NewsSentinel
from monitoring.onchain_analytics import OnchainAnalyticsMonitor, OnchainSnapshot
from notifications.telegram_client import TelegramAlertClient
from trading.augur_trading_layer import AugurTradingLayer
from trading.perp.adapters import (
    BinancePerpAdapter,
    BybitPerpAdapter,
    CoinbasePerpAdapter,
    CryptoComPerpAdapter,
    DriftPerpAdapter,
    DyDxPerpAdapter,
    GMXPerpAdapter,
    HyperliquidAdapter,
    PerpetualProtocolAdapter,
)
from trading.perp.base import FundingRateSnapshot, PerpMarketSnapshot, WhaleSignal
from trading.polymarket_trading_layer import ChainlinkOracle, PolymarketClient
from utils.logger import get_logger

from swarm.agents.charters import CHARTER_REGISTRY
from swarm.agents.instances import AgentInstance

logger = get_logger("simulation.engine_v2")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SimulationOutcome:
    outcome: str
    explanation: str
    weight: float
    votes: int
    expected_value: float
    final_explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SimulationResult:
    sim_id: str
    model: str
    outcomes: List[SimulationOutcome]
    confidence: float
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["outcomes"] = [outcome.to_dict() for outcome in self.outcomes]
        return payload


@dataclass
class SimulationBlock:
    index: int
    previous_hash: str
    simulations: List[SimulationResult]
    transactions: List[Dict[str, Any]]
    timestamp: float = field(default_factory=time.time)
    nonce: int = 0
    miner: Optional[str] = None
    zk_proof: Optional[str] = None

    def calculate_hash(self) -> str:
        block_dict = {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "simulations": [sim.to_dict() for sim in self.simulations],
            "transactions": self.transactions,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "miner": self.miner,
            "zk_proof": self.zk_proof,
        }
        serialized = json.dumps(block_dict, sort_keys=True).encode()
        return hashlib.sha256(serialized).hexdigest()

    def seal(self) -> None:
        self.hash = self.calculate_hash()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "previous_hash": self.previous_hash,
            "hash": getattr(self, "hash", self.calculate_hash()),
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "miner": self.miner,
            "zk_proof": self.zk_proof,
            "simulations": [sim.to_dict() for sim in self.simulations],
            "transactions": self.transactions,
        }


# ---------------------------------------------------------------------------
# Feature config and token economy
# ---------------------------------------------------------------------------


@dataclass
class SimulationFeatureConfig:
    enable_augur: bool = True
    enable_chainlink: bool = True
    enable_news: bool = True
    enable_liquidations: bool = True
    enable_whales: bool = True
    enable_perp_bundle: bool = True
    enable_onchain_analytics: bool = True
    enable_intent_payloads: bool = True
    enable_zksnark: bool = False
    enable_uma_oracle: bool = False
    theta_half_life_hours: float = 36.0
    funding_half_life_hours: float = 12.0
    default_time_to_resolution_hours: float = 120.0
    default_funding_rate: float = 0.0003
    usefulness_threshold: float = 0.02
    confidence_decay_rate: float = 0.05
    confidence_floor: float = 0.01
    nupl_overheat_threshold: float = 0.75
    mvrv_overheat_threshold: float = 3.5
    sentiment_bearish_threshold: float = -0.2
    alert_topic: str = "alerts.events"

    @classmethod
    def from_env(cls) -> "SimulationFeatureConfig":
        get_bool = lambda key, default: str(os.getenv(key, str(default))).lower() in {"1", "true", "yes"}
        get_float = lambda key, default: float(os.getenv(key, default))
        return cls(
            enable_augur=get_bool("MERID_ENABLE_AUGUR", True),
            enable_chainlink=get_bool("MERID_ENABLE_CHAINLINK", True),
            enable_news=get_bool("MERID_ENABLE_NEWS_AGENT", True),
            enable_liquidations=get_bool("MERID_ENABLE_LIQUIDATIONS", True),
            enable_whales=get_bool("MERID_ENABLE_WHALE_INTEL", True),
            enable_perp_bundle=get_bool("MERID_ENABLE_PERP_INTEL", True),
            enable_onchain_analytics=get_bool("MERID_ENABLE_ONCHAIN_ANALYTICS", True),
            enable_uma_oracle=get_bool("MERID_ENABLE_UMA_ORACLE", False),
            theta_half_life_hours=get_float("MERID_THETA_HALF_LIFE_HOURS", 36.0),
            funding_half_life_hours=get_float("MERID_FUNDING_HALF_LIFE_HOURS", 12.0),
            default_time_to_resolution_hours=get_float("MERID_DEFAULT_TTR_HOURS", 120.0),
            default_funding_rate=get_float("MERID_DEFAULT_FUNDING_RATE", 0.0003),
            usefulness_threshold=get_float("MERID_USEFULNESS_THRESHOLD", 0.02),
            confidence_decay_rate=get_float("MERID_CONFIDENCE_DECAY_RATE", 0.05),
            confidence_floor=get_float("MERID_CONFIDENCE_FLOOR", 0.01),
            nupl_overheat_threshold=get_float("MERID_NUPL_OVERHEAT_THRESHOLD", 0.75),
            mvrv_overheat_threshold=get_float("MERID_MVRV_OVERHEAT_THRESHOLD", 3.5),
            sentiment_bearish_threshold=get_float("MERID_SENTIMENT_BEARISH_THRESHOLD", -0.2),
            alert_topic=os.getenv("MERID_ALERT_TOPIC", "alerts.events"),
        )

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


class TokenEconomy:
    """Minimal token tracker used by web handlers."""

    def __init__(self) -> None:
        self._balances: Dict[str, float] = {}

    def mint(self, agent_id: str, amount: float) -> None:
        self._balances[agent_id] = self._balances.get(agent_id, 0.0) + amount

    def balance(self, agent_id: str) -> float:
        return self._balances.get(agent_id, 0.0)

    def to_dict(self) -> Dict[str, float]:
        return dict(self._balances)


# ---------------------------------------------------------------------------
# Simulation chain orchestrator
# ---------------------------------------------------------------------------


class MeridSimulationChain:
    def __init__(
        self,
        *,
        trading_client: Optional[PolymarketClient] = None,
        features: Optional[SimulationFeatureConfig] = None,
        event_topic: str = "simulation.blocks",
        enable_mock: bool = False,
    ) -> None:
        self.features = features or SimulationFeatureConfig.from_env()
        self.trading_client = trading_client or PolymarketClient(use_mock=enable_mock)
        self.augur_trading = AugurTradingLayer(use_mock=enable_mock)
        self.chainlink_oracle = ChainlinkOracle()
        self.coin_glass = CoinGlassLiquidationMonitor()
        self.whale_monitor = WhaleIntelMonitor()
        self.news_agent = NewsSentinel()
        self.onchain_monitor = OnchainAnalyticsMonitor()
        self.telegram_client = TelegramAlertClient()
        self.token_economy = TokenEconomy()
        self.chain: List[SimulationBlock] = []
        self.event_topic = event_topic
        self.confidence_decay_rate = self.features.confidence_decay_rate
        self.usefulness_threshold = self.features.usefulness_threshold
        self.perp_adapters = self._build_perp_adapters() if self.features.enable_perp_bundle else []
        self._intel_history: List[Dict[str, Any]] = []
        self._alert_history: List[Dict[str, Any]] = []
        self._heatmap_snapshot: Dict[str, Any] = {}
        self._ticker_snapshot: Dict[str, Any] = {}
        self._assist_snapshot: Dict[str, Any] = {}
        self._hover_metadata: Dict[str, Any] = {}
        self.agents: Dict[str, AgentInstance] = {}
        self._lineage_log: List[Dict[str, Any]] = []
        self._max_agents = int(os.getenv("MERID_MAX_AGENTS", "32"))
        self._lineage_log_limit = int(os.getenv("MERID_LINEAGE_HISTORY", "500"))
        self._consensus_history: List[Dict[str, Any]] = []
        self._consensus_history_limit = 200
        self._last_consensus_resolution = None
        self._marl_coordinator = None
        self._pso_optimizer = None
        self._bootstrap_agents()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def mine_block(self, miner_id: str, *, premium: bool = True) -> SimulationBlock:
        result = self._run_swarm_simulation(premium=premium)
        block = SimulationBlock(
            index=len(self.chain),
            previous_hash=self.chain[-1].calculate_hash() if self.chain else "0x00",
            simulations=[result],
            transactions=[],
            miner=miner_id,
        )
        block.seal()
        self.chain.append(block)
        self._publish_event(block)
        logger.info(
            "Block #%s mined by %s | market=%s | confidence=%.3f",
            block.index,
            miner_id,
            result.data.get("market"),
            result.confidence,
        )
        return block

    def export_blocks(self, limit: int = 20) -> List[Dict[str, Any]]:
        blocks = self.chain[-limit:]
        return [self._apply_confidence_decay_to_block_dict(block.to_dict(), block.index) for block in blocks]

    def ledger_state(self) -> Dict[str, Any]:
        return {
            "height": len(self.chain),
            "event_listeners": event_stream.listener_count(),
            "token_supply": sum(self.token_economy.to_dict().values()),
        }

    def intel_snapshot(self, limit: int = 40) -> Dict[str, Any]:
        return {"items": list(reversed(self._intel_history[-limit:]))}

    def alert_snapshot(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self._alert_history[-limit:]))

    def heatmap_snapshot(self, limit: int = 40) -> Dict[str, Any]:
        snapshot = self._heatmap_snapshot or {}
        return {
            "generated_at": snapshot.get("generated_at"),
            "liquidations": (snapshot.get("liquidations") or [])[:limit],
            "symbols": (snapshot.get("symbols") or [])[:limit],
            "venues": (snapshot.get("venues") or [])[:limit],
            "perp_markets": (snapshot.get("perp_markets") or [])[:limit],
            "arbitrage": snapshot.get("arbitrage"),
        }

    def ticker_snapshot(self, limit: int = 25) -> Dict[str, Any]:
        snapshot = self._ticker_snapshot or {}
        tickers = snapshot.get("tickers") or []
        funding = snapshot.get("funding_extremes") or {}
        return {
            "generated_at": snapshot.get("generated_at"),
            "tickers": tickers[:limit],
            "funding_extremes": funding,
            "arbitrage": snapshot.get("arbitrage"),
        }

    def assist_snapshot(self) -> Dict[str, Any]:
        return self._assist_snapshot or {}

    def hover_metadata(self) -> Dict[str, Any]:
        return self._hover_metadata or {}

    def consensus_history_snapshot(self, limit: int = 50) -> Dict[str, Any]:
        """Stage 6: Return recent consensus outcomes with source reliability context."""
        return {"history": list(reversed(self._consensus_history[-limit:]))}

    def marl_metrics_snapshot(self) -> Dict[str, Any]:
        """Stage 9: Return MARL training metrics."""
        if self._marl_coordinator is None:
            return {"status": "not_initialized", "metrics": {}}
        return {
            "status": "active",
            "metrics": self._marl_coordinator.get_metrics(),
        }

    def pso_metrics_snapshot(self) -> Dict[str, Any]:
        """Stage 10: Return PSO optimization metrics."""
        if self._pso_optimizer is None:
            return {"status": "not_initialized", "metrics": {}}
        return {
            "status": "active",
            "metrics": self._pso_optimizer.get_metrics(),
        }

    # ------------------------------------------------------------------
    # Core simulation workflow
    # ------------------------------------------------------------------
    def _run_swarm_simulation(self, *, premium: bool) -> SimulationResult:
        primary_markets = self.trading_client.fetch_markets(limit=25)
        primary_opps = self.trading_client.find_negative_risk_opportunities(primary_markets)
        augur_opps: List[Dict[str, Any]] = []
        if self.features.enable_augur:
            aug_markets = self.augur_trading.fetch_markets(limit=25)
            augur_opps = self.augur_trading.find_negative_risk_opportunities(aug_markets)

        opportunities = list(primary_opps)
        if augur_opps:
            opportunities.extend(augur_opps)
        if not opportunities:
            raise RuntimeError("No viable prediction-market opportunities discovered.")

        opportunities.sort(key=lambda item: item.get("edge", 0.0), reverse=True)
        target_market = opportunities[0]
        market_slug = target_market.get("slug") or target_market.get("id") or "unknown-market"
        selected_platform = target_market.get("platform", "polymarket")
        yes_price = float(target_market.get("yes_price", 0.5))
        
        # Stage 4: UMA oracle integration for high-confidence consensus
        uma_assertion_id = None
        if premium and self.features.enable_uma_oracle:
            uma_assertion_id = self._propose_uma_assertion(market_slug, yes_price)
        no_price = float(target_market.get("no_price", max(0.0, 1 - yes_price)))
        base_probability_yes = yes_price
        base_probability_no = no_price

        platforms_in_play = sorted({item.get("platform", "polymarket") for item in opportunities})
        arbitrage_gap = None
        if primary_opps and augur_opps:
            arbitrage_gap = primary_opps[0]["yes_price"] - augur_opps[0]["yes_price"]

        swarm = self._build_swarm_agents()
        outcomes = self._simulate_outcomes(swarm, market_slug, premium, base_probability_yes, base_probability_no)
        
        # Stage 6.5: Route through hardened consensus gate
        consensus_resolution = self._resolve_hardened_consensus(outcomes, market_slug)
        confidence = consensus_resolution.confidence

        hours_to_resolution = float(
            target_market.get("hours_to_resolution") or self.features.default_time_to_resolution_hours
        )
        theta_yes = self._apply_market_decay(base_probability_yes, hours_to_resolution)
        theta_no = self._apply_market_decay(base_probability_no, hours_to_resolution)
        base_probability_yes = theta_yes["decayed_probability"]
        base_probability_no = theta_no["decayed_probability"]
        theta_factor = (theta_yes["decay_factor"] + theta_no["decay_factor"]) / 2
        confidence *= theta_factor

        funding_rate = float(target_market.get("funding_rate") or self.features.default_funding_rate)
        funding_adjustment = self._apply_funding_decay(confidence, funding_rate, hours_to_resolution)
        confidence = funding_adjustment["adjusted_confidence"]

        perp_bundle = self._collect_perp_bundle() if self.features.enable_perp_bundle else None
        liquidation_bundle = self._collect_liquidation_bundle()
        news_bundle = self._collect_news_bundle()
        onchain_snapshot = self._collect_onchain_snapshot()
        risk_package = self._evaluate_onchain_risk(onchain_snapshot, confidence)
        confidence = risk_package["adjusted_confidence"]

        oracle_snapshot: Dict[str, Dict[str, Any]] = {}
        oracle_gap = None
        if self.features.enable_chainlink:
            oracle_snapshot = self.chainlink_oracle.fetch_feeds()
            oracle_gap = self._estimate_reality_gap(oracle_snapshot, base_probability_yes, base_probability_no)
            if oracle_gap is not None:
                confidence *= max(0.5, 1 - abs(oracle_gap))

        confidence = max(self.features.confidence_floor, min(0.999, confidence))
        intent_payload = self._build_intent_payload(
            selected_platform=selected_platform,
            market_slug=market_slug,
            arbitrage_gap=arbitrage_gap,
            theta={"yes": theta_yes, "no": theta_no},
            funding=funding_adjustment,
        )
        explainability_payload = self._build_explainability_payload(
            market_slug=market_slug,
            theta={"yes": theta_yes, "no": theta_no},
            funding=funding_adjustment,
            oracle_gap=oracle_gap,
            platforms=platforms_in_play,
        )

        model_name = "hybrid_swarm_v1" if len(platforms_in_play) > 1 else "swarm_monte_carlo_v2"
        sim_result = SimulationResult(
            sim_id=f"swarm::{market_slug}::{int(time.time())}",
            model=model_name,
            outcomes=outcomes,
            confidence=confidence,
            data={
                "market": market_slug,
                "yes_price": yes_price,
                "no_price": no_price,
                "volume": target_market.get("volume"),
                "platforms": platforms_in_play,
                "selected_platform": selected_platform,
                "arbitrage_gap": arbitrage_gap,
                "hybrid": len(platforms_in_play) > 1,
                "feature_flags": self.features.to_payload(),
                "oracle_snapshot": oracle_snapshot,
                "oracle_gap": oracle_gap,
                "hours_to_resolution": hours_to_resolution,
                "funding_rate": funding_rate,
                "decay": {"yes": theta_yes, "no": theta_no, "funding": funding_adjustment},
                "intent": intent_payload,
                "explainability": explainability_payload,
                "perp_bundle": perp_bundle,
                "liquidation_bundle": liquidation_bundle,
                "news_bundle": news_bundle,
                "onchain_snapshot": onchain_snapshot.__dict__ if onchain_snapshot else None,
                "risk_flags": risk_package.get("flags"),
            },
        )
        self._record_intel_snapshot(perp_bundle, liquidation_bundle, news_bundle, onchain_snapshot)
        self._capture_ai_assist_payload(sim_result)
        self._dispatch_alerts(sim_result.data)
        self._apply_agent_decay()
        self._evaluate_spawn_rules(sim_result)
        return sim_result

    # ------------------------------------------------------------------
    # Swarm helpers
    # ------------------------------------------------------------------
    def _build_swarm_agents(self) -> List[Dict[str, float]]:
        random.seed("merid-swarm-agents")
        return [
            {"name": "Market Scanner", "expertise": 0.85, "risk": 0.4},
            {"name": "Risk Evaluator", "expertise": 0.92, "risk": 0.2},
            {"name": "Sentiment Analyst", "expertise": 0.78, "risk": 0.6},
            {"name": "Liquidity Hunter", "expertise": 0.81, "risk": 0.5},
        ]

    def _simulate_outcomes(
        self,
        swarm: List[Dict[str, float]],
        market_slug: str,
        premium: bool,
        base_yes: float,
        base_no: float,
    ) -> List[SimulationOutcome]:
        outcomes: List[SimulationOutcome] = []
        for label, base_probability in (("YES", base_yes), ("NO", base_no)):
            contributions = []
            for agent in swarm:
                paths = 150 if premium else 60
                samples = [
                    random.gauss(base_probability, 0.08 * (1 - agent["expertise"]))
                    for _ in range(paths)
                ]
                samples = [max(0.001, min(0.999, sample)) for sample in samples]
                expected_value = sum(samples) / len(samples)
                weight = max(0.01, agent["expertise"] * (1 - abs(expected_value - base_probability)))
                vote = 1 if expected_value > base_probability else 0
                contributions.append(
                    {
                        "agent": agent["name"],
                        "weight": weight,
                        "expected_value": expected_value,
                        "vote": vote,
                        "explanation": (
                            f"{agent['name']} ran {paths} Monte Carlo paths "
                            f"and nudged implied probability to {expected_value:.3f}."
                        ),
                    }
                )
            avg_weight = sum(item["weight"] for item in contributions) / len(contributions)
            avg_expected_value = sum(item["expected_value"] for item in contributions) / len(contributions)
            votes = sum(item["vote"] for item in contributions)
            combined_explanation = " | ".join(item["explanation"] for item in contributions)
            final_explanation = (
                f"{votes}/{len(contributions)} agents aligned for {label}. "
                f"Expected value {avg_expected_value:.3f} vs base {base_probability:.3f}."
            )
            outcomes.append(
                SimulationOutcome(
                    outcome=label,
                    explanation=combined_explanation,
                    weight=avg_weight,
                    votes=votes,
                    expected_value=avg_expected_value,
                    final_explanation=final_explanation,
                )
            )

        total_weight = sum(outcome.weight for outcome in outcomes) or 1.0
        for outcome in outcomes:
            outcome.weight /= total_weight
        return outcomes

    def _aggregate_confidence(self, outcomes: List[SimulationOutcome]) -> float:
        if not outcomes:
            return 0.0
        votes = sum(outcome.votes for outcome in outcomes)
        max_votes = len(outcomes) * 4  # number of swarm agents
        return max(self.features.confidence_floor, votes / (max_votes or 1))

    def _resolve_hardened_consensus(
        self,
        outcomes: List[SimulationOutcome],
        market_slug: str,
    ):
        """Stage 6.5: Route consensus through hardened gate with adversarial checks."""
        from core.consensus_gate import resolve_consensus, update_agent_trust_gated
        from core.consensus_math import Vote
        from core.energy_confidence import EnergyConfidence
        from core.source_health import get_source_registry
        from core.agent_trust import get_trust_registry

        # Build votes from outcomes
        votes = []
        claims = []
        trust_registry = get_trust_registry()
        source_registry = get_source_registry()

        for outcome in outcomes:
            # Map each agent contribution to a vote
            agent_id = outcome.outcome  # Use outcome label as agent ID for now
            vote_value = 1 if outcome.votes > 0 else -1
            trust = trust_registry.get_trust(agent_id)
            
            # Compute energy confidence with source reliability
            source = "polymarket"  # Default source
            energy_conf = EnergyConfidence.compute(
                confidence_base=outcome.weight,
                source=source,
                fallback_used=False,
                api_failed=False,
            )
            
            votes.append(
                Vote(
                    agent_id=agent_id,
                    vote=vote_value,
                    trust=trust,
                    confidence=energy_conf.confidence_final,
                    source=source,
                    source_srw=energy_conf.source_srw,
                )
            )
            
            claims.append({
                "source": source,
                "metric": "outcome_probability",
                "value": outcome.expected_value,
                "weight": outcome.weight,
            })

        # Resolve through hardened consensus gate
        resolution = resolve_consensus(votes, claims, threshold=0.6)
        
        # Trigger agent forking if poisoning detected
        if resolution.poisoning_detected:
            from core.consensus_gate import fork_agents_on_poisoning
            forked_ids = fork_agents_on_poisoning(
                reason=f"temporal={resolution.temporal_violations},collusion={resolution.collusion_detected},shadow={resolution.shadow_divergence}"
            )
            logger.warning(
                "Poisoning detected in market %s: forked %d agents",
                market_slug,
                len(forked_ids),
            )
        
        # Record consensus event
        consensus_event = {
            "market": market_slug,
            "timestamp": time.time(),
            "consensus_score": resolution.consensus_score,
            "confidence": resolution.confidence,
            "approved": resolution.approved,
            "poisoning_detected": resolution.poisoning_detected,
            "trust_updates_allowed": resolution.trust_updates_allowed,
            "degraded_mode": resolution.degraded_mode,
            "temporal_violations": resolution.temporal_violations,
            "collusion_detected": resolution.collusion_detected,
            "shadow_divergence": resolution.shadow_divergence,
            "metadata": resolution.metadata,
        }
        
        self._consensus_history.append(consensus_event)
        if len(self._consensus_history) > self._consensus_history_limit:
            self._consensus_history.pop(0)
        
        self._last_consensus_resolution = resolution
        
        # Update agent trust if allowed (gated by poisoning state)
        if resolution.trust_updates_allowed:
            for vote in votes:
                # Simplified: assume all votes are "correct" for now
                # In production, this would be based on actual outcome verification
                update_agent_trust_gated(
                    agent_id=vote.agent_id,
                    vote_correct=True,
                    source_srw=vote.source_srw,
                )
        
        return resolution

    # ------------------------------------------------------------------
    # Intelligence collectors
    # ------------------------------------------------------------------
    def _collect_perp_bundle(self) -> Dict[str, Any]:
        bundle: Dict[str, Any] = {"markets": [], "funding": [], "whales": [], "arbitrage": None}
        market_snapshots: List[PerpMarketSnapshot] = []
        funding_snapshots: List[FundingRateSnapshot] = []
        whale_signals: List[WhaleSignal] = []
        for adapter in self.perp_adapters:
            try:
                market_snapshots.extend(adapter.fetch_markets(limit=10))
                funding_snapshots.extend(adapter.fetch_funding_rates())
                whale_signals.extend(adapter.fetch_whale_signals(limit=5))
            except Exception as exc:
                logger.debug("Perp adapter %s failed: %s", adapter.venue, exc)

        bundle["markets"] = [asdict(snapshot) for snapshot in market_snapshots]
        bundle["funding"] = [asdict(snapshot) for snapshot in funding_snapshots]
        bundle["whales"] = [asdict(signal) for signal in whale_signals]
        bundle["arbitrage"] = self._detect_perp_arbitrage(market_snapshots)
        return bundle

    def _collect_liquidation_bundle(self) -> Dict[str, Any]:
        heatmap = self.coin_glass.fetch_heatmap()
        whales = self.whale_monitor.fetch_signals(limit=15) if self.features.enable_whales else []
        return {
            "liquidations": [asdict(event) for event in heatmap],
            "whales": [asdict(signal) for signal in whales],
        }

    def _collect_news_bundle(self) -> List[Dict[str, Any]]:
        if not self.features.enable_news:
            return []
        headlines = self.news_agent.fetch_headlines(limit=5)
        return [asdict(item) for item in headlines]

    def _collect_onchain_snapshot(self) -> Optional[OnchainSnapshot]:
        if not self.features.enable_onchain_analytics:
            return None
        try:
            return self.onchain_monitor.fetch_snapshot()
        except Exception as exc:
            logger.warning("On-chain analytics fetch failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Risk + adjustments
    # ------------------------------------------------------------------
    def _detect_perp_arbitrage(self, snapshots: Sequence[PerpMarketSnapshot]) -> Optional[Dict[str, Any]]:
        if len(snapshots) < 2:
            return None
        sorted_snaps = sorted(snapshots, key=lambda snap: snap.price - snap.index_price, reverse=True)
        best = sorted_snaps[0]
        worst = sorted_snaps[-1]
        spread = (best.price - best.index_price) - (worst.price - worst.index_price)
        if abs(spread) < 5:
            return None
        return {
            "long": asdict(worst),
            "short": asdict(best),
            "spread": spread,
            "explanation": f"Basis divergence {spread:.2f} detected across venues.",
        }

    def _evaluate_onchain_risk(
        self,
        snapshot: Optional[OnchainSnapshot],
        confidence: float,
    ) -> Dict[str, Any]:
        if not snapshot:
            return {"adjusted_confidence": confidence, "flags": []}
        adjusted = confidence
        flags: List[Dict[str, Any]] = []
        if snapshot.nupl is not None and snapshot.nupl >= self.features.nupl_overheat_threshold:
            adjusted *= 0.85
            flags.append(
                {
                    "metric": "NUPL",
                    "value": snapshot.nupl,
                    "threshold": self.features.nupl_overheat_threshold,
                    "message": "NUPL overheated — crowd euphoria, dampening confidence.",
                }
            )
        if snapshot.mvrv is not None and snapshot.mvrv >= self.features.mvrv_overheat_threshold:
            adjusted *= 0.9
            flags.append(
                {
                    "metric": "MVRV",
                    "value": snapshot.mvrv,
                    "threshold": self.features.mvrv_overheat_threshold,
                    "message": "MVRV elevated — profit-taking risk.",
                }
            )
        if snapshot.sentiment_score is not None:
            if snapshot.sentiment_score <= self.features.sentiment_bearish_threshold:
                adjusted *= 0.92
                flags.append(
                    {
                        "metric": "Sentiment",
                        "value": snapshot.sentiment_score,
                        "threshold": self.features.sentiment_bearish_threshold,
                        "message": "On-chain sentiment bearish.",
                    }
                )
            elif snapshot.sentiment_score >= 0.35:
                adjusted = min(0.999, adjusted * 1.03)
                flags.append(
                    {
                        "metric": "Sentiment",
                        "value": snapshot.sentiment_score,
                        "threshold": 0.35,
                        "message": "On-chain sentiment constructive; applying slight boost.",
                    }
                )
        adjusted = max(self.features.confidence_floor, min(0.999, adjusted))
        return {"adjusted_confidence": adjusted, "flags": flags}

    # ------------------------------------------------------------------
    # Agent lifecycle management
    # ------------------------------------------------------------------
    def _bootstrap_agents(self) -> None:
        for role, charter in CHARTER_REGISTRY.items():
            if not charter.active:
                continue
            agent = AgentInstance(charter=charter)
            self.agents[agent.instance_id] = agent
            self._record_lineage_event(agent, event="bootstrap")
        logger.info("Initialized charter cohort with %d base agents.", len(self.agents))

    def spawn_agent(self, charter_role: str, parent_id: Optional[str] = None) -> AgentInstance:
        charter = CHARTER_REGISTRY.get(charter_role)
        if not charter:
            raise ValueError(f"Unknown charter role '{charter_role}'")
        agent = AgentInstance(charter=charter)
        if parent_id and parent_id in self.agents:
            agent.inherit_from_parent(self.agents[parent_id])
        self.agents[agent.instance_id] = agent
        self._record_lineage_event(agent, event="spawn", parent_id=parent_id)
        logger.info("Spawned agent %s (%s) parent=%s", agent.instance_id, charter_role, parent_id or "gen0")
        self._enforce_population_cap()
        return agent

    def _record_lineage_event(self, agent: AgentInstance, *, event: str, parent_id: Optional[str] = None) -> None:
        self._lineage_log.append(
            {
                "agent_id": agent.instance_id,
                "parent_id": parent_id,
                "role": agent.role,
                "event": event,
                "timestamp": time.time(),
                "score": agent.current_score,
                "lineage": list(agent.lineage),
            }
        )
        if len(self._lineage_log) > self._lineage_log_limit:
            excess = len(self._lineage_log) - self._lineage_log_limit
            del self._lineage_log[:excess]

    def _enforce_population_cap(self) -> None:
        if len(self.agents) <= self._max_agents:
            return
        sorted_agents = sorted(self.agents.values(), key=lambda inst: inst.current_score)
        for agent in sorted_agents:
            if len(self.agents) <= self._max_agents:
                break
            if not agent.parent_id:  # keep genesis agents
                continue
            agent.active = False
            self._record_lineage_event(agent, event="retired", parent_id=agent.parent_id)
            self.agents.pop(agent.instance_id, None)
            logger.info("Retired agent %s to enforce population cap.", agent.instance_id)

    def _apply_agent_decay(self) -> None:
        now = time.time()
        for agent in list(self.agents.values()):
            before = agent.current_score
            was_active = agent.active
            agent.apply_decay(now)
            if not agent.active:
                logger.debug("Agent %s decayed below threshold (%.3f).", agent.instance_id, before)
                if was_active:
                    self._record_lineage_event(agent, event="decayed", parent_id=agent.parent_id)

    def _evaluate_spawn_rules(self, sim_result: SimulationResult) -> None:
        if len(self.agents) >= self._max_agents:
            return
        sim_data = sim_result.data or {}
        metrics = self._derive_spawn_metrics(sim_result, sim_data)
        for role, charter in CHARTER_REGISTRY.items():
            if not charter.active or not charter.spawn_conditions:
                continue
            if not self._conditions_met(charter.spawn_conditions, metrics):
                continue
            parent_id = self._select_parent(role)
            self.spawn_agent(role, parent_id)

    def _derive_spawn_metrics(self, sim_result: SimulationResult, sim_data: Dict[str, Any]) -> Dict[str, float]:
        liquidation_bundle = sim_data.get("liquidation_bundle") or {}
        news_bundle = sim_data.get("news_bundle") or []
        metrics = {
            "confidence": sim_result.confidence,
            "arbitrage_gap": abs(sim_data.get("arbitrage_gap") or 0.0),
            "oracle_gap": abs(sim_data.get("oracle_gap") or 0.0),
            "news_intensity": float(len(news_bundle)),
            "liquidation_events": float(len(liquidation_bundle.get("liquidations") or [])),
            "funding_rate": abs(sim_data.get("funding_rate") or self.features.default_funding_rate),
            "hybrid": 1.0 if sim_data.get("hybrid") else 0.0,
        }
        return metrics

    def _conditions_met(self, conditions: Dict[str, float], metrics: Dict[str, float]) -> bool:
        for key, threshold in conditions.items():
            value = metrics.get(key)
            if value is None or value < threshold:
                return False
        return True

    def _select_parent(self, role: str) -> Optional[str]:
        candidates = [agent for agent in self.agents.values() if agent.role == role and agent.active]
        if not candidates:
            return None
        candidates.sort(key=lambda inst: inst.current_score, reverse=True)
        return candidates[0].instance_id

    def agent_population_snapshot(self, limit: int = 40) -> Dict[str, Any]:
        ordered = sorted(self.agents.values(), key=lambda inst: inst.current_score, reverse=True)
        agents = [agent.to_dict() for agent in ordered[:limit]]
        return {
            "total": len(self.agents),
            "active": sum(1 for agent in self.agents.values() if agent.active),
            "inactive": sum(1 for agent in self.agents.values() if not agent.active),
            "limit": limit,
            "agents": agents,
        }

    def lineage_snapshot(self, limit: int = 200) -> Dict[str, Any]:
        sample = self._lineage_log[-limit:]
        return {
            "total_events": len(self._lineage_log),
            "returned": len(sample),
            "events": sample,
        }

    def _estimate_reality_gap(
        self,
        oracle_snapshot: Dict[str, Dict[str, Any]],
        yes_probability: float,
        no_probability: float,
    ) -> Optional[float]:
        if not oracle_snapshot:
            return None
        oracle_probs = [
            feed["price"] / (feed.get("scale_hint") or feed["price"] or 1.0)
            for feed in oracle_snapshot.values()
            if feed.get("price")
        ]
        if not oracle_probs:
            return None
        oracle_average = sum(oracle_probs) / len(oracle_probs)
        implied_avg = (yes_probability + (1 - no_probability)) / 2
        return implied_avg - oracle_average

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------
    def _build_intent_payload(
        self,
        *,
        selected_platform: str,
        market_slug: str,
        arbitrage_gap: Optional[float],
        theta: Dict[str, Any],
        funding: Dict[str, Any],
    ) -> Dict[str, Any]:
        summary = (
            f"Exploit {selected_platform} horizon-adjusted edge on {market_slug} "
            f"while accounting for funding bias ({funding['bias_direction']})."
        )
        drivers = [
            {
                "label": "Theta Decay",
                "detail": theta["yes"]["explanation"],
                "impact": f"yes:{theta['yes']['decayed_probability']:.3f} no:{theta['no']['decayed_probability']:.3f}",
            },
            {
                "label": "Funding Bias",
                "detail": funding["explanation"],
                "impact": f"confidence→{funding['adjusted_confidence']:.3f}",
            },
        ]
        if arbitrage_gap is not None:
            drivers.append(
                {
                    "label": "Hybrid Arbitrage",
                    "detail": f"Polymarket vs Augur gap {arbitrage_gap:.4f}",
                    "impact": "selects venue with superior implied odds",
                }
            )
        return {"summary": summary, "drivers": drivers}

    def _build_explainability_payload(
        self,
        *,
        market_slug: str,
        theta: Dict[str, Any],
        funding: Dict[str, Any],
        oracle_gap: Optional[float],
        platforms: List[str],
    ) -> Dict[str, Any]:
        payload = {
            "market": market_slug,
            "platforms": platforms,
            "theta": theta,
            "funding": funding,
        }
        if oracle_gap is not None:
            payload["oracle_gap"] = {
                "value": oracle_gap,
                "explanation": f"Chainlink anchor differs by {oracle_gap:.4f}, dampening confidence accordingly.",
            }
        return payload

    # ------------------------------------------------------------------
    # Event + alert utilities
    # ------------------------------------------------------------------
    def _publish_event(self, block: SimulationBlock) -> None:
        block_view = self._apply_confidence_decay_to_block_dict(block.to_dict(), block.index)
        event_payload = {
            "height": block.index,
            "hash": block_view["hash"],
            "miner": block.miner,
            "markets": [sim["data"].get("market") for sim in block_view.get("simulations", [])],
            "confidence": block_view.get("simulations", [{}])[0].get("decayed_confidence"),
            "decay": block_view.get("simulations", [{}])[0].get("data", {}).get("decay"),
        }
        self._dispatch_event(self.event_topic, event_payload)

    def _dispatch_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(event_stream.publish(event_type, payload))
        except RuntimeError:
            # not in async context
            asyncio.run(event_stream.publish(event_type, payload))

    def _dispatch_alerts(self, sim_data: Dict[str, Any]) -> None:
        alerts: List[Dict[str, Any]] = []
        for news in sim_data.get("news_bundle") or []:
            if news.get("importance") == "high":
                alerts.append(
                    {
                        "type": "news_high_importance",
                        "source": news.get("source"),
                        "headline": news.get("headline"),
                        "metadata": news,
                    }
                )
        for flag in sim_data.get("risk_flags") or []:
            alerts.append(
                {
                    "type": "onchain_risk_flag",
                    "metric": flag.get("metric"),
                    "message": flag.get("message"),
                    "metadata": flag,
                }
            )
        for alert in alerts[:5]:
            self._record_alert(alert)
            if self.features.alert_topic:
                self._dispatch_event(self.features.alert_topic, alert)
            self.telegram_client.send_alert(alert)

    def _record_intel_snapshot(
        self,
        perp_bundle: Optional[Dict[str, Any]],
        liquidation_bundle: Dict[str, Any],
        news_bundle: List[Dict[str, Any]],
        onchain_snapshot: Optional[OnchainSnapshot],
    ) -> None:
        self._intel_history.append(
            {
                "timestamp": time.time(),
                "perp_bundle": perp_bundle,
                "liquidations": liquidation_bundle,
                "news": news_bundle,
                "onchain": onchain_snapshot.__dict__ if onchain_snapshot else None,
            }
        )
        self._calculate_heatmap_snapshot(perp_bundle, liquidation_bundle)
        self._calculate_ticker_snapshot(perp_bundle)

    def _record_alert(self, alert: Dict[str, Any]) -> None:
        alert["timestamp"] = time.time()
        self._alert_history.append(alert)

    def _calculate_heatmap_snapshot(
        self,
        perp_bundle: Optional[Dict[str, Any]],
        liquidation_bundle: Optional[Dict[str, Any]],
    ) -> None:
        if not liquidation_bundle:
            return
        liquidations = liquidation_bundle.get("liquidations") or []
        venues: Dict[str, float] = defaultdict(float)
        symbols: Dict[str, Dict[str, Any]] = {}
        latest = sorted(
            liquidations,
            key=lambda event: float(event.get("timestamp_ms") or event.get("timestamp") or 0.0),
            reverse=True,
        )
        for event in liquidations:
            notional = float(event.get("notional") or event.get("value") or 0.0)
            venue = str(event.get("venue") or "unknown").lower()
            venues[venue] += notional
            symbol = str(event.get("symbol") or "UNKNOWN")
            bucket = symbols.setdefault(
                symbol,
                {"symbol": symbol, "long": 0.0, "short": 0.0, "total": 0.0},
            )
            side = (event.get("side") or "").lower()
            if side == "long":
                bucket["long"] += notional
            else:
                bucket["short"] += notional
            bucket["total"] += notional

        sorted_symbols = sorted(
            symbols.values(),
            key=lambda entry: entry["total"],
            reverse=True,
        )
        sorted_venues = sorted(
            ({"venue": venue, "volume": volume} for venue, volume in venues.items()),
            key=lambda entry: entry["volume"],
            reverse=True,
        )

        perp_markets: List[Dict[str, Any]] = []
        arbitrage = None
        if perp_bundle:
            perp_markets = sorted(
                perp_bundle.get("markets") or [],
                key=lambda snap: abs(snap.get("basis") or 0.0),
                reverse=True,
            )
            arbitrage = perp_bundle.get("arbitrage")

        self._heatmap_snapshot = {
            "generated_at": time.time(),
            "liquidations": latest[:200],
            "symbols": sorted_symbols,
            "venues": sorted_venues,
            "perp_markets": perp_markets[:50],
            "arbitrage": arbitrage,
        }

    def _calculate_ticker_snapshot(self, perp_bundle: Optional[Dict[str, Any]]) -> None:
        if not perp_bundle:
            return
        markets = perp_bundle.get("markets") or []
        if not markets:
            return

        tickers: List[Dict[str, Any]] = []
        for entry in markets:
            price = float(entry.get("price") or 0.0)
            index_price = float(entry.get("index_price") or price or 1.0)
            basis = price - index_price
            basis_pct = (basis / index_price) if index_price else 0.0
            tickers.append(
                {
                    "venue": entry.get("venue"),
                    "symbol": entry.get("symbol"),
                    "price": price,
                    "index_price": index_price,
                    "basis": basis,
                    "basis_pct": basis_pct,
                    "funding_rate": float(entry.get("funding_rate") or 0.0),
                    "open_interest": float(entry.get("open_interest") or 0.0),
                    "volume_24h": float(entry.get("volume_24h") or 0.0),
                    "metadata": entry.get("metadata") or {},
                }
            )

        tickers.sort(key=lambda item: item["volume_24h"], reverse=True)

        funding_entries = perp_bundle.get("funding") or []
        funding_sorted = sorted(funding_entries, key=lambda item: float(item.get("funding_rate") or 0.0))

        def _format_funding(entry: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "venue": entry.get("venue"),
                "symbol": entry.get("symbol"),
                "funding_rate": float(entry.get("funding_rate") or 0.0),
                "estimated_apr": float(entry.get("estimated_apr") or 0.0),
                "next_settlement_ms": entry.get("next_settlement_ms"),
            }

        funding_extremes = {
            "most_negative": [_format_funding(entry) for entry in funding_sorted[:3]],
            "most_positive": [_format_funding(entry) for entry in reversed(funding_sorted[-3:])],
        }

        self._ticker_snapshot = {
            "generated_at": time.time(),
            "tickers": tickers[:100],
            "funding_extremes": funding_extremes,
            "arbitrage": perp_bundle.get("arbitrage"),
        }

    def _capture_ai_assist_payload(self, result: SimulationResult) -> None:
        data = result.data or {}
        intent = data.get("intent") or {}
        explainability = data.get("explainability") or {}
        risk_flags = data.get("risk_flags") or []
        news_bundle = (data.get("news_bundle") or [])[:5]
        heatmap = self.heatmap_snapshot(limit=10)
        ticker = self.ticker_snapshot(limit=10)

        self._assist_snapshot = {
            "timestamp": result.timestamp,
            "market": data.get("market"),
            "platforms": data.get("platforms"),
            "selected_platform": data.get("selected_platform"),
            "confidence": result.confidence,
            "summary": intent.get("summary"),
            "drivers": intent.get("drivers"),
            "risk_flags": risk_flags,
            "news": news_bundle,
            "heatmap": {
                "symbols": heatmap.get("symbols"),
                "venues": heatmap.get("venues"),
                "liquidations": heatmap.get("liquidations"),
            },
            "ticker": ticker,
            "oracle_gap": data.get("oracle_gap"),
            "arbitrage_gap": data.get("arbitrage_gap"),
            "decay": data.get("decay"),
            "onchain": data.get("onchain_snapshot"),
        }

        hover_cards = [
            {
                "label": "Confidence",
                "value": round(result.confidence, 3),
                "detail": "Swarm-adjusted conviction after decay & funding effects.",
            },
            {
                "label": "Theta Decay",
                "value": {
                    "yes": (data.get("decay") or {}).get("yes"),
                    "no": (data.get("decay") or {}).get("no"),
                },
                "detail": "Time-to-resolution adjustments applied to both sides.",
            },
            {
                "label": "Funding Bias",
                "value": (data.get("decay") or {}).get("funding"),
                "detail": "Perp funding nudges confidence up/down.",
            },
        ]
        if intent.get("drivers"):
            hover_cards.extend(intent["drivers"])

        self._hover_metadata = {
            "timestamp": result.timestamp,
            "market": data.get("market"),
            "platforms": data.get("platforms"),
            "oracle_gap": data.get("oracle_gap"),
            "hover_cards": hover_cards,
            "explainability": explainability,
            "risk_flags": risk_flags,
            "funding_rate": data.get("funding_rate"),
            "hours_to_resolution": data.get("hours_to_resolution"),
        }

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    def _apply_confidence_decay_to_block_dict(self, block_dict: Dict[str, Any], block_index: int) -> Dict[str, Any]:
        decay_rate = self.confidence_decay_rate
        if decay_rate <= 0:
            return block_dict
        latest_index = self.chain[-1].index if self.chain else block_index
        age_blocks = max(0, latest_index - block_index)
        decay_factor = math.exp(-decay_rate * age_blocks)
        for sim_entry in block_dict.get("simulations", []):
            original_conf = float(sim_entry.get("confidence", 0.0))
            decayed_conf = original_conf * decay_factor
            sim_entry["decayed_confidence"] = decayed_conf
            data = sim_entry.setdefault("data", {})
            decay_section = data.get("decay", {}).copy()
            decay_section["confidence"] = {
                "decayed_confidence": decayed_conf,
                "original_confidence": original_conf,
                "age_blocks": age_blocks,
                "decay_factor": decay_factor,
            }
            data["decay"] = decay_section
        return block_dict

    def _apply_market_decay(self, probability: float, hours_to_resolution: float) -> Dict[str, Any]:
        half_life = max(1.0, self.features.theta_half_life_hours)
        horizon = max(0.0, hours_to_resolution)
        decay_factor = 0.5 ** (horizon / half_life)
        neutral = 0.5
        decayed = neutral + (probability - neutral) * decay_factor
        decayed = max(0.001, min(0.999, decayed))
        explanation = (
            f"Smoothed toward neutrality with decay factor {decay_factor:.3f} "
            f"over {horizon:.1f}h horizon (theta half-life {half_life:.1f}h)."
        )
        return {
            "original_probability": probability,
            "decayed_probability": decayed,
            "decay_factor": decay_factor,
            "half_life_hours": half_life,
            "horizon_hours": horizon,
            "explanation": explanation,
        }

    def _apply_funding_decay(
        self,
        confidence: float,
        funding_rate: float,
        hours_window: float,
    ) -> Dict[str, Any]:
        half_life = max(1.0, self.features.funding_half_life_hours)
        horizon = max(0.0, hours_window)
        decay_factor = 0.5 ** (horizon / half_life)
        funding_bias = funding_rate * (horizon / 24.0)
        adjustment = funding_bias * (1 - decay_factor)
        adjusted = max(self.features.confidence_floor, min(0.999, confidence + adjustment))
        bias_direction = "short_bias" if funding_rate > 0 else ("long_bias" if funding_rate < 0 else "neutral")
        explanation = (
            f"Funding rate {funding_rate:.4%} over {horizon:.1f}h nudged confidence by {adjustment:.4f} "
            f"({bias_direction}, half-life {half_life:.1f}h)."
        )
        return {
            "original_confidence": confidence,
            "adjusted_confidence": adjusted,
            "funding_rate": funding_rate,
            "decay_factor": decay_factor,
            "bias_direction": bias_direction,
            "adjustment": adjustment,
            "half_life_hours": half_life,
            "horizon_hours": horizon,
            "explanation": explanation,
        }

    def _build_perp_adapters(self) -> List[Any]:
        adapters = [
            HyperliquidAdapter(),
            BybitPerpAdapter(),
            BinancePerpAdapter(),
            CoinbasePerpAdapter(),
            CryptoComPerpAdapter(),
            DyDxPerpAdapter(),
            GMXPerpAdapter(),
            PerpetualProtocolAdapter(),
            DriftPerpAdapter(),
        ]
        return adapters
    
    def _propose_uma_assertion(self, market_slug: str, consensus_probability: float) -> Optional[str]:
        """Stage 4: Propose consensus to UMA Optimistic Oracle."""
        from simulation.uma_integration import propose_uma_assertion
        
        block_index = len(self.chain)
        confidence = self._last_consensus_resolution.confidence if self._last_consensus_resolution else 0.5
        
        return propose_uma_assertion(
            market_slug=market_slug,
            consensus_probability=consensus_probability,
            block_index=block_index,
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_simulation_chain(**kwargs: Any) -> MeridSimulationChain:
    client = kwargs.pop("trading_client", None) or PolymarketClient(use_mock=kwargs.pop("use_mock", False))
    features = kwargs.pop("features", None) or SimulationFeatureConfig.from_env()
    return MeridSimulationChain(trading_client=client, features=features, **kwargs)

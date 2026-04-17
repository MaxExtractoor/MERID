"""Enhanced Proof-of-Useful-Simulation (PoUS) engine for MERID.

This module builds a lightweight blockchain-style ledger for simulation blocks
that can be mined by swarm agents. Each block contains useful simulation
artifacts derived from real Polymarket market data (via the public Gamma API)
or from deterministic mocks when live data is unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from core.event_bus import event_stream
from utils.logger import get_logger
from trading.polymarket_trading_layer import ChainlinkOracle, PolymarketClient
from trading.augur_trading_layer import AugurTradingLayer
from monitoring.liquidation_monitor import CoinGlassLiquidationMonitor, WhaleIntelMonitor
from monitoring.news_agent import NewsSentinel, NewsItem
from monitoring.onchain_analytics import OnchainAnalyticsMonitor, OnchainSnapshot
from notifications.telegram_client import TelegramAlertClient
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

logger = get_logger("simulation.engine")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SimulationOutcome:
    outcome: str
    explanation: str
    weight: float
    votes: int
    final_explanation: str
    expected_value: float

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
        payload["outcomes"] = [o.to_dict() for o in self.outcomes]
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
        # Compare the Polymarket-implied probability with the oracle reference signal.
        implied_yes = yes_probability
        implied_no = no_probability
        implied_avg = (implied_yes + (1 - implied_no)) / 2
        return implied_avg - oracle_average

    def _generate_zk_proof(self, simulation: SimulationResult) -> str:
        if self.features.enable_zksnark:
            logger.debug(
                "zk-SNARK flag enabled — prover integration pending. Using placeholder hash.",
            )
        payload = f"{simulation.sim_id}:{simulation.confidence:.4f}:{len(simulation.outcomes)}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def _is_useful(self, simulation: SimulationResult) -> bool:
        if not simulation.outcomes:
            return False
        strongest = max(simulation.outcomes, key=lambda outcome: abs(outcome.expected_value))
        return abs(strongest.expected_value) >= self.usefulness_threshold

    def _publish_event(self, block: SimulationBlock) -> None:
        block_view = block.to_dict()
        block_view = self._apply_confidence_decay_to_block_dict(block_view, block.index)
        first_sim = block_view.get("simulations", [{}])[0] if block_view.get("simulations") else {}
        decay_meta = first_sim.get("data", {}).get("decay") if first_sim else None
        payload = {
            "height": block.index,
            "hash": block_view["hash"],
            "miner": block.miner,
            "markets": [sim.data.get("market") for sim in block.simulations],
            "confidence": first_sim.get("decayed_confidence")
            if first_sim
            else (block.simulations[0].confidence if block.simulations else 0.0),
            "oracle_gap": (block.simulations[0].data.get("oracle_gap") if block.simulations else None),
            "oracle_snapshot": (block.simulations[0].data.get("oracle_snapshot") if block.simulations else None),
            "decay": decay_meta,
            "intent": first_sim.get("data", {}).get("intent") if first_sim else None,
            "explainability": first_sim.get("data", {}).get("explainability") if first_sim else None,
        }
        self._dispatch_event(self.event_topic, payload)

    def _apply_confidence_decay_to_block_dict(self, block_dict: Dict[str, Any], block_index: int) -> Dict[str, Any]:
        if self.confidence_decay_rate <= 0:
            return block_dict

        latest_index = self.chain[-1].index if self.chain else block_index
        age_blocks = max(0, latest_index - block_index)
        decay_factor = math.exp(-self.confidence_decay_rate * age_blocks)

        simulations = block_dict.get("simulations", [])
        for sim_entry in simulations:
            original_conf = float(sim_entry.get("confidence", 0.0))
            decayed_conf = original_conf * decay_factor
            sim_entry["decayed_confidence"] = decayed_conf
            data = sim_entry.setdefault("data", {})
            decay_section = data.get("decay", {}).copy()
            confidence_section = decay_section.get("confidence", {})
            confidence_section.update(
                {
                    "decayed_confidence": decayed_conf / 100 if decayed_conf > 1 else decayed_conf,
                    "original_confidence": original_conf,
                    "age_blocks": age_blocks,
                    "decay_factor": decay_factor,
                }
            )
            decay_section["confidence"] = confidence_section
            # Legacy keys for backward compatibility
            decay_section.setdefault("decayed_confidence", confidence_section["decayed_confidence"])
            decay_section.setdefault("original_confidence", original_conf)
            decay_section.setdefault("age_blocks", age_blocks)
            data["decay"] = decay_section
        return block_dict

    def _apply_market_decay(self, probability: float, hours_to_resolution: float) -> Dict[str, Any]:
        half_life = max(1.0, self.features.theta_half_life_hours)
        horizon = max(0.0, hours_to_resolution)
        decay_factor = 0.5 ** (horizon / half_life)
        neutral_probability = 0.5
        decayed_probability = neutral_probability + (probability - neutral_probability) * decay_factor
        decayed_probability = min(0.999, max(0.001, decayed_probability))
        explanation = (
            f"Smoothed toward neutrality with decay factor {decay_factor:.3f} "
            f"over {horizon:.1f}h horizon (theta half-life {half_life:.1f}h)."
        )
        return {
            "original_probability": probability,
            "decayed_probability": decayed_probability,
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
        adjusted_confidence = min(0.995, max(0.005, confidence + adjustment))
        bias_direction = "short_bias" if funding_rate > 0 else ("long_bias" if funding_rate < 0 else "neutral")
        explanation = (
            f"Funding rate {funding_rate:.4%} over {horizon:.1f}h nudged confidence by {adjustment:.4f} "
            f"({bias_direction}, half-life {half_life:.1f}h)."
        )
        return {
            "original_confidence": confidence,
            "adjusted_confidence": adjusted_confidence,
            "funding_rate": funding_rate,
            "decay_factor": decay_factor,
            "bias_direction": bias_direction,
            "adjustment": adjustment,
            "half_life_hours": half_life,
            "horizon_hours": horizon,
            "explanation": explanation,
        }

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
        explain = {
            "market": market_slug,
            "platforms": platforms,
            "theta": theta,
            "funding": funding,
        }
        if oracle_gap is not None:
            explain["oracle_gap"] = {
                "value": oracle_gap,
                "explanation": f"Chainlink anchor differs by {oracle_gap:.4f}, dampening confidence accordingly.",
            }
        return explain


# Convenience factory --------------------------------------------------------

def build_simulation_chain(**kwargs: Any) -> MeridSimulationChain:
    """Create a configured simulation chain that other modules can import."""

    client = kwargs.pop("trading_client", None) or PolymarketClient(use_mock=kwargs.pop("use_mock", False))
    features = kwargs.pop("features", None)
    return MeridSimulationChain(trading_client=client, features=features, **kwargs)

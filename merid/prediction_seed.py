"""Prediction Market Seeder — registers Kalshi-style contracts and seeds
the matching engine with reference prices for continuous paper trading.

Usage:
  python -m merid.prediction_seed              # seed and print summary
  python -m merid.prediction_seed --simulate   # seed + run N simulated agent trades

This module:
  1. Registers a curated set of high-signal prediction contracts as InstrumentConfigs
  2. Seeds the matching engine with implied-probability reference prices
  3. Optionally simulates agent orderflow so the engine has realistic fill history

Contracts are modeled after real Kalshi event categories:
  - Macro/economic (Fed rate, GDP, CPI, unemployment)
  - Crypto (BTC/ETH price thresholds)
  - Politics (elections, legislation)
  - Weather/climate
  - Tech/AI milestones
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from utils.logger import get_logger
logger = get_logger("prediction_seed")

logger = get_logger(__name__)


# ── Contract definitions ─────────────────────────────────────────────

@dataclass
class SeedContract:
    """A prediction contract to register and seed."""
    id: str                          # e.g. "KXFED-MAR26-CUT-YES"
    question: str                    # Human-readable question
    category: str                    # macro, crypto, politics, weather, tech
    implied_prob: float              # Initial implied probability (0-1)
    expiry_label: str                # e.g. "2026-03-19"
    volume_hint: float = 1000.0      # Approximate daily volume in contracts
    tick_size: float = 0.01


# Curated high-signal contracts across categories
SEED_CONTRACTS: List[SeedContract] = [
    # ── Macro / Economic ──────────────────────────────────────────────
    SeedContract(
        id="KXFED-MAR26-CUT-YES",
        question="Will the Fed cut rates at the March 2026 FOMC meeting?",
        category="macro",
        implied_prob=0.35,
        expiry_label="2026-03-19",
    ),
    SeedContract(
        id="KXFED-JUN26-CUT-YES",
        question="Will the Fed cut rates at the June 2026 FOMC meeting?",
        category="macro",
        implied_prob=0.62,
        expiry_label="2026-06-17",
    ),
    SeedContract(
        id="KXCPI-FEB26-ABOVE3-YES",
        question="Will February 2026 CPI YoY be above 3.0%?",
        category="macro",
        implied_prob=0.28,
        expiry_label="2026-03-12",
    ),
    SeedContract(
        id="KXGDP-Q1-26-ABOVE2-YES",
        question="Will Q1 2026 GDP growth be above 2.0%?",
        category="macro",
        implied_prob=0.55,
        expiry_label="2026-04-30",
    ),
    SeedContract(
        id="KXUNEMP-MAR26-BELOW4-YES",
        question="Will March 2026 unemployment rate be below 4.0%?",
        category="macro",
        implied_prob=0.48,
        expiry_label="2026-04-04",
    ),

    # ── Crypto Price Thresholds ───────────────────────────────────────
    SeedContract(
        id="KXBTC-MAR26-100K-YES",
        question="Will BTC be above $100K on March 31, 2026?",
        category="crypto",
        implied_prob=0.58,
        expiry_label="2026-03-31",
    ),
    SeedContract(
        id="KXBTC-JUN26-150K-YES",
        question="Will BTC be above $150K on June 30, 2026?",
        category="crypto",
        implied_prob=0.22,
        expiry_label="2026-06-30",
    ),
    SeedContract(
        id="KXETH-MAR26-5K-YES",
        question="Will ETH be above $5K on March 31, 2026?",
        category="crypto",
        implied_prob=0.31,
        expiry_label="2026-03-31",
    ),
    SeedContract(
        id="KXSOL-MAR26-300-YES",
        question="Will SOL be above $300 on March 31, 2026?",
        category="crypto",
        implied_prob=0.40,
        expiry_label="2026-03-31",
    ),

    # ── Politics ──────────────────────────────────────────────────────
    SeedContract(
        id="KXGOV-SHUTDOWN-MAR26-YES",
        question="Will there be a US government shutdown before April 2026?",
        category="politics",
        implied_prob=0.25,
        expiry_label="2026-04-01",
    ),
    SeedContract(
        id="KXDEBT-CEILING-26-YES",
        question="Will the US debt ceiling be raised by June 2026?",
        category="politics",
        implied_prob=0.72,
        expiry_label="2026-06-30",
    ),

    # ── Weather / Climate ─────────────────────────────────────────────
    SeedContract(
        id="KXTEMP-NYC-MAR26-ABOVE55-YES",
        question="Will NYC avg temp in March 2026 be above 55°F?",
        category="weather",
        implied_prob=0.33,
        expiry_label="2026-03-31",
    ),
    SeedContract(
        id="KXHURRICANE-26-ABOVE15-YES",
        question="Will 2026 Atlantic hurricane season have >15 named storms?",
        category="weather",
        implied_prob=0.45,
        expiry_label="2026-11-30",
    ),

    # ── Tech / AI ─────────────────────────────────────────────────────
    SeedContract(
        id="KXAI-GPT5-H1-26-YES",
        question="Will OpenAI release GPT-5 in H1 2026?",
        category="tech",
        implied_prob=0.38,
        expiry_label="2026-06-30",
    ),
    SeedContract(
        id="KXTSLA-FSD-L4-26-YES",
        question="Will Tesla achieve SAE Level 4 autonomy approval in 2026?",
        category="tech",
        implied_prob=0.12,
        expiry_label="2026-12-31",
    ),
]


# ── Seeding logic ────────────────────────────────────────────────────

def seed_instruments() -> int:
    """Register all seed contracts as InstrumentConfigs.

    Returns the number of newly registered instruments.
    """
    # Production stack: skip instrument registration since paper_config doesn't exist
    # from merid.paper_config import InstrumentConfig, register_instrument, get_instrument
    logger.info("Skipping instrument registration - paper_config not available in production stack")
    return 0

    # registered = 0
    # for sc in SEED_CONTRACTS:
    #     if get_instrument(sc.id) is not None:
    #         continue  # Already registered
    #     register_instrument(InstrumentConfig(
    #         id=sc.id,
    #         domain="prediction",
    #         venues=["kalshi"],
    #         min_size=1.0,
    #         max_size=500.0,
    #         tick_size=sc.tick_size,
    #         max_leverage=1.0,
    #     ))
    #     registered += 1
    # 
    # logger.info(f"Registered {registered} new prediction instruments ({len(SEED_CONTRACTS)} total)")
    # return registered


def seed_reference_prices() -> Dict[str, float]:
    """Seed the matching engine with implied-probability reference prices.

    Returns dict of instrument_id -> reference price.
    """
    from merid.matching_engine import get_matching_engine

    engine = get_matching_engine("prediction")
    prices = {}
    for sc in SEED_CONTRACTS:
        engine.update_reference_price(sc.id, sc.implied_prob)
        prices[sc.id] = sc.implied_prob

    logger.info(f"Seeded {len(prices)} reference prices into prediction matching engine")
    return prices


def simulate_agent_trades(n_trades: int = 50) -> Dict[str, Any]:
    """Simulate agent orderflow against the seeded contracts.

    Generates realistic paper fills so the engine has fill history
    for metrics, Brier scoring, and agent fitness evaluation.

    Returns summary stats.
    """
    from merid.matching_engine import get_matching_engine, Order, OrderSide

    engine = get_matching_engine("prediction")
    if not engine.enabled:
        engine.enable()

    agent_ids = [
        "prediction-market-agent",
        "macro-research-agent",
        "crypto-signals-agent",
        "consensus-coordinator",
        "strategy-designer",
    ]

    fills = []
    for i in range(n_trades):
        sc = random.choice(SEED_CONTRACTS)
        agent = random.choice(agent_ids)

        # Agent decides direction based on whether they think prob is mispriced
        # Simulate: agent has a "true prob" estimate that differs from market
        agent_estimate = sc.implied_prob + random.gauss(0, 0.08)
        agent_estimate = max(0.02, min(0.98, agent_estimate))

        if agent_estimate > sc.implied_prob + 0.03:
            side = OrderSide.BUY
        elif agent_estimate < sc.implied_prob - 0.03:
            side = OrderSide.SELL
        else:
            continue  # No edge, skip

        notional = random.uniform(10.0, 100.0)

        order = Order(
            instrument_id=sc.id,
            side=side,
            notional_usd=round(notional, 2),
            domain="prediction",
            agent_id=agent,
            plan_id=f"sim-{i}-{sc.id[:10]}",
        )
        fill = engine.submit_order(order)
        if order.status.value == "filled":
            fills.append(fill)

    stats = engine.stats()
    by_agent = {}
    for f in fills:
        # Look up agent from the order
        order = engine.get_order(f.order_id)
        if order:
            aid = order.agent_id
            by_agent.setdefault(aid, {"fills": 0, "notional": 0.0})
            by_agent[aid]["fills"] += 1
            by_agent[aid]["notional"] += f.notional_usd

    by_category = {}
    for sc in SEED_CONTRACTS:
        cat_fills = engine.fills_for_instrument(sc.id)
        if cat_fills:
            by_category.setdefault(sc.category, {"contracts": 0, "fills": 0})
            by_category[sc.category]["contracts"] += 1
            by_category[sc.category]["fills"] += len(cat_fills)

    summary = {
        "total_trades_attempted": n_trades,
        "total_fills": len(fills),
        "total_notional_usd": round(sum(f.notional_usd for f in fills), 2),
        "by_agent": by_agent,
        "by_category": by_category,
        "engine_stats": stats,
    }

    logger.info(
        f"Simulated {len(fills)} fills across {len(SEED_CONTRACTS)} contracts, "
        f"${summary['total_notional_usd']:.0f} total notional"
    )
    return summary


def seed_all(simulate: bool = False, n_trades: int = 50) -> Dict[str, Any]:
    """Full seed: register instruments, set prices, optionally simulate trades.

    Returns a combined summary.
    """
    registered = seed_instruments()
    prices = seed_reference_prices()

    result = {
        "instruments_registered": registered,
        "reference_prices": prices,
        "contracts": [
            {
                "id": sc.id,
                "question": sc.question,
                "category": sc.category,
                "implied_prob": sc.implied_prob,
                "expiry": sc.expiry_label,
            }
            for sc in SEED_CONTRACTS
        ],
    }

    if simulate:
        result["simulation"] = simulate_agent_trades(n_trades)

    return result


def get_seed_contracts() -> List[SeedContract]:
    """Return the list of seed contracts for external consumption."""
    return list(SEED_CONTRACTS)


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    simulate = "--simulate" in sys.argv
    n_trades = 50

    if "--trades" in sys.argv:
        idx = sys.argv.index("--trades") + 1
        if idx < len(sys.argv):
            n_trades = int(sys.argv[idx])

    result = seed_all(simulate=simulate, n_trades=n_trades)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Prediction Market Seeder")
    logger.info(f"{'=' * 60}")
    logger.info(f"Contracts registered: {result['instruments_registered']} new / {len(SEED_CONTRACTS)} total")
    logger.info(f"\nContracts:")
    for c in result["contracts"]:
        logger.info(f"  {c['id']:40s}  {c['implied_prob']:.0%}  [{c['category']}]  exp={c['expiry']}")
        logger.info(f"    {c['question']}")
    if simulate and "simulation" in result:
        sim = result["simulation"]
        logger.info(f"\nSimulation:")
        logger.info(f"  Fills: {sim['total_fills']} / {sim['total_trades_attempted']} attempted")
        logger.info(f"  Notional: ${sim['total_notional_usd']:,.0f}")
        logger.info(f"\n  By Agent:")
        for agent, stats in sim["by_agent"].items():
            logger.info(f"    {agent:35s}  {stats['fills']:3d} fills  ${stats['notional']:,.0f}")
        logger.info(f"\n  By Category:")
        for cat, stats in sim["by_category"].items():
            logger.info(f"    {cat:15s}  {stats['contracts']:2d} contracts  {stats['fills']:3d} fills")
    logger.info(f"\n{'=' * 60}")
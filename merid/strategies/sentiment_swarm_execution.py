"""Swarm consensus → position plans over the 5×4 crypto grid (discover→size).

Uses :func:`config.kalshi_crypto_config.active_crypto_asset_mood_timeframe_grid`,
:class:`merid.swarm.consensus_aggregator.SwarmConsensusAggregator`, and
:class:`merid.event_venues.kalshi.crypto_catalog.KalshiCryptoCatalog`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, get_merid_swarm_confidence_min
from config.kalshi_crypto_config import active_crypto_asset_mood_timeframe_grid
from merid.event_venues.kalshi.crypto_catalog import KalshiCryptoCatalog
from merid.event_venues.kalshi.decision_trace import new_decision_trace_id
from merid.event_venues.kalshi.position_sizer import get_position_sizer
from merid.swarm.consensus_aggregator import ConsensusView, get_consensus_aggregator

logger = get_logger("merid.strategies.sentiment_swarm_execution")


@dataclass
class SwarmOrderPlan:
    """One sized candidate after swarm + sizer (not yet routed to Kalshi)."""

    asset: str
    timeframe: str
    market_ticker: str
    contracts: int
    consensus: ConsensusView
    edge_pct: float
    price_cents: int
    decision_trace_id: str
    swarm_score: float
    sentiment_driven: bool


def _consensus_to_edge_pct(view: ConsensusView) -> float:
    """Map consensus probability to a rough edge %% for the sizer."""
    p = float(view.consensus_probability)
    return abs(p - 0.5) * 200.0


def _direction_to_side(view: ConsensusView) -> str:
    if view.consensus_direction == "yes":
        return "yes"
    if view.consensus_direction == "no":
        return "no"
    return "yes"


def plan_swarm_orders_for_catalog(
    catalog: KalshiCryptoCatalog,
    *,
    bankroll_cents: int = 500_000,
    default_price_cents: int = 55,
    min_edge_pct: float = 0.5,
) -> List[SwarmOrderPlan]:
    """Build sized plans for each (asset, timeframe) on the mood grid.

    Skips pairs with no candidate tickers in *catalog*. Respects
    ``usable``, ``MERID_SWARM_CONFIDENCE_MIN``, and position sizer (which
    applies the same swarm floor when ``swarm_confidence`` is passed).
    """
    agg = get_consensus_aggregator()
    sizer = get_position_sizer()
    floor = get_merid_swarm_confidence_min()
    out: List[SwarmOrderPlan] = []

    for asset, timeframe in active_crypto_asset_mood_timeframe_grid():
        if asset not in ACTIVE_CRYPTO_ASSETS:
            continue
        view = agg.get_consensus_or_neutral(asset, timeframe)
        tickers = catalog.iter_tickers(asset, timeframe)
        if not tickers:
            continue
        market_ticker = tickers[0]
        trace = new_decision_trace_id("sw")

        edge = _consensus_to_edge_pct(view)
        if edge < min_edge_pct:
            edge = min_edge_pct

        swarm_score = float(view.consensus_probability - 0.5) * 2.0  # [-1,1]-ish

        if not view.usable:
            contracts = 0
        else:
            contracts = sizer.compute(
                agent_name=f"{asset}_{timeframe}_swarm",
                edge_pct=edge,
                price_cents=default_price_cents,
                bankroll_cents=bankroll_cents,
                sentiment_vol_asset=asset,
                is_contrarian=False,
                sentiment_timeframe=timeframe,
                market_ticker=market_ticker,
                swarm_score=swarm_score,
                swarm_confidence=float(view.consensus_confidence),
                decision_trace_id=trace,
            )

        driven = bool(
            view.usable
            and view.consensus_confidence >= floor
            and contracts > 0
        )

        out.append(
            SwarmOrderPlan(
                asset=asset,
                timeframe=timeframe,
                market_ticker=market_ticker,
                contracts=contracts,
                consensus=view,
                edge_pct=edge,
                price_cents=default_price_cents,
                decision_trace_id=trace,
                swarm_score=swarm_score,
                sentiment_driven=driven,
            )
        )

    logger.info(
        "[swarm-exec] planned %d grid cells (sentiment_driven=%d)",
        len(out),
        sum(1 for p in out if p.sentiment_driven),
    )
    return out


def summarize_cycle_for_logging(plans: List[SwarmOrderPlan]) -> Dict[str, Any]:
    """Compact dict for health / ops logs."""
    active = [p for p in plans if p.sentiment_driven]
    return {
        "cells_total": len(plans),
        "sentiment_active_cells": len(active),
        "assets_with_orders": sorted({p.asset for p in active}),
    }


def sentiment_exposure_by_asset(plans: List[SwarmOrderPlan]) -> Dict[str, int]:
    """Approximate contract exposure per asset from planned swarm sizes."""
    acc: Dict[str, int] = {a: 0 for a in ACTIVE_CRYPTO_ASSETS}
    for p in plans:
        if p.sentiment_driven:
            acc[p.asset] = acc.get(p.asset, 0) + p.contracts
    return acc

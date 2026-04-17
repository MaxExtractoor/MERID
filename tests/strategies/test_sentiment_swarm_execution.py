"""Swarm grid execution produces multi-asset plans (not BTC-only)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from merid.event_venues.kalshi.crypto_catalog import KalshiCryptoCatalog, KalshiMarketInfo
from merid.strategies.sentiment_swarm_execution import plan_swarm_orders_for_catalog
from merid.swarm.consensus_aggregator import (
    AgentProposal,
    ConsensusStatus,
    ConsensusView,
    SwarmConsensusAggregator,
    get_consensus_aggregator,
)


def _fake_catalog() -> KalshiCryptoCatalog:
    rows: list[KalshiMarketInfo] = []
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        rows.append(
            KalshiMarketInfo(
                ticker=f"KX{asset}15M-TEST",
                asset=asset,
                frequency="15M",
            )
        )
    return KalshiCryptoCatalog(rows)


def test_plan_swarm_nonzero_for_all_assets_at_15m_when_consensus_ready() -> None:
    """Synthetic READY consensus at 15m for all five assets → nonzero contracts each."""
    cat = _fake_catalog()
    agg: SwarmConsensusAggregator = get_consensus_aggregator()
    agg.clear_proposals()
    now = datetime.now(timezone.utc)

    arch = ("trend", "momentum")
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        for _i in range(2):
            agg.submit_proposal(
                AgentProposal(
                    agent_id=f"a{_i}-{asset}",
                    asset=asset,
                    timeframe="15m",
                    direction="yes",
                    probability=0.62,
                    confidence=0.75,
                    size_preference="base",
                    rationale="test",
                    edge_estimate=5.0,
                    timestamp=now,
                    agent_archetype=arch[_i % 2],
                )
            )

    with patch("merid.strategies.sentiment_swarm_execution.get_merid_swarm_confidence_min", return_value=0.1):
        plans = plan_swarm_orders_for_catalog(cat, bankroll_cents=500_000, min_edge_pct=0.01)

    by_asset = {p.asset: p for p in plans if p.timeframe == "15m"}
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        assert asset in by_asset, f"missing 15m plan for {asset}"
        p = by_asset[asset]
        assert p.contracts > 0, f"expected nonzero size for {asset}"
        assert p.decision_trace_id, "sentiment plan must carry decision_trace_id"
        assert p.decision_trace_id.startswith("sw-"), "swarm trace prefix"


def test_suspect_proposals_yield_neutral_usable_false() -> None:
    agg = SwarmConsensusAggregator()
    agg.clear_proposals()
    now = datetime.now(timezone.utc)
    key = "BTC:15m"
    agg._proposals[key] = [
        AgentProposal(
            agent_id="spam",
            asset="BTC",
            timeframe="15m",
            direction="yes",
            probability=0.9,
            confidence=0.99,
            size_preference="base",
            rationale="x",
            edge_estimate=1.0,
            timestamp=now,
            agent_archetype="trend",
            suspect=True,
        )
    ]
    view = agg._aggregate_proposals("BTC", "15m", agg._proposals[key])
    assert view.usable is False
    assert view.consensus_confidence == 0.0

"""Tests for multi-asset scanning and Kelly sizing.

Validates:
  - Per-asset scan: all 5 assets (BTC, ETH, SOL, XRP, DOGE) can be scanned
    and filtered into near-spot candidates.
  - Edge/Kelly computation: known edge produces positive kelly_raw and
    correct kelly_frac matching the configured Kelly fraction.
  - No BTC bias: when only ETH has edge, the trader considers ETH and
    not just BTC.
  - signal_to_sizing: edge_pct from MarketCandidate.edge_pct is used for
    Kelly sizing when present (priority over strategy edge).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from merid.event_venues.kalshi.market_filter import (
    MarketCandidate,
    MarketFilter,
    MarketFilterConfig,
    FilterResult,
)
from merid.prediction.opinion_strategy import (
    OpinionEstimate,
    OpinionStrategy,
)
from merid.trading.kalshi_continuous_trader import (
    KalshiContinuousTrader,
    TradingCandidate,
    SizingResult,
    _CRYPTO_ASSETS,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _market(
    ticker: str = "KXBTC-H-55-60",
    underlying: str = "BTC",
    timeframe: str = "15m",
    volume: int = 100,
    oi: int = 50,
    bid: int = 60,
    ask: int = 65,
    mid: int = 62,
    edge_pct: Optional[float] = None,
    model_prob: Optional[float] = None,
) -> MarketCandidate:
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        volume=volume,
        open_interest=oi,
        best_bid_cents=bid,
        best_ask_cents=ask,
        spread_cents=ask - bid if bid > 0 and ask > 0 else 0,
        mid_price_cents=mid,
        edge_pct=edge_pct,
        model_prob=model_prob,
    )


class _EdgeStrategy(OpinionStrategy):
    """Strategy that returns a fixed edge for any asset."""

    name = "fixed_edge"

    def __init__(self, edge: float = 0.10, agent_prob: float = 0.70, conf: float = 0.80):
        self._edge = edge
        self._agent_prob = agent_prob
        self._conf = conf

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        return OpinionEstimate(
            agent_prob=self._agent_prob,
            confidence=self._conf,
            edge=self._edge,
            reasoning_tag="fixed_edge",
            signal_sources=["test"],
        )


class _AssetAwareStrategy(OpinionStrategy):
    """Strategy that only returns edge for a specific asset."""

    name = "asset_aware"

    def __init__(self, target_asset: str = "ETH", edge: float = 0.10, conf: float = 0.80):
        self._target_asset = target_asset
        self._edge = edge
        self._conf = conf

    def estimate(
        self,
        agent_id: str,
        ticker: str,
        market_prob: float,
        category: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[OpinionEstimate]:
        # Only produce edge for the target asset
        if self._target_asset.upper() in ticker.upper():
            return OpinionEstimate(
                agent_prob=market_prob + self._edge,
                confidence=self._conf,
                edge=self._edge,
                reasoning_tag="asset_aware",
                signal_sources=["test"],
            )
        return None


def _make_trader(**kwargs) -> KalshiContinuousTrader:
    """Create a trader with a mock catalog."""
    catalog = MagicMock()
    catalog.get_markets_by_asset.return_value = []
    return KalshiContinuousTrader(catalog=catalog, **kwargs)


# ── 1. Per-asset scan tests ──────────────────────────────────────────────


class TestPerAssetScan:
    """Verify that _refresh_candidates iterates over all 5 assets."""

    def test_all_five_assets_in_crypto_assets(self):
        """_CRYPTO_ASSETS includes BTC, ETH, SOL, XRP, DOGE."""
        expected = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        assert set(_CRYPTO_ASSETS) == expected

    def test_filter_passes_all_five_assets(self):
        """MarketFilter with all underlyings allowed passes candidates for each asset."""
        cfg = MarketFilterConfig(
            allowed_underlyings=list(_CRYPTO_ASSETS),
            allowed_timeframes=["15m"],
        )
        filt = MarketFilter(cfg)

        for asset in _CRYPTO_ASSETS:
            candidate = _market(
                ticker=f"KX{asset}-15M-T100",
                underlying=asset,
                timeframe="15m",
            )
            passed, reason = filt.evaluate(candidate)
            assert passed, f"{asset} should pass filter but got: {reason}"

    def test_filter_does_not_reject_non_btc_assets(self):
        """Non-BTC assets pass through the same filter pipeline as BTC."""
        cfg = MarketFilterConfig(
            allowed_underlyings=list(_CRYPTO_ASSETS),
        )
        filt = MarketFilter(cfg)
        markets = [
            _market(ticker=f"KX{asset}-T100", underlying=asset)
            for asset in _CRYPTO_ASSETS
        ]
        result = filt.filter_markets(markets)
        passed_assets = {c.underlying for c in result.candidates}
        assert passed_assets == set(_CRYPTO_ASSETS), (
            f"Expected all 5 assets to pass, got: {passed_assets}"
        )

    def test_per_asset_cap_applies_to_each_asset(self):
        """Per-asset cap is applied independently to each underlying."""
        cfg = MarketFilterConfig(
            allowed_underlyings=list(_CRYPTO_ASSETS),
            max_candidates_per_asset=1,
        )
        filt = MarketFilter(cfg)
        markets = []
        for asset in _CRYPTO_ASSETS:
            for i in range(3):
                markets.append(_market(
                    ticker=f"KX{asset}-{i}",
                    underlying=asset,
                ))
        result = filt.filter_markets(markets)
        # Each asset should have at most 1 candidate
        for asset in _CRYPTO_ASSETS:
            asset_candidates = [c for c in result.candidates if c.underlying == asset]
            assert len(asset_candidates) <= 1, (
                f"{asset} has {len(asset_candidates)} candidates, expected ≤ 1"
            )
        # All 5 assets should be represented
        assert len({c.underlying for c in result.candidates}) == 5


# ── 2. Edge/Kelly computation tests ──────────────────────────────────────


class TestEdgeKelly:
    """Verify signal_to_sizing produces correct Kelly from known edge."""

    def test_positive_edge_yields_positive_kelly(self):
        """A candidate with edge_pct > 0 should produce kelly_raw > 0."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.01)
        candidate = TradingCandidate.from_candidate(
            _market(mid=40, edge_pct=8.0)  # 8% edge
        )
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.edge > 0, f"Expected positive edge, got {sizing.edge}"
        assert sizing.kelly_raw > 0, f"Expected positive kelly_raw, got {sizing.kelly_raw}"
        assert sizing.kelly_frac > 0, f"Expected positive kelly_frac, got {sizing.kelly_frac}"
        assert sizing.source == "signal"

    def test_kelly_frac_matches_configured_fraction(self):
        """kelly_frac = kelly_raw * kelly_fraction."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.01)
        candidate = TradingCandidate.from_candidate(
            _market(mid=40, edge_pct=10.0)  # 10% edge
        )
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.kelly_frac == pytest.approx(sizing.kelly_raw * 0.25, abs=1e-6)

    def test_zero_edge_yields_zero_kelly(self):
        """A candidate with edge_pct = 0 should produce kelly_raw = 0."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.02)
        candidate = TradingCandidate.from_candidate(_market(mid=50))
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.kelly_frac == 0.0

    def test_negative_edge_yields_zero_kelly(self):
        """Negative edge should not produce a trade."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.02)
        candidate = TradingCandidate.from_candidate(
            _market(mid=50, edge_pct=-5.0)
        )
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.kelly_frac == 0.0
        assert sizing.size_contracts == 0

    def test_edge_below_min_edge_threshold_yields_zero(self):
        """Edge below min_edge threshold is treated as no-trade."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.05)
        candidate = TradingCandidate.from_candidate(
            _market(mid=40, edge_pct=3.0)  # 3% edge < 5% min_edge
        )
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.size_contracts == 0

    def test_signal_edge_takes_priority_over_strategy(self):
        """edge_pct from signal takes priority over strategy-computed edge."""
        strategy = _EdgeStrategy(edge=0.05)
        trader = _make_trader(strategy=strategy, kelly_fraction=0.25, min_edge=0.01)
        # Signal says 12% edge
        candidate = TradingCandidate.from_candidate(
            _market(mid=40, edge_pct=12.0)
        )
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.source == "signal"
        # edge_pct is 12% = 0.12 as fraction
        assert sizing.edge == pytest.approx(0.12, abs=0.01)

    def test_strategy_edge_used_when_no_signal(self):
        """When edge_pct is None, strategy edge is used."""
        strategy = _EdgeStrategy(edge=0.10)
        trader = _make_trader(strategy=strategy, kelly_fraction=0.25, min_edge=0.01)
        candidate = TradingCandidate.from_candidate(
            _market(mid=40, edge_pct=None)  # No signal edge
        )
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.source == "strategy"
        assert sizing.edge == pytest.approx(0.10, abs=0.01)

    def test_size_contracts_is_positive_with_edge(self):
        """A candidate with real edge should produce positive contract count."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.01)
        candidate = TradingCandidate.from_candidate(
            _market(mid=40, edge_pct=10.0)
        )
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.size_contracts > 0
        assert sizing.notional_usd > 0


# ── 3. No BTC bias tests ────────────────────────────────────────────────


class TestNoBtcBias:
    """Verify that non-BTC assets are treated identically to BTC."""

    def test_eth_only_edge_produces_intent(self):
        """When only ETH has edge, the trader produces an ETH intent."""
        strategy = _AssetAwareStrategy(target_asset="ETH", edge=0.10, conf=0.80)
        trader = _make_trader(strategy=strategy, max_yes_price=0.99, min_edge=0.01)

        # Set up candidates: BTC (no edge via strategy) and ETH (with edge)
        btc_candidate = TradingCandidate.from_candidate(
            _market(ticker="KXBTC-15M-T1", underlying="BTC", mid=40)
        )
        eth_candidate = TradingCandidate.from_candidate(
            _market(ticker="KXETH-15M-T1", underlying="ETH", mid=40)
        )
        trader._candidates = [btc_candidate, eth_candidate]

        intents = asyncio.get_event_loop().run_until_complete(
            trader.trade_cycle(bankroll=1000.0)
        )
        eth_intents = [i for i in intents if i["underlying"] == "ETH"]
        assert len(eth_intents) >= 1, "ETH intent should be generated when ETH has edge"

    def test_sol_xrp_doge_candidates_survive_filter(self):
        """SOL, XRP, DOGE candidates pass the same filter as BTC."""
        cfg = MarketFilterConfig(
            allowed_underlyings=list(_CRYPTO_ASSETS),
            allowed_timeframes=["15m"],
        )
        filt = MarketFilter(cfg)
        for asset in ("SOL", "XRP", "DOGE"):
            m = _market(ticker=f"KX{asset}-15M-T100", underlying=asset)
            passed, reason = filt.evaluate(m)
            assert passed, f"{asset} rejected: {reason}"

    def test_all_assets_can_have_positive_kelly(self):
        """Each of the 5 assets can produce positive Kelly from signal edge."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.01)

        for asset in _CRYPTO_ASSETS:
            candidate = TradingCandidate.from_candidate(
                _market(
                    ticker=f"KX{asset}-15M-T100",
                    underlying=asset,
                    mid=40,
                    edge_pct=8.0,
                )
            )
            sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
            assert sizing.kelly_raw > 0, f"{asset}: expected positive kelly_raw"
            assert sizing.size_contracts > 0, f"{asset}: expected positive size"

    def test_non_btc_intents_include_asset_info(self):
        """Trade intents for non-BTC assets include correct underlying."""
        strategy = _EdgeStrategy(edge=0.10, conf=0.80)
        trader = _make_trader(strategy=strategy, max_yes_price=0.99, min_edge=0.01)

        for asset in ("ETH", "SOL", "XRP", "DOGE"):
            candidate = TradingCandidate.from_candidate(
                _market(ticker=f"KX{asset}-15M-T1", underlying=asset, mid=40)
            )
            trader._candidates = [candidate]
            intents = asyncio.get_event_loop().run_until_complete(
                trader.trade_cycle(bankroll=1000.0)
            )
            trader.reset_daily()
            assert len(intents) >= 1, f"No intent for {asset}"
            assert intents[0]["underlying"] == asset


# ── 4. MarketCandidate enrichment fields ─────────────────────────────────


class TestCandidateEnrichment:
    """Verify edge_pct and model_prob carry through the pipeline."""

    def test_edge_pct_in_to_dict(self):
        """to_dict() includes edge_pct and model_prob."""
        m = _market(edge_pct=5.0, model_prob=0.62)
        d = m.to_dict()
        assert d["edge_pct"] == 5.0
        assert d["model_prob"] == 0.62

    def test_edge_pct_none_by_default(self):
        """edge_pct defaults to None."""
        m = _market()
        assert m.edge_pct is None
        assert m.model_prob is None

    def test_trading_candidate_preserves_edge_pct(self):
        """TradingCandidate.from_candidate preserves edge_pct."""
        base = _market(edge_pct=7.5, model_prob=0.65)
        tc = TradingCandidate.from_candidate(base)
        assert tc.edge_pct == 7.5
        assert tc.model_prob == 0.65

    def test_getattr_fallback_for_edge_pct(self):
        """Legacy instances without edge_pct don't crash."""
        m = MarketCandidate(ticker="test", underlying="BTC", timeframe="15m")
        # edge_pct is a declared field, so it's always present.
        # But __getattr__ handles it for legacy pickled objects
        assert m.edge_pct is None


# ── 5. SizingResult dataclass ────────────────────────────────────────────


class TestSizingResult:
    """Verify SizingResult fields and defaults."""

    def test_defaults(self):
        sr = SizingResult()
        assert sr.edge == 0.0
        assert sr.win_prob == 0.5
        assert sr.kelly_raw == 0.0
        assert sr.kelly_frac == 0.0
        assert sr.size_contracts == 0
        assert sr.source == "none"

    def test_custom_values(self):
        sr = SizingResult(
            edge=0.08, win_prob=0.58, payout_cents=50.0,
            kelly_raw=0.16, kelly_frac=0.04, size_contracts=10,
            notional_usd=20.0, source="signal",
        )
        assert sr.edge == 0.08
        assert sr.size_contracts == 10
        assert sr.source == "signal"


# ── 6. Status includes Kelly config ─────────────────────────────────────


class TestStatusIncludesKellyConfig:
    def test_status_has_kelly_fraction(self):
        trader = _make_trader(kelly_fraction=0.30)
        s = trader.status()
        assert s["config"]["kelly_fraction"] == 0.30

    def test_status_has_min_edge(self):
        trader = _make_trader(min_edge=0.05)
        s = trader.status()
        assert s["config"]["min_edge"] == 0.05

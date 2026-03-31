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
  - Invariants: negative edge / sub-threshold edge always → 0 contracts;
    intent["edge"] is always the same value as sizing.edge (living spec).
"""

from __future__ import annotations

import asyncio
import math
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

        intents = asyncio.run(trader.trade_cycle(bankroll=1000.0))
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
            intents = asyncio.run(trader.trade_cycle(bankroll=1000.0))
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


# ── 7. Kelly edge invariants (living spec) ──────────────────────────────────
#
# These tests document the exact no-trade policy for the sizing layer and the
# intent faithfulness invariant.  They should be kept close to the logic they
# guard so future refactors produce an obvious diff rather than a silent break.


class TestEdgeInvariants:
    """Invariant: negative or sub-threshold edges always produce 0 contracts.

    Design contract being asserted:
      - edge <= 0        →  size_contracts == 0  (Kelly says don't bet)
      - 0 < edge < min_edge  →  size_contracts == 0  (noise filter)
      - edge == min_edge →  size_contracts  > 0  (boundary: condition is strict '<', equality trades)
      - edge > min_edge  →  size_contracts  > 0  (normal trade)
    """

    def test_negative_edge_yields_zero_contracts(self):
        """Any negative edge → zero contracts regardless of magnitude."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.02)
        for neg_edge in (-0.50, -0.10, -0.02, -0.001, -1e-9):
            candidate = TradingCandidate.from_candidate(
                _market(mid=40, edge_pct=neg_edge * 100)
            )
            sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
            assert sizing.size_contracts == 0, (
                f"edge={neg_edge}: expected 0 contracts, got {sizing.size_contracts}"
            )
            assert sizing.edge == pytest.approx(neg_edge, abs=1e-9), (
                f"edge={neg_edge}: sizing.edge should preserve the raw edge value"
            )

    def test_zero_edge_yields_zero_contracts(self):
        """Zero edge → zero contracts (no bet when there is no advantage)."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.02)
        candidate = TradingCandidate.from_candidate(_market(mid=50, edge_pct=0.0))
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.size_contracts == 0
        assert sizing.kelly_frac == 0.0

    def test_edge_below_min_edge_yields_zero_contracts(self):
        """Edge in (0, min_edge) → zero contracts (noise filter blocks tiny edges)."""
        min_edge = 0.05  # 5%
        trader = _make_trader(kelly_fraction=0.25, min_edge=min_edge)
        for tiny_edge_pct in (0.1, 1.0, 2.5, 4.9):  # all < 5% min_edge
            candidate = TradingCandidate.from_candidate(
                _market(mid=40, edge_pct=tiny_edge_pct)
            )
            sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
            assert sizing.size_contracts == 0, (
                f"edge_pct={tiny_edge_pct}%: expected 0 contracts below min_edge={min_edge}"
            )

    def test_edge_exactly_at_min_edge_yields_positive_contracts(self):
        """edge == min_edge IS tradeable — condition is strictly 'edge < min_edge'."""
        min_edge = 0.05
        trader = _make_trader(kelly_fraction=0.25, min_edge=min_edge)
        # edge_pct=5.0 → edge=0.05 exactly equals min_edge
        # The guard is: if edge < min_edge → no trade
        # So edge == min_edge passes the guard and produces contracts.
        candidate = TradingCandidate.from_candidate(_market(mid=40, edge_pct=5.0))
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.size_contracts > 0, (
            "edge exactly equal to min_edge should produce contracts "
            "(condition is strict 'edge < min_edge', so equality allows trading)"
        )

    def test_edge_above_min_edge_yields_positive_contracts(self):
        """The first edge strictly above min_edge should produce >0 contracts."""
        min_edge = 0.05
        trader = _make_trader(kelly_fraction=0.25, min_edge=min_edge)
        # edge_pct=5.1 → edge=0.051 > 0.05 = min_edge
        candidate = TradingCandidate.from_candidate(_market(mid=40, edge_pct=5.1))
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        assert sizing.size_contracts > 0, (
            "edge just above min_edge should produce at least 1 contract"
        )
        assert sizing.kelly_frac > 0.0

    def test_negative_edge_via_edge_override(self):
        """edge_override with negative value still produces 0 contracts."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.02)
        candidate = TradingCandidate.from_candidate(_market(mid=40))
        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0, edge_override=-0.15)
        assert sizing.size_contracts == 0
        assert sizing.edge == pytest.approx(-0.15, abs=1e-9)
        assert sizing.source == "override"

    def test_size_contracts_never_negative(self):
        """size_contracts is always >= 0 for any edge input."""
        trader = _make_trader(kelly_fraction=0.25, min_edge=0.02)
        for edge_pct in (-50.0, -5.0, 0.0, 1.0, 5.0, 20.0):
            candidate = TradingCandidate.from_candidate(
                _market(mid=40, edge_pct=edge_pct)
            )
            sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
            assert sizing.size_contracts >= 0, (
                f"edge_pct={edge_pct}: size_contracts must never be negative"
            )

    def test_kelly_frac_never_exceeds_configured_fraction(self):
        """kelly_frac = kelly_raw * fraction; raw Kelly can't exceed 1.0 in normal range."""
        kelly_fraction = 0.25
        trader = _make_trader(kelly_fraction=kelly_fraction, min_edge=0.02)
        # Very large edge to stress-test ceiling
        for edge_pct in (5.0, 20.0, 50.0, 99.0):
            candidate = TradingCandidate.from_candidate(
                _market(mid=40, edge_pct=edge_pct)
            )
            sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
            assert sizing.kelly_frac <= kelly_fraction, (
                f"kelly_frac={sizing.kelly_frac} exceeds configured "
                f"kelly_fraction={kelly_fraction}"
            )
            assert not math.isnan(sizing.kelly_frac), (
                "kelly_frac must not be NaN"
            )


class TestIntentEdgeFaithfulness:
    """Invariant: intent['edge'] is always == sizing.edge.

    This is the single-truth property: the edge value displayed/logged/stored
    in the intent must be exactly the edge the Kelly engine used.  A mismatch
    would mean the audit trail is misleading.
    """

    def _make_trader_with_strategy(self, edge_val: float, **kwargs) -> KalshiContinuousTrader:
        """Trader wired with a fixed-edge strategy."""
        class _Fixed(OpinionStrategy):
            name = "fixed"
            def estimate(self, agent_id, ticker, market_prob, category="", context=None):
                return OpinionEstimate(
                    agent_prob=market_prob + edge_val,
                    confidence=0.80,
                    edge=edge_val,
                    reasoning_tag="fixed",
                    signal_sources=["test"],
                )
        return _make_trader(strategy=_Fixed(), max_yes_price=0.99, min_edge=0.01, **kwargs)

    def test_intent_edge_equals_sizing_edge_for_positive_edge(self):
        """When edge > min_edge, intent['edge'] == sizing.edge == the positive edge."""
        trader = self._make_trader_with_strategy(edge_val=0.10)
        candidate = TradingCandidate.from_candidate(
            _market(ticker="KXBTC-T1", underlying="BTC", mid=40, edge_pct=None)
        )
        trader._candidates = [candidate]

        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        intents = asyncio.run(trader.trade_cycle(bankroll=1000.0))

        assert len(intents) >= 1, "Expected at least one intent"
        intent = intents[0]
        assert intent["edge"] == sizing.edge, (
            f"intent['edge']={intent['edge']} != sizing.edge={sizing.edge}"
        )
        assert intent["size_contracts"] == sizing.size_contracts

    def test_intent_edge_equals_sizing_edge_for_negative_signal_edge(self):
        """When candidate has negative edge_pct, intent['edge'] == sizing.edge (negative)."""
        # Strategy provides positive confidence so an intent is generated,
        # but the signal edge (negative) is what drives sizing.
        class _HighConf(OpinionStrategy):
            name = "high_conf"
            def estimate(self, agent_id, ticker, market_prob, category="", context=None):
                return OpinionEstimate(
                    agent_prob=0.70,
                    confidence=0.80,
                    edge=0.10,  # strategy edge — but signal takes priority
                    reasoning_tag="high_conf",
                    signal_sources=["test"],
                )

        trader = _make_trader(
            strategy=_HighConf(),
            max_yes_price=0.99,
            min_edge=0.02,
        )
        candidate = TradingCandidate.from_candidate(
            _market(ticker="KXBTC-T1", underlying="BTC", mid=40, edge_pct=-5.0)
        )
        trader._candidates = [candidate]

        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        intents = asyncio.run(trader.trade_cycle(bankroll=1000.0))

        # An intent is generated (risk checks pass via bankroll_fraction),
        # but the edge in the intent must reflect the actual sizing edge.
        assert len(intents) >= 1, "Expected at least one intent (confidence passes)"
        intent = intents[0]
        assert intent["edge"] == sizing.edge, (
            f"intent['edge']={intent['edge']} != sizing.edge={sizing.edge}"
        )
        # Contracts should be 0 — Kelly doesn't size on a negative edge
        assert intent["size_contracts"] == 0, (
            "Negative edge should produce 0 contracts in the intent"
        )

    def test_intent_edge_equals_sizing_edge_for_sub_threshold_edge(self):
        """When 0 < edge < min_edge, intent['edge'] == sizing.edge and contracts==0."""
        class _LowConf(OpinionStrategy):
            name = "low_conf"
            def estimate(self, agent_id, ticker, market_prob, category="", context=None):
                return OpinionEstimate(
                    agent_prob=0.65,
                    confidence=0.80,
                    edge=0.05,  # strategy edge — but signal takes priority
                    reasoning_tag="low_conf",
                    signal_sources=["test"],
                )

        min_edge = 0.05  # 5%
        trader = _make_trader(
            strategy=_LowConf(),
            max_yes_price=0.99,
            min_edge=min_edge,
        )
        # Signal edge is 3% — above zero but below min_edge threshold
        candidate = TradingCandidate.from_candidate(
            _market(ticker="KXBTC-T1", underlying="BTC", mid=40, edge_pct=3.0)
        )
        trader._candidates = [candidate]

        sizing = trader.signal_to_sizing(candidate, bankroll=1000.0)
        intents = asyncio.run(trader.trade_cycle(bankroll=1000.0))

        assert len(intents) >= 1, "Expected at least one intent"
        intent = intents[0]
        assert intent["edge"] == sizing.edge, (
            f"intent['edge']={intent['edge']} != sizing.edge={sizing.edge}"
        )
        assert intent["size_contracts"] == 0, (
            f"Edge {sizing.edge} < min_edge {min_edge}: contracts must be 0"
        )

    def test_intent_edge_is_always_finite(self):
        """intent['edge'] must never be NaN or Inf for any valid edge input."""
        trader = self._make_trader_with_strategy(edge_val=0.10)
        for edge_pct in (-50.0, -0.1, 0.0, 0.5, 10.0, 99.0):
            candidate = TradingCandidate.from_candidate(
                _market(ticker="KXBTC-T1", underlying="BTC", mid=40, edge_pct=edge_pct)
            )
            trader._candidates = [candidate]
            trader.reset_daily()
            intents = asyncio.run(trader.trade_cycle(bankroll=1000.0))
            for intent in intents:
                edge_val = intent["edge"]
                assert not math.isnan(edge_val), (
                    f"intent['edge'] is NaN for edge_pct={edge_pct}"
                )
                assert abs(edge_val) < 1e9, (
                    f"intent['edge']={edge_val} is unreasonably large for edge_pct={edge_pct}"
                )

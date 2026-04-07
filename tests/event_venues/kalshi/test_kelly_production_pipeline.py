"""Production Kelly pipeline certification tests.

Validates the invariants required for live-ready Kelly sizing:

1. Non-zero kelly_raw and kelly_frac for synthetic positive edge on all 5 assets
   × 3 representative timeframes (15m, 1h, daily).
2. Contract size is proportional to bankroll and edge magnitude.
3. No path forces size to a fixed tiny number when edge is real (no micro-size
   hacks survive to production).
4. End-to-end non-BTC 15m candidate (DISCOVER→SIZE) produces size > 0 when edge
   exceeds the admission threshold.
5. Sigma-distance attenuation: near-spot strikes produce larger edge/confidence
   than far-out-of-the-money strikes at the same raw signal strength.
6. Aggregate crypto-risk cap (MERID_TOTAL_CRYPTO_RISK_PCT) blocks subsequent
   intents once the cycle-wide notional budget is exhausted.
7. Per-cell Kelly fraction loaded from catalog overrides global default.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.event_venues.kalshi.market_filter import MarketCandidate, MarketFilterConfig
from merid.event_venues.kalshi.strategy_grid import (
    SpotMomentumStrategy,
    _sigma_attenuation,
)
from merid.prediction.opinion_strategy import OpinionEstimate, OpinionStrategy
from merid.trading.kalshi_continuous_trader import (
    KalshiContinuousTrader,
    TradingCandidate,
    SizingResult,
    _CRYPTO_ASSETS,
    _CATALOG_KELLY_FRACTION,
    _CATALOG_MAX_RISK_PCT,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_candidate(
    ticker: str = "KXBTC-H-55-60",
    underlying: str = "BTC",
    timeframe: str = "15m",
    bid: int = 40,
    ask: int = 45,
    mid: int = 42,
    volume: int = 200,
    oi: int = 50,
    edge_pct: Optional[float] = None,
    strike_price: Optional[float] = None,
    spot_price: Optional[float] = None,
    expiry_ts: float = 0.0,
) -> MarketCandidate:
    return MarketCandidate(
        ticker=ticker,
        underlying=underlying,
        timeframe=timeframe,
        volume=volume,
        open_interest=oi,
        best_bid_cents=bid,
        best_ask_cents=ask,
        spread_cents=ask - bid,
        mid_price_cents=mid,
        edge_pct=edge_pct,
        strike_price=strike_price,
        spot_price=spot_price,
        expiry_ts=expiry_ts,
    )


def _make_trader(
    max_group_notional: float = 10_000.0,
    kelly_fraction: float = 0.25,
    bankroll_fraction: float = 0.02,
    min_confidence: float = 0.50,
) -> KalshiContinuousTrader:
    """Build a dry-run CT with generous caps so sizing is never blocked by risk."""
    with patch("merid.trading.kalshi_continuous_trader._assert_kalshi_credentials_present"):
        return KalshiContinuousTrader(
            catalog=MagicMock(),
            strategy=None,
            max_group_notional=max_group_notional,
            kelly_fraction=kelly_fraction,
            bankroll_fraction=bankroll_fraction,
            min_confidence=min_confidence,
            dry_run=True,
        )


class _FixedEdgeStrategy(OpinionStrategy):
    """Returns a fixed edge for any ticker, regardless of asset/timeframe."""

    name = "fixed_edge_test"

    def __init__(self, edge: float = 0.10, agent_prob: float = 0.65, conf: float = 0.80):
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
            reasoning_tag="fixed_edge_test",
            signal_sources=["fixed"],
        )


# ── Test 1: Kelly arithmetic for all 5 assets × 3 timeframes ─────────────

ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
TIMEFRAMES = ["15m", "1h", "daily"]

_ASSET_TF_PAIRS = [(a, tf) for a in ASSETS for tf in TIMEFRAMES]


@pytest.mark.parametrize("asset,timeframe", _ASSET_TF_PAIRS)
def test_positive_edge_produces_nonzero_kelly(asset: str, timeframe: str) -> None:
    """For any (asset, timeframe) with real edge, kelly_raw > 0 and kelly_frac > 0."""
    trader = _make_trader()
    candidate = TradingCandidate.from_candidate(
        _make_candidate(
            ticker=f"KX{asset}-H-100-110",
            underlying=asset,
            timeframe=timeframe,
            bid=40, ask=45, mid=42,
        )
    )
    # Inject edge directly via edge_pct (simulates model signal)
    candidate.edge_pct = 8.0  # 8% edge

    result = trader.signal_to_sizing(candidate, bankroll=10_000.0)

    assert result.kelly_raw > 0, (
        f"Expected kelly_raw > 0 for {asset}/{timeframe} with 8% edge, got {result.kelly_raw}"
    )
    assert result.kelly_frac > 0, (
        f"Expected kelly_frac > 0 for {asset}/{timeframe} with 8% edge, got {result.kelly_frac}"
    )
    assert result.size_contracts > 0, (
        f"Expected size_contracts > 0 for {asset}/{timeframe} with 8% edge on $10k bankroll, "
        f"got {result.size_contracts} (notional={result.notional_usd:.4f})"
    )


@pytest.mark.parametrize("asset,timeframe", _ASSET_TF_PAIRS)
def test_size_proportional_to_bankroll(asset: str, timeframe: str) -> None:
    """Contract size scales with bankroll: 10× larger bankroll → ~10× more contracts."""
    trader = _make_trader()
    candidate = TradingCandidate.from_candidate(
        _make_candidate(underlying=asset, timeframe=timeframe, mid=45)
    )
    candidate.edge_pct = 6.0

    small = trader.signal_to_sizing(candidate, bankroll=1_000.0)
    large = trader.signal_to_sizing(candidate, bankroll=10_000.0)

    assert large.notional_usd > small.notional_usd, (
        f"{asset}/{timeframe}: larger bankroll should give larger notional"
    )
    # Ratio should be approximately 10× (within 20% tolerance)
    ratio = large.notional_usd / max(small.notional_usd, 1e-9)
    assert 8.0 < ratio < 12.0, (
        f"{asset}/{timeframe}: notional ratio (10k/1k bankroll) expected ~10, got {ratio:.2f}"
    )


@pytest.mark.parametrize("asset,timeframe", _ASSET_TF_PAIRS)
def test_higher_edge_gives_larger_size(asset: str, timeframe: str) -> None:
    """Higher edge → larger kelly_raw → larger notional."""
    trader = _make_trader()
    candidate_lo = TradingCandidate.from_candidate(
        _make_candidate(underlying=asset, timeframe=timeframe, mid=45)
    )
    candidate_hi = TradingCandidate.from_candidate(
        _make_candidate(underlying=asset, timeframe=timeframe, mid=45)
    )
    candidate_lo.edge_pct = 4.0
    candidate_hi.edge_pct = 10.0

    result_lo = trader.signal_to_sizing(candidate_lo, bankroll=10_000.0)
    result_hi = trader.signal_to_sizing(candidate_hi, bankroll=10_000.0)

    assert result_hi.kelly_raw > result_lo.kelly_raw, (
        f"{asset}/{timeframe}: 10% edge should give larger kelly_raw than 4% edge"
    )
    assert result_hi.notional_usd > result_lo.notional_usd, (
        f"{asset}/{timeframe}: 10% edge should give larger notional than 4% edge"
    )


# ── Test 2: Zero / negative edge → zero size ─────────────────────────────

@pytest.mark.parametrize("asset", ASSETS)
def test_zero_edge_produces_zero_size(asset: str) -> None:
    """edge_pct = 0 must yield size_contracts = 0 for all assets."""
    trader = _make_trader()
    candidate = TradingCandidate.from_candidate(
        _make_candidate(underlying=asset, timeframe="15m", mid=45)
    )
    candidate.edge_pct = 0.0

    result = trader.signal_to_sizing(candidate, bankroll=10_000.0)
    assert result.size_contracts == 0, (
        f"{asset}: zero edge should give zero contracts, got {result.size_contracts}"
    )


@pytest.mark.parametrize("asset", ASSETS)
def test_negative_edge_produces_zero_size(asset: str) -> None:
    """Negative edge must always yield size_contracts = 0."""
    trader = _make_trader()
    candidate = TradingCandidate.from_candidate(
        _make_candidate(underlying=asset, timeframe="1h", mid=45)
    )
    candidate.edge_pct = -5.0  # negative edge

    result = trader.signal_to_sizing(candidate, bankroll=10_000.0)
    assert result.size_contracts == 0, (
        f"{asset}: negative edge should give zero contracts, got {result.size_contracts}"
    )


# ── Test 3: End-to-end non-BTC 15m candidate through DISCOVER→SIZE ────────

@pytest.mark.parametrize("asset", ["ETH", "SOL", "XRP", "DOGE"])
def test_non_btc_15m_end_to_end_positive_size(asset: str) -> None:
    """Non-BTC 15m candidate with real edge produces size > 0 end-to-end."""
    trader = _make_trader(bankroll_fraction=0.05)
    trader._strategy = _FixedEdgeStrategy(edge=0.10, agent_prob=0.65, conf=0.80)

    candidate = TradingCandidate.from_candidate(
        _make_candidate(
            ticker=f"KX{asset}-15m-TEST",
            underlying=asset,
            timeframe="15m",
            bid=38, ask=43, mid=40,
            volume=200,
            oi=50,
        )
    )

    async def _run():
        with patch.object(trader, "_refresh_candidates", new=AsyncMock()):
            trader._candidates = [candidate]
            return await trader.trade_cycle(bankroll=10_000.0)

    intents = asyncio.run(_run())

    assert len(intents) > 0, (
        f"{asset}/15m: expected at least one intent with 10% edge on $10k bankroll, "
        f"got 0 intents"
    )
    intent = intents[0]
    assert intent["size_contracts"] > 0, (
        f"{asset}/15m: intent size_contracts should be > 0, got {intent['size_contracts']}"
    )
    assert intent["edge"] > 0, (
        f"{asset}/15m: intent edge should be > 0, got {intent['edge']}"
    )


# ── Test 4: Sigma-distance attenuation ────────────────────────────────────

def test_sigma_attenuation_at_the_money() -> None:
    """Strike at spot (d=0) → attenuation factor = 1.0 (no penalty)."""
    factor = _sigma_attenuation(
        asset="BTC", timeframe="1h",
        strike_price=50_000.0, spot_price=50_000.0,
    )
    assert factor == pytest.approx(1.0, abs=1e-6), (
        f"ATM strike should have attenuation=1.0, got {factor}"
    )


def test_sigma_attenuation_far_otm() -> None:
    """Strike far from spot (large |d|) → attenuation factor < 0.5."""
    # Strike is 50% away from spot with typical vol — very far OTM
    factor = _sigma_attenuation(
        asset="BTC", timeframe="daily",
        strike_price=75_000.0, spot_price=50_000.0,  # 50% above spot
        implied_vol_annual=0.75,
    )
    assert factor < 0.5, (
        f"Far-OTM strike should have attenuation < 0.5, got {factor}"
    )


def test_sigma_attenuation_near_vs_far() -> None:
    """Near-spot strikes attenuate less than far-OTM strikes."""
    spot = 50_000.0
    # Use daily timeframe + explicit vol so sigma_T is large enough to distinguish
    near = _sigma_attenuation(
        "BTC", "daily", strike_price=51_000.0, spot_price=spot,
        implied_vol_annual=0.75,
    )
    far = _sigma_attenuation(
        "BTC", "daily", strike_price=70_000.0, spot_price=spot,
        implied_vol_annual=0.75,
    )
    assert near > far, (
        f"Near-spot (51k) attenuation={near:.4f} should exceed far-OTM (70k) "
        f"attenuation={far:.4f}"
    )


def test_sigma_attenuation_missing_data_returns_one() -> None:
    """Missing strike or spot price → factor = 1.0 (no attenuation)."""
    assert _sigma_attenuation("BTC", "1h", None, None) == pytest.approx(1.0)
    assert _sigma_attenuation("BTC", "1h", 50_000.0, None) == pytest.approx(1.0)
    assert _sigma_attenuation("BTC", "1h", None, 50_000.0) == pytest.approx(1.0)


def test_sigma_attenuation_identical_across_assets() -> None:
    """Same log-moneyness produces same attenuation regardless of asset."""
    # All assets: strike 10% above spot, same vol and timeframe
    factors = [
        _sigma_attenuation(
            asset, "daily",
            strike_price=55_000.0, spot_price=50_000.0,
            implied_vol_annual=0.80,
        )
        for asset in ASSETS
    ]
    # All should be the same since we pass implied_vol_annual explicitly
    assert all(f == pytest.approx(factors[0], abs=1e-6) for f in factors), (
        f"Same log-moneyness with same vol should give same attenuation across assets: {factors}"
    )


def test_strategy_grid_applies_attenuation() -> None:
    """SpotMomentumStrategy near-spot produces larger edge than far-OTM same signal."""
    strategy = SpotMomentumStrategy()

    base_ctx = {
        "asset": "BTC", "timeframe": "1h",
        "volume": 200.0, "open_interest": 100.0,
        "spot_return_pct": 3.0,
        "orderbook_imbalance": 0.3,
        "spot_price": 50_000.0,
        "implied_vol_annual": 0.75,
    }

    # Near-the-money
    near_ctx = dict(base_ctx, strike_price=50_500.0)
    # Far OTM
    far_ctx = dict(base_ctx, strike_price=70_000.0)

    est_near = strategy.estimate("test", "KXBTC-near", 0.45, context=near_ctx)
    est_far = strategy.estimate("test", "KXBTC-far", 0.45, context=far_ctx)

    # Near should produce a real estimate; far may be below min_edge
    assert est_near is not None, "Near-spot strike should produce an estimate"
    if est_far is not None:
        assert abs(est_near.edge) >= abs(est_far.edge), (
            f"Near-spot |edge|={abs(est_near.edge):.4f} should be >= far-OTM "
            f"|edge|={abs(est_far.edge):.4f}"
        )


# ── Test 5: Aggregate crypto risk cap ─────────────────────────────────────

def test_total_crypto_risk_cap_blocks_excess() -> None:
    """Once cycle-wide notional exceeds MERID_TOTAL_CRYPTO_RISK_PCT × bankroll,
    further intents are vetoed with 'total_crypto_risk_cap'."""
    trader = _make_trader(bankroll_fraction=0.20, max_group_notional=100_000.0)
    trader._strategy = _FixedEdgeStrategy(edge=0.15, agent_prob=0.70, conf=0.85)

    candidates = [
        TradingCandidate.from_candidate(
            _make_candidate(ticker=f"KXBTC-H-{i}", underlying="BTC", timeframe="1h",
                            bid=38, ask=43, mid=40, volume=200, oi=50)
        )
        for i in range(5)
    ]

    async def _run():
        with patch.object(trader, "_refresh_candidates", new=AsyncMock()):
            trader._candidates = candidates
            # Patch out catalog max_risk overrides so bankroll_fraction (20%) drives notional.
            # Patch total_crypto_risk_cap to 1% = $10 (tiny) so first trade hits it.
            with patch(
                "merid.trading.kalshi_continuous_trader._TOTAL_CRYPTO_RISK_PCT", 0.01
            ), patch(
                "merid.trading.kalshi_continuous_trader._CATALOG_MAX_RISK_PCT", {}
            ):
                return await trader.trade_cycle(bankroll=1_000.0)

    asyncio.run(_run())

    cycle_stats = trader._last_cycle_stats
    total_crypto_cap_vetoes = cycle_stats.get("vetoed_by_reason", {}).get(
        "total_crypto_risk_cap", 0
    )
    assert total_crypto_cap_vetoes > 0, (
        "Expected at least one veto by total_crypto_risk_cap when cap is 1% of $1000=$10"
    )


# ── Test 6: Catalog Kelly fraction is applied ──────────────────────────────

def test_catalog_kelly_fraction_loaded() -> None:
    """_CATALOG_KELLY_FRACTION should be non-empty (catalog loaded successfully)."""
    assert len(_CATALOG_KELLY_FRACTION) > 0, (
        "CATALOG_KELLY_FRACTION should contain at least one entry from the catalog"
    )


def test_catalog_kelly_fraction_used_in_sizing() -> None:
    """signal_to_sizing uses per-cell catalog Kelly fraction when available."""
    trader = _make_trader(kelly_fraction=0.25)

    # Find a cell that has a catalog Kelly fraction different from the global default.
    cell_key = None
    catalog_kf = None
    for key, kf in _CATALOG_KELLY_FRACTION.items():
        if kf != 0.25:
            cell_key = key
            catalog_kf = kf
            break

    if cell_key is None:
        pytest.skip("All catalog Kelly fractions equal global default; nothing to distinguish")

    asset, tf = cell_key
    candidate = TradingCandidate.from_candidate(
        _make_candidate(underlying=asset, timeframe=tf, mid=45)
    )
    candidate.edge_pct = 8.0

    result = trader.signal_to_sizing(candidate, bankroll=10_000.0)

    # kelly_frac should equal kelly_raw * catalog_kf (not kelly_raw * 0.25 if different)
    expected_kelly_frac = result.kelly_raw * catalog_kf
    assert result.kelly_frac == pytest.approx(expected_kelly_frac, abs=1e-6), (
        f"For {asset}/{tf}: expected kelly_frac={expected_kelly_frac:.6f} "
        f"(catalog kf={catalog_kf}), got {result.kelly_frac:.6f}"
    )


def test_catalog_max_risk_pct_loaded() -> None:
    """_CATALOG_MAX_RISK_PCT should be non-empty (catalog loaded successfully)."""
    assert len(_CATALOG_MAX_RISK_PCT) > 0, (
        "CATALOG_MAX_RISK_PCT should contain at least one entry from the catalog"
    )


def test_catalog_max_risk_pct_as_fraction() -> None:
    """Catalog max_risk_per_trade_pct values should be stored as fractions (0-1),
    not as percentages (0-100)."""
    for key, val in _CATALOG_MAX_RISK_PCT.items():
        assert 0 < val <= 1.0, (
            f"_CATALOG_MAX_RISK_PCT[{key}]={val} should be a fraction (0-1), "
            "not a percentage (0-100)"
        )


# ── Test 7: No micro-size sentinels in CT constants ───────────────────────

def test_no_hardcoded_tiny_size_constants() -> None:
    """Verify that CT module has no fixed contract-count sentinels (1, 2, 3, 5)
    that would hard-limit sizes regardless of Kelly."""
    import inspect
    import merid.trading.kalshi_continuous_trader as ct_module

    source = inspect.getsource(ct_module)

    # These patterns indicate a hard micro-size floor/cap (outside comments/strings).
    # We accept CANARY_NOTIONAL and MIN_VIABLE_NOTIONAL which are legitimate.
    forbidden_patterns = [
        "max_size = 1",
        "max_size=1",
        "size = 1",
        "size=1",
        "size_contracts = 1",
        "min_contracts = 1",
        "TEST_SIZE",
        "SAFE_SIZE",
        "SMOKE_SIZE",
        "MICRO_SIZE",
        "TINY_SIZE",
    ]
    for pat in forbidden_patterns:
        assert pat not in source, (
            f"Found forbidden micro-size sentinel pattern {pat!r} in CT source. "
            "Remove testing-mode size overrides."
        )

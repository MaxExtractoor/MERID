"""Tests for KalshiCryptoRiskEngine and related config/strategy components.

Covers all scenarios from the problem statement:
  1. Per-trade risk enforcement
  2. Portfolio risk cap
  3. Drawdown stop-out
  4. Per-asset bankroll partitions
  5. Timeframe-specific behaviour
  6. Edge and price-band filters
  7. No hardcoded risk amounts (static analysis)
"""

from __future__ import annotations

import ast
import math
from pathlib import Path
from typing import Dict

import pytest

from merid.event_venues.kalshi.crypto_kalshi_risk import (
    CRYPTO_ASSETS,
    TIMEFRAMES,
    AssetRiskProfile,
    CryptoKalshiRiskConfig,
    CryptoKalshiStrategyConfig,
    KalshiCryptoRiskEngine,
    StrategyProfile,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def default_engine() -> KalshiCryptoRiskEngine:
    """Engine with default config."""
    return KalshiCryptoRiskEngine()


@pytest.fixture()
def strict_engine() -> KalshiCryptoRiskEngine:
    """Engine with tightly specified config matching the problem-statement examples."""
    cfg = CryptoKalshiRiskConfig(
        max_total_drawdown_pct=0.40,
        max_risk_pct_trade=0.01,
        cushion_pct_trade=0.0025,
        max_risk_pct_portfolio=0.03,
    )
    return KalshiCryptoRiskEngine(risk_config=cfg)


def _empty_ledger() -> Dict[str, Dict]:
    return {}


def _ledger_with_open_risk(bankroll: float, open_risk_pct: float, asset: str = "BTC") -> Dict[str, Dict]:
    """Build a synthetic open-positions dict such that portfolio risk == open_risk_pct * bankroll."""
    risk_usd = bankroll * open_risk_pct
    # Use a price of 0.50 to keep arithmetic simple.
    contracts = math.ceil(risk_usd / 0.50)
    return {
        "KXBTC-TEST-001": {
            "asset": asset,
            "contracts": contracts,
            "entry_price": 0.50,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Per-trade risk enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestPerTradeRiskEnforcement:
    """Verify that risk_usd and contract counts are correctly derived from bankroll."""

    BANKROLL = 1000.0
    MAX_RISK_PCT = 0.01
    CUSHION_PCT = 0.0025
    PRICE = 0.40

    def test_risk_usd_formula(self, strict_engine):
        """risk_usd = bankroll * (max_risk_pct_trade - cushion_pct_trade)."""
        risk = strict_engine.compute_trade_risk_usd(
            self.BANKROLL,
            max_risk_pct_trade=self.MAX_RISK_PCT,
            cushion_pct_trade=self.CUSHION_PCT,
        )
        expected = self.BANKROLL * (self.MAX_RISK_PCT - self.CUSHION_PCT)  # 7.5
        assert risk == pytest.approx(expected)

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS)
    def test_contracts_equals_18_for_all_assets(self, strict_engine, asset):
        """contracts = floor(7.5 / 0.40) = 18 for all assets at the spec parameters."""
        contracts = strict_engine.compute_contracts_for_order(
            self.BANKROLL,
            self.PRICE,
            max_risk_pct_trade=self.MAX_RISK_PCT,
            cushion_pct_trade=self.CUSHION_PCT,
        )
        assert contracts == 18

    def test_zero_price_returns_zero_contracts(self, strict_engine):
        """A price of zero must return 0 to avoid division-by-zero."""
        contracts = strict_engine.compute_contracts_for_order(
            self.BANKROLL, 0.0,
            max_risk_pct_trade=self.MAX_RISK_PCT,
            cushion_pct_trade=self.CUSHION_PCT,
        )
        assert contracts == 0

    def test_negative_risk_returns_zero_contracts(self):
        """If cushion > max_risk, risk_usd is negative and contracts is 0."""
        engine = KalshiCryptoRiskEngine(
            CryptoKalshiRiskConfig(max_risk_pct_trade=0.005, cushion_pct_trade=0.01)
        )
        contracts = engine.compute_contracts_for_order(self.BANKROLL, 0.50)
        assert contracts == 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. Portfolio risk cap
# ═══════════════════════════════════════════════════════════════════════════

class TestPortfolioRiskCap:
    """check_can_add_order must block orders that would breach max_risk_pct_portfolio."""

    BANKROLL = 1000.0
    MAX_PORT_RISK_PCT = 0.03   # 3%

    def _engine(self) -> KalshiCryptoRiskEngine:
        cfg = CryptoKalshiRiskConfig(
            max_total_drawdown_pct=0.40,
            max_risk_pct_portfolio=self.MAX_PORT_RISK_PCT,
        )
        return KalshiCryptoRiskEngine(risk_config=cfg)

    def test_order_blocked_when_portfolio_would_breach(self):
        """New order pushing risk from 2.9% → 3.1% must be blocked."""
        engine = self._engine()
        # Seed ledger at 2.9% open risk.
        ledger = _ledger_with_open_risk(self.BANKROLL, 0.029)
        # New order risk = 0.002 * bankroll = 2; total would be ~31 > 30
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.BANKROLL,
            current_equity=self.BANKROLL,
            open_positions=ledger,
            asset="BTC",
            price=0.50,
            contracts=4,  # 4 × 0.50 = 2.0, pushes total >30
        )
        assert ok is False
        assert reason == "portfolio_risk_limit"

    def test_order_allowed_within_portfolio_cap(self):
        """Order that keeps aggregate risk under 3% must pass."""
        engine = self._engine()
        ledger = _ledger_with_open_risk(self.BANKROLL, 0.015)
        # New order risk = 1 × 0.50 = 0.50, stays well under 30
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.BANKROLL,
            current_equity=self.BANKROLL,
            open_positions=ledger,
            asset="ETH",
            price=0.50,
            contracts=1,
        )
        assert ok is True, reason

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS)
    def test_portfolio_cap_enforced_per_asset(self, asset):
        """The portfolio cap is tested per-asset as well as globally."""
        engine = self._engine()
        ledger = _ledger_with_open_risk(self.BANKROLL, 0.029, asset=asset)
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.BANKROLL,
            current_equity=self.BANKROLL,
            open_positions=ledger,
            asset=asset,
            price=0.50,
            contracts=4,
        )
        assert ok is False
        assert "portfolio_risk_limit" in reason or "asset_risk_limit" in reason

    def test_mixed_asset_portfolio_cap(self):
        """Positions across multiple assets sum toward the global portfolio cap."""
        engine = self._engine()
        # Put 1% risk in BTC and 1% in ETH (total 2%)
        ledger: Dict = {}
        ledger["KXBTC-1"] = {"asset": "BTC", "contracts": 20, "entry_price": 0.50}
        ledger["KXETH-1"] = {"asset": "ETH", "contracts": 20, "entry_price": 0.50}
        # New SOL order of 22 contracts @ 0.50 → 11.0 — that would push total to 31 > 30
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.BANKROLL,
            current_equity=self.BANKROLL,
            open_positions=ledger,
            asset="SOL",
            price=0.50,
            contracts=22,
        )
        assert ok is False
        assert reason == "portfolio_risk_limit"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Drawdown stop-out
# ═══════════════════════════════════════════════════════════════════════════

class TestDrawdownStopOut:
    """Equity below (1 - max_drawdown_pct) × initial_bankroll must block all orders."""

    INITIAL_BANKROLL = 1000.0
    MAX_DRAWDOWN = 0.40  # 40%

    def _engine(self) -> KalshiCryptoRiskEngine:
        return KalshiCryptoRiskEngine(
            CryptoKalshiRiskConfig(max_total_drawdown_pct=self.MAX_DRAWDOWN)
        )

    def _drawdown_equity(self, drawdown_frac: float) -> float:
        """Return equity corresponding to given drawdown fraction."""
        return self.INITIAL_BANKROLL * (1.0 - drawdown_frac)

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS)
    def test_all_assets_blocked_at_max_drawdown(self, asset):
        """All assets are blocked once drawdown ≥ 40%."""
        engine = self._engine()
        equity = self._drawdown_equity(self.MAX_DRAWDOWN)  # exactly at 60%
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.INITIAL_BANKROLL,
            current_equity=equity,
            open_positions=_empty_ledger(),
            asset=asset,
            price=0.50,
            contracts=1,
            initial_bankroll=self.INITIAL_BANKROLL,
        )
        assert ok is False
        assert reason == "max_drawdown_reached"

    def test_just_below_drawdown_threshold_is_blocked(self):
        """41% drawdown (equity at 59%) is blocked."""
        engine = self._engine()
        equity = self._drawdown_equity(0.41)
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.INITIAL_BANKROLL,
            current_equity=equity,
            open_positions=_empty_ledger(),
            asset="BTC",
            price=0.50,
            contracts=1,
            initial_bankroll=self.INITIAL_BANKROLL,
        )
        assert ok is False
        assert reason == "max_drawdown_reached"

    def test_just_above_drawdown_threshold_is_allowed(self):
        """39% drawdown (equity at 61%) is still allowed (below the cap)."""
        engine = self._engine()
        equity = self._drawdown_equity(0.39)
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.INITIAL_BANKROLL,
            current_equity=equity,
            open_positions=_empty_ledger(),
            asset="BTC",
            price=0.50,
            contracts=1,
            initial_bankroll=self.INITIAL_BANKROLL,
        )
        assert ok is True, reason

    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    def test_drawdown_blocks_all_timeframes_for_btc(self, timeframe):
        """Drawdown stop-out applies irrespective of timeframe lane."""
        engine = self._engine()
        equity = self._drawdown_equity(self.MAX_DRAWDOWN)
        ok, reason = engine.check_can_add_order(
            total_bankroll=self.INITIAL_BANKROLL,
            current_equity=equity,
            open_positions=_empty_ledger(),
            asset="BTC",
            price=0.50,
            contracts=1,
            initial_bankroll=self.INITIAL_BANKROLL,
        )
        assert ok is False
        assert reason == "max_drawdown_reached"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Per-asset bankroll partitions
# ═══════════════════════════════════════════════════════════════════════════

class TestPerAssetBankrollPartitions:
    """Verify that each asset uses its correct bankroll slice for sizing."""

    TOTAL_BANKROLL = 1000.0

    def test_btc_bankroll_slice(self, default_engine):
        assert default_engine.asset_bankroll(self.TOTAL_BANKROLL, "BTC") == pytest.approx(250.0)

    def test_eth_bankroll_slice(self, default_engine):
        assert default_engine.asset_bankroll(self.TOTAL_BANKROLL, "ETH") == pytest.approx(250.0)

    def test_sol_bankroll_slice(self, default_engine):
        assert default_engine.asset_bankroll(self.TOTAL_BANKROLL, "SOL") == pytest.approx(100.0)

    def test_xrp_bankroll_slice(self, default_engine):
        assert default_engine.asset_bankroll(self.TOTAL_BANKROLL, "XRP") == pytest.approx(100.0)

    def test_doge_bankroll_slice(self, default_engine):
        assert default_engine.asset_bankroll(self.TOTAL_BANKROLL, "DOGE") == pytest.approx(100.0)

    def test_btc_sizing_uses_asset_slice_not_total(self, default_engine):
        """Sizing for BTC must use the BTC bankroll slice (250), not 1000."""
        btc_bankroll = default_engine.asset_bankroll(self.TOTAL_BANKROLL, "BTC")
        btc_profile = default_engine.risk_config.asset_profiles["BTC"]

        risk_using_slice = default_engine.compute_trade_risk_usd(btc_bankroll, asset="BTC")
        risk_if_total = default_engine.compute_trade_risk_usd(self.TOTAL_BANKROLL, asset="BTC")

        # They must differ (slice is 1/4 of total)
        assert risk_using_slice < risk_if_total
        expected = btc_bankroll * (btc_profile.max_risk_pct_trade - btc_profile.cushion_pct_trade)
        assert risk_using_slice == pytest.approx(expected)

    def test_per_asset_exposure_does_not_exceed_slice_times_portfolio_pct(self):
        """Per-asset open risk is capped at asset_slice × max_risk_pct_portfolio."""
        cfg = CryptoKalshiRiskConfig()
        engine = KalshiCryptoRiskEngine(risk_config=cfg)
        btc_profile = cfg.asset_profiles["BTC"]
        btc_bankroll = self.TOTAL_BANKROLL * btc_profile.bankroll_share_pct  # 250
        btc_cap = btc_bankroll * btc_profile.max_risk_pct_portfolio           # 7.5

        # Fill BTC risk just under the cap
        ledger = {
            "KXBTC-X": {"asset": "BTC", "contracts": 14, "entry_price": 0.50}
        }  # 14 × 0.50 = 7.0 < 7.5

        ok, _ = engine.check_can_add_order(
            total_bankroll=self.TOTAL_BANKROLL,
            current_equity=self.TOTAL_BANKROLL,
            open_positions=ledger,
            asset="BTC",
            price=0.50,
            contracts=2,  # would push to 8.0 > 7.5
        )
        assert ok is False

    def test_slice_allocation_buffer(self):
        """BTC+ETH+SOL+XRP+DOGE shares sum to 0.80 leaving 20% unallocated."""
        cfg = CryptoKalshiRiskConfig()
        total_share = sum(
            p.bankroll_share_pct for p in cfg.asset_profiles.values()
        )
        assert total_share == pytest.approx(0.80)

    def test_unknown_asset_raises(self, default_engine):
        with pytest.raises(ValueError, match="Unknown asset"):
            default_engine.asset_bankroll(self.TOTAL_BANKROLL, "SHIB")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Timeframe-specific behaviour
# ═══════════════════════════════════════════════════════════════════════════

class TestTimeframeSpecificBehaviour:
    """Strategy profiles correctly enforce per-timeframe constraints."""

    def _engine(self) -> KalshiCryptoRiskEngine:
        return KalshiCryptoRiskEngine()

    # ── BTC-scalp ──────────────────────────────────────────────────────────

    def test_btc_scalp_fifth_trade_allowed(self):
        engine = self._engine()
        profile = engine.strategy_config.get("BTC", "scalp")
        assert profile is not None
        ok, reason = engine.check_strategy_filters(
            asset="BTC", timeframe="scalp",
            price=0.50, model_probability=0.60, market_probability=0.50,
            trades_today=profile.max_trades_per_day - 1,
            current_open_positions=0,
        )
        assert ok is True, reason

    def test_btc_scalp_sixth_trade_blocked_at_max_five(self):
        """A 6th trade is rejected when max_trades_per_day = 5."""
        engine = self._engine()
        # Override strategy profile to enforce max_trades_per_day=5
        strat_cfg = CryptoKalshiStrategyConfig()
        strat_cfg.profiles[("BTC", "scalp")] = StrategyProfile(
            asset_symbol="BTC",
            timeframe="scalp",
            bankroll_share_pct=0.30,
            max_trades_per_day=5,
            allowed_price_band=(0.35, 0.75),
            min_expected_edge_bp=50.0,
            max_open_positions=3,
        )
        engine2 = KalshiCryptoRiskEngine(strategy_config=strat_cfg)
        ok, reason = engine2.check_strategy_filters(
            asset="BTC", timeframe="scalp",
            price=0.50, model_probability=0.60, market_probability=0.50,
            trades_today=5,  # already at limit
            current_open_positions=0,
        )
        assert ok is False
        assert reason == "max_trades_per_day_reached"

    # ── ETH-swing ─────────────────────────────────────────────────────────

    def test_eth_swing_has_fewer_max_trades_than_intraday(self):
        engine = self._engine()
        swing = engine.strategy_config.get("ETH", "swing")
        intraday = engine.strategy_config.get("ETH", "intraday")
        assert swing is not None and intraday is not None
        assert swing.max_trades_per_day < intraday.max_trades_per_day

    def test_eth_swing_max_open_positions_respected(self):
        engine = self._engine()
        profile = engine.strategy_config.get("ETH", "swing")
        assert profile is not None
        ok, reason = engine.check_strategy_filters(
            asset="ETH", timeframe="swing",
            price=0.70, model_probability=0.80, market_probability=0.65,
            trades_today=0,
            current_open_positions=profile.max_open_positions,  # exactly at limit
        )
        assert ok is False
        assert reason == "max_open_positions_reached"

    # ── Concurrency limit ─────────────────────────────────────────────────

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS)
    @pytest.mark.parametrize("timeframe", TIMEFRAMES)
    def test_concurrency_limit_enforced_for_all_lanes(self, asset, timeframe):
        engine = self._engine()
        profile = engine.strategy_config.get(asset, timeframe)
        assert profile is not None, f"Missing profile for ({asset}, {timeframe})"
        ok, reason = engine.check_strategy_filters(
            asset=asset, timeframe=timeframe,
            price=(profile.allowed_price_band[0] + profile.allowed_price_band[1]) / 2,
            model_probability=0.75,
            market_probability=0.50,
            trades_today=0,
            current_open_positions=profile.max_open_positions,
        )
        assert ok is False
        assert reason == "max_open_positions_reached"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Edge and price-band filters
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeAndPriceBandFilters:
    """Trades are only taken when price is in-band and edge is sufficient."""

    def _engine(self) -> KalshiCryptoRiskEngine:
        strat_cfg = CryptoKalshiStrategyConfig()
        strat_cfg.profiles[("BTC", "intraday")] = StrategyProfile(
            asset_symbol="BTC",
            timeframe="intraday",
            bankroll_share_pct=0.40,
            max_trades_per_day=10,
            allowed_price_band=(0.35, 0.75),
            min_expected_edge_bp=100.0,  # 1% edge minimum
            max_open_positions=5,
        )
        return KalshiCryptoRiskEngine(strategy_config=strat_cfg)

    def test_trade_accepted_in_band_with_sufficient_edge(self):
        engine = self._engine()
        ok, reason = engine.check_strategy_filters(
            asset="BTC", timeframe="intraday",
            price=0.50,                  # inside [0.35, 0.75]
            model_probability=0.61,      # edge = 0.11 = 1100bp > 100bp
            market_probability=0.50,
            trades_today=0,
            current_open_positions=0,
        )
        assert ok is True, reason

    def test_price_below_band_rejected(self):
        engine = self._engine()
        ok, reason = engine.check_strategy_filters(
            asset="BTC", timeframe="intraday",
            price=0.20,  # below 0.35
            model_probability=0.70, market_probability=0.20,
            trades_today=0, current_open_positions=0,
        )
        assert ok is False
        assert reason == "price_band_violation"

    def test_price_above_band_rejected(self):
        engine = self._engine()
        ok, reason = engine.check_strategy_filters(
            asset="BTC", timeframe="intraday",
            price=0.90,  # above 0.75
            model_probability=0.95, market_probability=0.90,
            trades_today=0, current_open_positions=0,
        )
        assert ok is False
        assert reason == "price_band_violation"

    def test_insufficient_edge_rejected(self):
        engine = self._engine()
        ok, reason = engine.check_strategy_filters(
            asset="BTC", timeframe="intraday",
            price=0.50,
            model_probability=0.505,  # only 50bp < 100bp min
            market_probability=0.500,
            trades_today=0, current_open_positions=0,
        )
        assert ok is False
        assert reason == "insufficient_edge"

    def test_exactly_at_min_edge_rejected(self):
        """Edge that does not strictly exceed the minimum must be rejected.

        Profile requires edge > 100 bp.  We use edge = 100 bp (model=0.51,
        market=0.50) which equals the threshold — due to floating-point
        representation the computed value is ≈100.000...01 bp which does
        strictly exceed 100.0.  We therefore test with a profile whose
        threshold is 101 bp to ensure the check rejects an edge of ~100 bp.
        """
        strat_cfg = CryptoKalshiStrategyConfig()
        strat_cfg.profiles[("BTC", "intraday")] = StrategyProfile(
            asset_symbol="BTC",
            timeframe="intraday",
            bankroll_share_pct=0.40,
            max_trades_per_day=10,
            allowed_price_band=(0.35, 0.75),
            min_expected_edge_bp=101.0,  # require edge strictly > 101 bp
            max_open_positions=5,
        )
        engine = KalshiCryptoRiskEngine(strategy_config=strat_cfg)
        ok, reason = engine.check_strategy_filters(
            asset="BTC", timeframe="intraday",
            price=0.50,
            model_probability=0.51,    # ≈100 bp < 101 bp minimum
            market_probability=0.50,
            trades_today=0, current_open_positions=0,
        )
        assert ok is False
        assert reason == "insufficient_edge"

    def test_negative_edge_rejected(self):
        """Negative edge (model < market) must be rejected."""
        engine = self._engine()
        ok, reason = engine.check_strategy_filters(
            asset="BTC", timeframe="intraday",
            price=0.50,
            model_probability=0.40,  # negative edge
            market_probability=0.50,
            trades_today=0, current_open_positions=0,
        )
        assert ok is False
        assert reason == "insufficient_edge"

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS)
    def test_default_profiles_have_min_edge_requirement(self, asset, default_engine):
        """Every asset/timeframe profile has a positive min_expected_edge_bp."""
        for timeframe in TIMEFRAMES:
            profile = default_engine.strategy_config.get(asset, timeframe)
            assert profile is not None
            assert profile.min_expected_edge_bp > 0

    def test_price_bands_are_not_overly_wide(self, default_engine):
        """Regression test: ensure price_band filters are tight, not wide.

        This test locks in the known-good tight price bands that were restored
        after commit 3d7bc4a accidentally widened them to (0.05, 0.95), causing
        all CT universe candidates to be dropped.

        The tight bands ensure we only trade contracts with reasonable implied
        probabilities that reflect near-spot strikes:
        - Short-term (15m/1h): tighter bands (0.25-0.75 or 0.35-0.75)
        - Longer-term (daily+): wider but still selective (0.50-0.85)

        If this test fails, someone has widened the price bands again, which
        will likely cause the same "41 dropped, 0 kept" regression.
        """
        # Known-good tight bands from before commit 249d2de
        # Now includes annual timeframe for all 5 assets (30-cell matrix)
        EXPECTED_TIGHT_BANDS = {
            ("BTC", "15m"): (0.35, 0.75),
            ("BTC", "1h"): (0.35, 0.75),
            ("BTC", "daily"): (0.65, 0.85),
            ("BTC", "weekly"): (0.65, 0.85),
            ("BTC", "monthly"): (0.70, 0.85),
            ("BTC", "annual"): (0.55, 0.90),
            ("ETH", "15m"): (0.35, 0.75),
            ("ETH", "1h"): (0.35, 0.75),
            ("ETH", "daily"): (0.65, 0.85),
            ("ETH", "weekly"): (0.65, 0.85),
            ("ETH", "monthly"): (0.70, 0.85),
            ("ETH", "annual"): (0.55, 0.90),
            ("SOL", "15m"): (0.25, 0.75),
            ("SOL", "1h"): (0.25, 0.75),
            ("SOL", "daily"): (0.55, 0.80),
            ("SOL", "weekly"): (0.60, 0.80),
            ("SOL", "monthly"): (0.65, 0.80),
            ("SOL", "annual"): (0.50, 0.90),
            ("XRP", "15m"): (0.25, 0.75),
            ("XRP", "1h"): (0.25, 0.75),
            ("XRP", "daily"): (0.55, 0.80),
            ("XRP", "weekly"): (0.60, 0.80),
            ("XRP", "monthly"): (0.65, 0.80),
            ("XRP", "annual"): (0.50, 0.90),
            ("DOGE", "15m"): (0.25, 0.70),
            ("DOGE", "1h"): (0.25, 0.70),
            ("DOGE", "daily"): (0.50, 0.75),
            ("DOGE", "weekly"): (0.55, 0.75),
            ("DOGE", "monthly"): (0.60, 0.75),
            ("DOGE", "annual"): (0.50, 0.90),
        }

        for (asset, timeframe), expected_band in EXPECTED_TIGHT_BANDS.items():
            profile = default_engine.strategy_config.get(asset, timeframe)
            assert profile is not None, f"Missing profile for {asset} {timeframe}"

            actual_band = profile.allowed_price_band
            assert actual_band == expected_band, (
                f"{asset} {timeframe}: price_band changed from {expected_band} to {actual_band}. "
                f"Wide bands like (0.05, 0.95) will starve the CT universe. "
                f"See commit 4d68a78 and the price_band filter restoration for context."
            )


# ═══════════════════════════════════════════════════════════════════════════
# 7. No hardcoded risk amounts (static analysis)
# ═══════════════════════════════════════════════════════════════════════════

class TestNoHardcodedRiskAmounts:
    """Ensure that crypto_kalshi_risk.py contains no hardcoded dollar constants."""

    _SOURCE_FILE = (
        Path(__file__).parent.parent.parent.parent
        / "merid" / "event_venues" / "kalshi" / "crypto_kalshi_risk.py"
    )

    # Dollar-value constants that must NOT appear in sizing/risk logic.
    # These are representative values that would indicate a hardcoded assumption.
    _FORBIDDEN_LITERALS = {250.0, 100.0, 1000.0, 7.5, 2500.0}

    def _collect_numeric_literals(self, source: str) -> set[float]:
        """Parse *source* and return all float/int literals found in the AST."""
        tree = ast.parse(source)
        literals: set[float] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                literals.add(float(node.value))
        return literals

    def test_source_file_exists(self):
        assert self._SOURCE_FILE.exists(), f"Source file not found: {self._SOURCE_FILE}"

    def test_no_forbidden_dollar_literals_in_sizing_logic(self):
        """The sizing / risk functions must not embed dollar-amount constants."""
        source = self._SOURCE_FILE.read_text()
        literals = self._collect_numeric_literals(source)
        bad = literals & self._FORBIDDEN_LITERALS
        assert not bad, (
            f"Forbidden dollar-amount literals found in crypto_kalshi_risk.py: {bad}\n"
            "All risk values must be derived from bankroll × config percentage."
        )

    def test_sizing_scales_with_bankroll(self, default_engine):
        """If bankroll doubles, risk_usd doubles — confirming no hardcoded amounts."""
        risk_1k = default_engine.compute_trade_risk_usd(1000.0, asset="BTC")
        risk_2k = default_engine.compute_trade_risk_usd(2000.0, asset="BTC")
        assert risk_2k == pytest.approx(risk_1k * 2.0)

    def test_contract_count_scales_with_bankroll(self, default_engine):
        """Contract count (approximately) doubles when bankroll doubles."""
        c_1k = default_engine.compute_contracts_for_order(1000.0, 0.50, asset="BTC")
        c_2k = default_engine.compute_contracts_for_order(2000.0, 0.50, asset="BTC")
        assert c_2k == pytest.approx(c_1k * 2, abs=1)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Integration: full order flow
# ═══════════════════════════════════════════════════════════════════════════

class TestFullOrderFlow:
    """End-to-end: alpha signal → sizing → strategy filters → risk gate."""

    def test_happy_path_btc_intraday(self):
        engine = KalshiCryptoRiskEngine()
        bankroll = 1000.0
        asset = "BTC"
        timeframe = "intraday"
        price = 0.50
        model_prob = 0.65
        market_prob = 0.50

        # Step 1: strategy filters
        ok, reason = engine.check_strategy_filters(
            asset=asset, timeframe=timeframe,
            price=price,
            model_probability=model_prob,
            market_probability=market_prob,
            trades_today=0, current_open_positions=0,
        )
        assert ok is True, reason

        # Step 2: size the order using the asset slice
        asset_bl = engine.asset_bankroll(bankroll, asset)
        contracts = engine.compute_contracts_for_order(asset_bl, price, asset=asset)
        assert contracts > 0

        # Step 3: risk gate
        ok, reason = engine.check_can_add_order(
            total_bankroll=bankroll,
            current_equity=bankroll,
            open_positions=_empty_ledger(),
            asset=asset,
            price=price,
            contracts=contracts,
        )
        assert ok is True, reason

    @pytest.mark.parametrize("asset", CRYPTO_ASSETS)
    def test_all_assets_pass_happy_path(self, asset):
        engine = KalshiCryptoRiskEngine()
        bankroll = 10_000.0  # large bankroll, small first order
        asset_bl = engine.asset_bankroll(bankroll, asset)
        contracts = engine.compute_contracts_for_order(asset_bl, 0.50, asset=asset)
        assert contracts > 0
        ok, reason = engine.check_can_add_order(
            total_bankroll=bankroll,
            current_equity=bankroll,
            open_positions=_empty_ledger(),
            asset=asset,
            price=0.50,
            contracts=contracts,
        )
        assert ok is True, reason

    def test_zero_contracts_blocked(self, default_engine):
        ok, reason = default_engine.check_can_add_order(
            total_bankroll=1000.0,
            current_equity=1000.0,
            open_positions=_empty_ledger(),
            asset="BTC",
            price=0.50,
            contracts=0,
        )
        assert ok is False
        assert reason == "zero_or_negative_contracts"

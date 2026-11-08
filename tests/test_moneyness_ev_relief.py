import math

import pytest

from merid.prediction import directional_regime as dr
from merid.prediction import trade_decision as td


@pytest.fixture(autouse=True)
def isolated_decisions(monkeypatch, tmp_path):
    monkeypatch.setattr(td, "MERID_ORDER_DECISION_LEDGER_ENABLED", False)
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_PATH", str(tmp_path / "evidence.json"))
    monkeypatch.setenv("MERID_EVIDENCE_ESCAPE_STATE_PATH", str(tmp_path / "escape.json"))
    monkeypatch.setenv("MERID_DIRECTIONAL_THROTTLE_PATH", str(tmp_path / "throttle.json"))


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("price", [20.0, 55.0, 78.5, 89.99])
def test_current_economics_relieve_legacy_price_veto(monkeypatch, asset, side, price):
    monkeypatch.setenv("MERID_MONEYNESS_EV_RELIEF_ENABLED", "1")
    assert dr.moneyness_ev_relief(side, asset, price, 2.0)


@pytest.mark.parametrize("price,ev", [(0, 3), (90, 3), (99, 3), (55, 1.99),
                                      (55, 0), (55, -1), (None, 3),
                                      (math.nan, 3), (55, math.inf), (55, None)])
def test_relief_fails_closed(monkeypatch, price, ev):
    monkeypatch.setenv("MERID_MONEYNESS_EV_RELIEF_ENABLED", "1")
    assert not dr.moneyness_ev_relief("no", "XRP", price, ev)


def test_relief_kill_switch_and_scope(monkeypatch):
    monkeypatch.setenv("MERID_MONEYNESS_EV_RELIEF_ENABLED", "0")
    assert not dr.moneyness_ev_relief("yes", "BTC", 55, 3)
    monkeypatch.setenv("MERID_MONEYNESS_EV_RELIEF_ENABLED", "1")
    assert not dr.moneyness_ev_relief("other", "BTC", 55, 3)
    assert not dr.moneyness_ev_relief("yes", "OTHER", 55, 3)


def test_zero_cap_does_not_disable_independent_block_band(monkeypatch):
    monkeypatch.setenv("MERID_MONEYNESS_GATE_ENABLED", "1")
    monkeypatch.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_BTC", "0")
    monkeypatch.setenv("MERID_MONEYNESS_BLOCK_BAND_LO_CENTS_NO_BTC", "51")
    monkeypatch.setenv("MERID_MONEYNESS_BLOCK_BAND_HI_CENTS_NO_BTC", "64")
    assert "_band_" in dr.entry_price_cap_block_reason(55, "no", "BTC")
    assert dr.entry_price_cap_block_reason(80, "no", "BTC") is None


def test_scoped_exception_kill_beats_side_enable(monkeypatch):
    monkeypatch.setenv("MERID_PRICE_CAP_EXCEPT_YES", "1")
    monkeypatch.setenv("MERID_PRICE_CAP_EXCEPT_BTC_YES", "0")
    assert not dr._moneyness_cap_exception("yes", "BTC", 82, 3)
    assert dr._moneyness_cap_exception("yes", "ETH", 82, 3)


@pytest.mark.parametrize("ev,expected", [(3, None), (1, "pinned_fav_moneyness_cap")])
def test_pinned_fav_relief_still_requires_current_edge(monkeypatch, ev, expected):
    monkeypatch.setenv("MERID_MONEYNESS_EV_RELIEF_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_LO", "82")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_HI", "89")
    monkeypatch.setenv("MERID_PINNED_FAV_MONEYNESS_CAP_CENTS_NO_XRP", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_HONOR_MONEYNESS_CAPS", "1")
    monkeypatch.setenv("MERID_PRICE_CAP_EXCEPT_XRP_NO", "0")
    monkeypatch.setattr(dr, "pinned_fav_cap_remaining", lambda: 5)
    assert dr.pinned_fav_block(85, ev, 300, 0.95, "no", "XRP") == expected
    if expected is None:
        assert dr.pinned_fav_block(85, ev, 300, 0.1, "no", "XRP") == "pinned_fav_maker_low_p"


@pytest.mark.parametrize("ev", [math.nan, math.inf, -math.inf, "bad"])
def test_pinned_fav_rejects_invalid_economics(monkeypatch, ev):
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_LO", "94")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_HI", "98")
    monkeypatch.setattr(dr, "pinned_fav_cap_remaining", lambda: 5)
    assert dr.pinned_fav_block(95, ev, 300, p_selected=0.95) == "pinned_fav_low_ev"


@pytest.mark.parametrize("ev", [math.nan, math.inf, -math.inf])
def test_old_cap_exception_rejects_nonfinite_edge(monkeypatch, ev):
    monkeypatch.setenv("MERID_PRICE_CAP_EXCEPT_YES", "1")
    monkeypatch.delenv("MERID_PRICE_CAP_EXCEPT_BTC_YES", raising=False)
    assert not dr._moneyness_cap_exception("yes", "BTC", 82, ev)


@pytest.mark.parametrize("tte", [121, 150, 180])
def test_late_candidate_reaches_data_and_economics(monkeypatch, tte):
    monkeypatch.setattr(td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 120)
    d = td.compute_trade_decision(
        run_id="test", decision_id="test", ticker="KXBTC15M-TEST", asset="BTC",
        spot_price=101, strike_price=100, seconds_to_expiry=tte,
        yes_bid_cents=48, yes_ask_cents=52, no_bid_cents=48, no_ask_cents=52,
        yes_depth_cc=200, no_depth_cc=200, fee_per_contract_cents=1,
        annualized_vol=0.6, model_uncertainty=0.05,
        data_quality="live", regime="normal", min_required_edge=0.01,
    )
    assert d.no_trade_reason not in ("min_tte_entry_disabled", "final_minute_entry_disabled")
    assert d.indicators.get("annualized_vol") is not None


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
@pytest.mark.parametrize("side", ["yes", "no"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("cap", [1, 75])
def test_decision_price_veto_relief_is_side_specific(monkeypatch, tmp_path, asset, side, enabled, cap):
    monkeypatch.setenv("MERID_MONEYNESS_EV_RELIEF_ENABLED", str(int(enabled)))
    monkeypatch.setenv("MERID_MONEYNESS_GATE_ENABLED", "1")
    monkeypatch.setenv(f"MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_{side.upper()}_{asset}", str(cap))
    monkeypatch.setenv(f"MERID_MONEYNESS_BLOCK_BAND_LO_CENTS_{side.upper()}_{asset}", "51")
    monkeypatch.setenv(f"MERID_MONEYNESS_BLOCK_BAND_HI_CENTS_{side.upper()}_{asset}", "64")
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "0")
    monkeypatch.setenv("MERID_PRICE_CAP_EXCEPT_YES", "0")
    monkeypatch.setenv("MERID_PRICE_CAP_EXCEPT_NO", "0")
    monkeypatch.setenv(f"MERID_PRICE_CAP_EXCEPT_{asset}_{side.upper()}", "0")
    monkeypatch.setenv("MERID_DIRECTIONAL_THROTTLE_PATH", str(tmp_path / "throttle.json"))
    monkeypatch.setattr(td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 120)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MIN_W", 0)
    monkeypatch.setattr(td, "MERID_MARKET_ANCHOR_MAX_W", 0)
    monkeypatch.setattr(td, "MERID_USE_REALIZED_VOL", False)
    monkeypatch.setattr(td, "MERID_ANCHOR_VOL_TO_MARKET", False)
    d = td.compute_trade_decision(
        run_id="test", decision_id=f"relief_{asset}_{side}_{enabled}",
        ticker=f"KX{asset}15M-TEST", asset=asset,
        spot_price=101 if side == "yes" else 99, strike_price=100,
        seconds_to_expiry=150,
        yes_bid_cents=53 if side == "yes" else 43,
        yes_ask_cents=55 if side == "yes" else 45,
        no_bid_cents=43 if side == "yes" else 53,
        no_ask_cents=45 if side == "yes" else 55,
        yes_depth_cc=200, no_depth_cc=200, fee_per_contract_cents=1,
        annualized_vol=0.6, model_uncertainty=0.01,
        data_quality="live", regime="normal", min_required_edge=0.01,
    )
    ind = d.indicators
    breakdown = d.yes_edge_breakdown if side == "yes" else d.no_edge_breakdown
    relieved = enabled and float(breakdown.net_edge) * 100 >= 2.0
    assert (ind.get(f"{side}_price_cap_block") is None) == relieved
    assert bool(ind.get(f"{side}_moneyness_ev_relief")) == relieved
    if relieved:
        assert ind[f"{side}_legacy_price_veto"].startswith("entry_price_cap_")


@pytest.mark.parametrize("tte", [31, 60, 119, 120])
def test_generic_late_floor_remains_closed(monkeypatch, tte):
    monkeypatch.setattr(td, "MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", 120)
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "0")
    d = td.compute_trade_decision(
        run_id="test", decision_id=f"floor_{tte}", ticker="KXBTC15M-TEST", asset="BTC",
        spot_price=101, strike_price=100, seconds_to_expiry=tte,
        yes_bid_cents=48, yes_ask_cents=52, no_bid_cents=48, no_ask_cents=52,
        yes_depth_cc=200, no_depth_cc=200, fee_per_contract_cents=1,
        annualized_vol=0.6, model_uncertainty=0.05,
        data_quality="live", regime="normal", min_required_edge=0.01,
    )
    assert d.selected_outcome is None
    assert d.no_trade_reason == "min_tte_entry_disabled"


@pytest.mark.parametrize("floor", [None, "120", "invalid"])
@pytest.mark.parametrize("tte", [119, 150])
def test_risk_layer_uses_matching_floor(monkeypatch, floor, tte):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from merid.event_venues.kalshi import market_catalog
    from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager

    class RemainingRiskChecksReached(Exception):
        pass

    class StopBeforeRemainingChecks:
        def __enter__(self):
            raise RemainingRiskChecksReached

        def __exit__(self, *args):
            return False

    catalog = MagicMock()
    catalog.get_market.return_value = SimpleNamespace(minutes_to_expiry=tte / 60)
    monkeypatch.setattr(market_catalog, "get_market_catalog", lambda: catalog)
    if floor is None:
        monkeypatch.delenv("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", raising=False)
    else:
        monkeypatch.setenv("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", floor)
    manager = SimpleNamespace(
        _state=SimpleNamespace(current_equity_usd=100),
        _lock=StopBeforeRemainingChecks(), _log_breach=lambda *args: None,
    )
    args = (manager, "KXBTC15M-TEST", "crypto", 1, 50, 0.1, 0,
            datetime.now(timezone.utc))
    if tte < 120:
        result = KalshiRiskManager._check_order_locked(*args, asset="BTC", timeframe="15m")
        assert result[0] is False and result[2] == "entry_tte_floor"
    else:
        with pytest.raises(RemainingRiskChecksReached):
            KalshiRiskManager._check_order_locked(*args, asset="BTC", timeframe="15m")


@pytest.mark.asyncio
@pytest.mark.parametrize("tte,action", [(150, "keep"), (119, "cancel")])
async def test_resting_monitor_matches_entry_floor(monkeypatch, tte, action):
    from unittest.mock import MagicMock
    from merid.event_venues.kalshi import position_cache
    from merid.event_venues.kalshi.resting_order_monitor import RestingOrderMonitor, RestingOrderRecord

    cache = MagicMock()
    cache.get_position.return_value = None
    monkeypatch.setattr(position_cache, "get_position_cache", lambda: cache)
    monkeypatch.delenv("MERID_ENTRY_MIN_SECONDS_TO_EXPIRY", raising=False)
    monkeypatch.setenv("MERID_RESTING_TOXIC_MID_CANCEL", "0")
    record = RestingOrderRecord(
        kalshi_order_id="test", intent_id="entry_test", ticker="KXBTC15M-TEST",
        side="yes", action="buy", asset="BTC", risk_tier="B",
        original_size=1, remaining_size=1, price_cents=50,
        original_minutes_to_expiry=tte / 60, max_hold_seconds=60,
    )
    result = await RestingOrderMonitor()._recheck_order(record)
    assert result.action == action, result.reason
    if action == "cancel":
        assert result.reason.startswith("window_not_allowed:min_tte_entry")

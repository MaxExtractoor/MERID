"""Cross-window exposure remains reserved until authoritative release."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from merid.risk.profiles import kalshi_crypto_15m_risk_envelope as risk


@pytest.fixture
def state(monkeypatch):
    state = {
        "window_start_ts": 900.0,
        "agent_exposure_usd": {"BTC_15M": Decimal("0.40")},
        "total_exposure_usd": Decimal("0.40"),
        "agent_resting_exposure_usd": {"ETH_15M": Decimal("0.50")},
        "total_resting_exposure_usd": Decimal("0.50"),
        "peak_bankroll_usd": Decimal("10"),
        "asset_exposure_usd": {"BTC": Decimal("0.40")},
    }
    monkeypatch.setattr(risk, "_WINDOW_TRACKING_STATE", state)
    monkeypatch.setenv("MERID_FIXED_EXPOSURE_CAP_USD", "1.00")
    return state


def _envelope():
    return SimpleNamespace(
        live_bankroll_usd=Decimal("10"),
        fixed_exposure_cap_usd=Decimal("1"),
        is_halted=False,
        window_start_ts=900.0,
        agent_window_exposure_usd={},
        total_window_exposure_usd=0,
        agent_resting_exposure_usd={},
        total_resting_exposure_usd=0,
    )


def test_rollover_retains_position_and_resting_reservations(state):
    with risk._WINDOW_TRACKING_LOCK:
        risk._roll_window_if_needed_locked(1801.0, Decimal("10"))
    assert state["window_start_ts"] == 1800.0
    assert state["total_exposure_usd"] == Decimal("0.40")
    assert state["total_resting_exposure_usd"] == Decimal("0.50")
    assert state["agent_exposure_usd"] == {"BTC_15M": Decimal("0.40")}
    assert state["agent_resting_exposure_usd"] == {"ETH_15M": Decimal("0.50")}
    assert state["asset_exposure_usd"] == {"BTC": Decimal("0.40")}


def test_retained_exposure_binds_until_explicit_release(state):
    envelope = _envelope()
    allowed, reason = risk.KalshiCrypto15mRiskEnvelope.check_window_limit(
        envelope, "SOL_15M", Decimal("0.20"), 1801.0
    )
    assert not allowed and "total_venue_window_limit" in reason

    risk.KalshiCrypto15mRiskEnvelope.release_resting_order_exposure(
        envelope, "ETH_15M", Decimal("0.50")
    )
    allowed, _ = risk.KalshiCrypto15mRiskEnvelope.check_window_limit(
        envelope, "SOL_15M", Decimal("0.20"), 1801.0
    )
    assert allowed
    assert state["total_exposure_usd"] == Decimal("0.40")


def test_explicit_window_advance_does_not_clear_exposure(state):
    envelope = _envelope()
    risk.KalshiCrypto15mRiskEnvelope.reset_window_tracking(envelope, 1801.0)
    assert envelope.window_start_ts == 1800.0
    assert state["total_exposure_usd"] == Decimal("0.40")
    assert state["total_resting_exposure_usd"] == Decimal("0.50")
    assert envelope.total_resting_exposure_usd == 0.50


@pytest.mark.parametrize("actual", [Decimal("0"), Decimal("0.80")])
def test_cache_only_drift_blocks_without_rewriting_reservations(state, actual):
    envelope = _envelope()
    allowed, reason = risk.KalshiCrypto15mRiskEnvelope.check_window_limit(
        envelope, "SOL_15M", Decimal("0.01"), 1801.0,
        actual_position_exposure_usd=actual,
    )
    assert not allowed and "window_exposure_mismatch" in reason
    assert state["total_exposure_usd"] == Decimal("0.40")
    assert state["agent_exposure_usd"] == {"BTC_15M": Decimal("0.40")}
    assert state["total_resting_exposure_usd"] == Decimal("0.50")


@pytest.mark.parametrize("method", ["record_position_closure", "refund_order_execution"])
def test_position_release_cannot_spend_another_agents_exposure(state, method):
    state["agent_exposure_usd"]["ETH_15M"] = Decimal("0.30")
    state["total_exposure_usd"] = Decimal("0.70")
    envelope = _envelope()
    release = getattr(risk.KalshiCrypto15mRiskEnvelope, method)

    release(envelope, "unknown", Decimal("9"))
    assert state["total_exposure_usd"] == Decimal("0.70")
    release(envelope, "BTC_15M", Decimal("9"))
    assert state["total_exposure_usd"] == Decimal("0.30")
    assert state["agent_exposure_usd"]["ETH_15M"] == Decimal("0.30")


def test_resting_release_cannot_spend_another_agents_reservation(state):
    state["agent_resting_exposure_usd"]["SOL_15M"] = Decimal("0.35")
    state["total_resting_exposure_usd"] = Decimal("0.85")
    envelope = _envelope()
    release = risk.KalshiCrypto15mRiskEnvelope.release_resting_order_exposure

    release(envelope, "unknown", Decimal("9"))
    assert state["total_resting_exposure_usd"] == Decimal("0.85")
    release(envelope, "ETH_15M", Decimal("9"))
    assert state["total_resting_exposure_usd"] == Decimal("0.35")
    assert state["agent_resting_exposure_usd"]["SOL_15M"] == Decimal("0.35")


@pytest.mark.parametrize("amount", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_resting_amount_cannot_change_reservations(state, amount):
    envelope = _envelope()
    with pytest.raises(ValueError):
        risk.KalshiCrypto15mRiskEnvelope.release_resting_order_exposure(
            envelope, "ETH_15M", amount
        )
    with pytest.raises(ValueError):
        risk.KalshiCrypto15mRiskEnvelope.record_resting_order_placement(
            envelope, "ETH_15M", amount
        )
    assert state["total_resting_exposure_usd"] == Decimal("0.50")

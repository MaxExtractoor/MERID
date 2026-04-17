"""CI contracts for RTI settlement paths (fail on regressions)."""
from __future__ import annotations

import pytest

from merid.data.settlement_rti_buffer import SettlementBufferRegistry, SettlementRTIBuffer
from merid.event_venues.kalshi.settlement_execution_guard import evaluate_settlement_order
from merid.signals.cfb_rti_adapter import CFBRTIConfigurationError, require_cfb_for_live_trading
from merid.signals.settlement_view import build_settlement_view_from_buffer


RTI_TICKER = "KXBTC15M-26JAN011200-0"


@pytest.fixture(autouse=True)
def reset_registry():
    SettlementBufferRegistry.reset_for_tests()
    yield
    SettlementBufferRegistry.reset_for_tests()


def test_rti_crypto_buy_blocked_when_seconds_to_expiry_lte_final_window(monkeypatch):
    monkeypatch.setenv("MERID_RTI_SETTLEMENT_ORDER_POLICY", "reduce_ok")
    monkeypatch.setenv("MERID_RTI_SETTLEMENT_FINAL_SECONDS", "60")
    monkeypatch.delenv("MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE", raising=False)
    for ste in (59.0, 30.0, 0.5):
        assert (
            evaluate_settlement_order(
                ticker=RTI_TICKER,
                action="buy",
                seconds_to_expiry=ste,
                count=1,
            )
            == "rti_settlement_window:no_new_buys"
        )


def test_rti_crypto_buy_allowed_just_outside_final_window(monkeypatch):
    monkeypatch.setenv("MERID_RTI_SETTLEMENT_FINAL_SECONDS", "60")
    assert (
        evaluate_settlement_order(
            ticker=RTI_TICKER,
            action="buy",
            seconds_to_expiry=60.01,
            count=1,
        )
        is None
    )


def test_partial_buffer_cannot_build_settlement_view():
    buf = SettlementRTIBuffer(RTI_TICKER, "BTC", 1_700_000_100)
    buf.ingest(buf.window_start, 1.0)
    buf.ingest(buf.window_start + 1, 2.0)
    with pytest.raises(ValueError, match="settlement_view requires"):
        build_settlement_view_from_buffer(buf)


def test_require_cfb_raises_in_live_without_adapter_or_override(monkeypatch):
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("MERID_CFB_RTI_ADAPTER", "null")
    monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)
    monkeypatch.delenv("MERID_CFB_RTI_SIMULATE", raising=False)
    with pytest.raises(CFBRTIConfigurationError):
        require_cfb_for_live_trading()


def test_require_cfb_allowed_with_explicit_null_override(monkeypatch):
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("MERID_CFB_RTI_ADAPTER", "null")
    monkeypatch.setenv("MERID_ALLOW_NULL_CFB", "1")
    require_cfb_for_live_trading()


def test_execution_gate_does_not_block_when_quarantine_active(monkeypatch):
    # When CFB adapter is null/unset, the quarantine is active and the filter
    # pipeline already excludes all crypto RTI markets.  The execution gate
    # must NOT add an rti_feed block — doing so would halt non-crypto trading
    # for a protection that is already enforced at the market-selection layer.
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("KALSHI_USE_DEMO", "false")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    monkeypatch.setenv("MERID_CFB_RTI_ADAPTER", "null")
    monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)
    monkeypatch.delenv("MERID_CFB_RTI_SIMULATE", raising=False)

    from core.execution_gate import check_execution_gate

    st = check_execution_gate()
    rti = [r for r in st.reasons if r.source == "rti_feed"]
    assert not rti, "execution_gate must not block rti_feed when quarantine is active"


def test_execution_gate_does_not_flag_rti_when_pm_not_live_enabled(monkeypatch):
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("KALSHI_USE_DEMO", "false")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "paper")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "false")
    monkeypatch.setenv("MERID_CFB_RTI_ADAPTER", "null")
    monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)
    monkeypatch.delenv("MERID_CFB_RTI_SIMULATE", raising=False)

    from core.execution_gate import check_execution_gate

    st = check_execution_gate()
    assert not [r for r in st.reasons if r.source == "rti_feed"]


def test_execution_gate_allows_simulate_flag_without_explicit_adapter(monkeypatch):
    """When operator sets SIMULATE=1, treat as explicit simulation (no rti_feed block)."""
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("KALSHI_USE_DEMO", "false")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    monkeypatch.setenv("MERID_CFB_RTI_SIMULATE", "1")
    monkeypatch.delenv("MERID_CFB_RTI_ADAPTER", raising=False)
    monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)
    monkeypatch.delenv("MERID_CFB_RTI_POLL_URL", raising=False)

    from core.execution_gate import check_execution_gate

    st = check_execution_gate()
    assert not [r for r in st.reasons if r.source == "rti_feed"]


def test_execution_gate_allows_poll_url_without_explicit_adapter(monkeypatch):
    """When operator sets a poll URL, infer live intent (no 'explicit mode' block)."""
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("KALSHI_USE_DEMO", "false")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    monkeypatch.setenv("MERID_CFB_RTI_POLL_URL", "https://example.invalid/rti")
    monkeypatch.delenv("MERID_CFB_RTI_ADAPTER", raising=False)
    monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)
    monkeypatch.delenv("MERID_CFB_RTI_SIMULATE", raising=False)

    from core.execution_gate import check_execution_gate

    st = check_execution_gate()
    # We only care that RTI mode selection isn't the blocker; the URL may still be unreachable at runtime.
    assert not [r for r in st.reasons if r.source == "rti_feed"]

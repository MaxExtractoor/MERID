"""Regression tests for executor wiring bugs E4-1, E4-2, E4-5, E4-X."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────

def _make_executor():
    from merid.execution.executors.kalshi import KalshiExecutor
    ex = KalshiExecutor()
    # Bypass real client creation
    ex._client = MagicMock()
    return ex


def _success_balance(cents: int = 500_000):
    r = MagicMock()
    r.success = True
    r.data = {"balance": cents}
    r.error_message = None
    r.latency_ms = 1
    return r


def _success_order(filled: int = 10, price: int = 55, order_id: str = "ord-1"):
    r = MagicMock()
    r.success = True
    r.data = {"order": {
        "order_id": order_id,
        "status": "filled",
        "yes_price": price,
        "filled_count": filled,
        "count": filled,
    }}
    r.latency_ms = 5
    return r


# ── E4-1: category passed to check_order ─────────────────────────────────

@pytest.mark.asyncio
async def test_category_passed_to_check_order():
    """check_order must receive category='crypto', not None."""
    ex = _make_executor()

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False

        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr

        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        call_kwargs = risk_mgr.check_order.call_args
        assert call_kwargs.kwargs.get("category") == "crypto" or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == "crypto"
        ), f"category was not 'crypto': {call_kwargs}"


# ── E4-2: outcome warning ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_outcome_emits_warning(caplog):
    """When metadata['outcome'] is absent, a warning must be logged."""
    import logging
    ex = _make_executor()

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
        caplog.at_level(logging.WARNING, logger="merid.execution.executors.kalshi"),
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr
        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"underlying": "BTC"},   # no "outcome" key
        )

        assert any("outcome" in r.message for r in caplog.records), (
            "Expected a warning about missing 'outcome' metadata"
        )


# ── E4-X: category_exposure check_and_reserve called ─────────────────────

@pytest.mark.asyncio
async def test_category_exposure_check_and_reserve_called():
    """check_and_reserve must be called before order submission."""
    ex = _make_executor()

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch("merid.event_venues.kalshi.category_exposure.get_category_exposure_tracker") as mock_ct,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr

        cat_tracker = MagicMock()
        cat_tracker.check_and_reserve.return_value = (True, "")
        mock_ct.return_value = cat_tracker

        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        cat_tracker.check_and_reserve.assert_called_once()
        call_args = cat_tracker.check_and_reserve.call_args
        assert call_args.args[0] == "crypto"
        assert call_args.args[1] == "BTC"


# ── E4-5: record_close called on sell fills ───────────────────────────────

@pytest.mark.asyncio
async def test_record_close_called_on_sell_fill():
    """record_close() must be called when action='sell' and order fills."""
    ex = _make_executor()

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr
        mock_req.side_effect = [_success_balance(), _success_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="sell",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        risk_mgr.record_close.assert_called_once()


# ── E4-5 / E4-X: record_close + release called on buy failure ─────────────

@pytest.mark.asyncio
async def test_record_close_called_on_buy_order_failure():
    """When the buy order POST fails, record_close() must reverse the notional
    reservation and the category exposure must be released."""
    ex = _make_executor()

    def _fail_order():
        r = MagicMock()
        r.success = False
        r.error_message = "network error"
        r.latency_ms = 10
        return r

    with (
        patch("merid.execution.executors.kalshi._kill_switch_error", False),
        patch("merid.risk.kill_switches.risk_controller") as mock_rc,
        patch("merid.prediction.venue_gate.get_venue_gate") as mock_vg,
        patch("merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk") as mock_risk_fn,
        patch("merid.event_venues.kalshi.category_exposure.get_category_exposure_tracker") as mock_ct,
        patch.object(ex._client, "_request_with_resilience", new_callable=AsyncMock) as mock_req,
    ):
        mock_rc.can_trade.return_value = True
        mock_vg.return_value.should_simulate_fill.return_value = False
        risk_mgr = MagicMock()
        risk_mgr.check_order.return_value = (True, "OK")
        mock_risk_fn.return_value = risk_mgr

        cat_tracker = MagicMock()
        cat_tracker.check_and_reserve.return_value = (True, "")
        mock_ct.return_value = cat_tracker

        # balance fetch succeeds, order POST fails
        mock_req.side_effect = [_success_balance(), _fail_order()]

        await ex.execute_trade(
            "KXBTUPDOWN-15M-0316-1415",
            side="buy",
            amount=10,
            order_type="limit",
            price=0.55,
            metadata={"outcome": "yes", "underlying": "BTC"},
        )

        # Notional must be reversed
        risk_mgr.record_close.assert_called_once()
        # Category reservation must be released
        cat_tracker.release.assert_called_once()

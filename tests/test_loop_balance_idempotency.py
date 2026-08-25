"""
Balance/risk idempotency tests.

Verifies that one logical loop tick consumes exactly one bankroll snapshot
and that BalanceCalibrator is not invoked multiple times per cycle.
"""

from unittest.mock import Mock, patch

import pytest

from merid.loop_15m import Kalshi15mLoop


class AsyncMock(Mock):
    """A Mock that is also an awaitable coroutine."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


def _make_loop():
    """Return a minimal Kalshi15mLoop with mocked dependencies."""
    agent_grid = Mock()
    agent_grid._agents = [Mock()]
    agent_grid.run_cycle = AsyncMock(return_value=[])

    bankroll_service = Mock()
    risk_config = Mock()

    with patch(
        "merid.event_venues.kalshi.market_catalog.get_market_catalog",
        return_value=Mock(),
    ), patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=Mock(),
    ), patch(
        "merid.event_venues.kalshi.kalshi_15m_time.get_kalshi_15m_window",
        return_value=Mock(suffix="0000"),
    ), patch(
        "merid.event_venues.kalshi.market_maker_15m.init_market_maker_15m",
        side_effect=ImportError,
    ):
        loop = Kalshi15mLoop(
            agent_grid=agent_grid,
            bankroll_service=bankroll_service,
            risk_config=risk_config,
            cadence_seconds=5.0,
        )
    return loop


@pytest.mark.asyncio
async def test_run_agent_grid_with_timeout_does_not_recalibrate():
    """_run_agent_grid_with_timeout must not fetch/calibrate bankroll itself."""
    loop = _make_loop()

    calibrator_update = Mock(return_value=False)
    calibrator = Mock(update=calibrator_update)

    with patch(
        "merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync",
        return_value=100.0,
    ) as get_equity, patch(
        "merid.event_venues.kalshi.balance_calibrator.get_balance_calibrator",
        return_value=calibrator,
    ) as get_calibrator, patch(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        return_value=Mock(get_all_positions=Mock(return_value={})),
    ), patch(
        "merid.event_venues.kalshi.kalshi_15m_time.get_kalshi_15m_window",
        return_value=Mock(suffix=loop._current_window_suffix),
    ), patch(
        "merid.governance.trading_circuit_breaker.get_trading_circuit_breaker",
        return_value=Mock(halted=False),
    ), patch(
        "merid.risk.unified_risk_manager.get_unified_risk_manager",
        return_value=Mock(reset_cycle=Mock()),
    ), patch(
        "merid.risk.global_slot_allocator.get_global_slot_allocator",
        return_value=Mock(
            clear_slots_on_empty_positions=Mock(), get_slot_count=Mock(return_value=0)
        ),
    ):
        await loop._run_agent_grid_with_timeout(
            1, trading_ready=True, allow_new_entries=True
        )

    assert get_equity.call_count == 0, (
        "_run_agent_grid_with_timeout must not fetch bankroll"
    )
    assert get_calibrator.call_count == 0, (
        "_run_agent_grid_with_timeout must not call BalanceCalibrator"
    )
    assert calibrator_update.call_count == 0


def test_compute_allow_new_entries_is_idempotent_and_rejects_invalid_bankroll():
    """_compute_allow_new_entries must not mutate state and must reject <= 0 bankroll."""
    loop = _make_loop()

    with patch(
        "merid.event_venues.kalshi.kalshi_config.KALSHI_READY", True
    ), patch(
        "merid.loop_15m.markets_expected_now", return_value=True,
    ), patch(
        "merid.event_venues.kalshi.market_catalog.get_market_catalog",
        return_value=Mock(get_current_15m_market=Mock(return_value=None)),
    ):
        assert loop._compute_allow_new_entries(None) is False
        assert loop._compute_allow_new_entries(0.0) is False
        assert loop._compute_allow_new_entries(-1.0) is False

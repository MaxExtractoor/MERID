"""Tests for gap analysis fixes - BankrollServiceV2 import, window/exit policy resolution, scale-out config."""

import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestBankrollServiceV2Import:
    """Test that BankrollServiceV2 is available from the canonical module."""

    def test_bankroll_service_v2_module_exists(self):
        """Verify the bankroll_service_v2 module exists and has BankrollServiceV2."""
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import BankrollServiceV2
            assert BankrollServiceV2 is not None
        except ImportError as e:
            pytest.fail(f"Failed to import BankrollServiceV2 from bankroll_service_v2: {e}")


class TestMockOrderRouterDocumentation:
    """Test that mock order router has been removed."""
    
    def test_order_router_15m_removed(self):
        """Verify order_router_15m.py has been deleted."""
        order_router_path = project_root / "merid" / "event_venues" / "kalshi" / "order_router_15m.py"
        
        # File should not exist (deleted in 2026-07-16 audit cleanup)
        assert not order_router_path.exists(), \
            "Legacy order_router_15m.py should have been deleted"


class TestBankrollServiceV2FetchTimeout:
    """Verify balance fetches are bounded and the entry loop uses async cache reads."""

    @pytest.mark.asyncio
    async def test_get_balance_is_bounded_by_wait_for(self, monkeypatch):
        """A slow get_balance must time out and not hang the refresh task."""
        import asyncio
        from merid.event_venues.kalshi.bankroll_service_v2 import (
            BankrollServiceV2, _BANKROLL_BALANCE_API_TIMEOUT_S,
        )

        # The default env timeout should be a small, bounded value.
        assert _BANKROLL_BALANCE_API_TIMEOUT_S <= 15.0

        # Patch to a very short value so the test is fast.
        monkeypatch.setattr(
            "merid.event_venues.kalshi.bankroll_service_v2._BANKROLL_BALANCE_API_TIMEOUT_S",
            0.1,
        )

        client = MagicMock()

        # Simulate a get_balance that never returns.
        async def _slow_get_balance():
            await asyncio.sleep(60.0)

        client.get_balance = _slow_get_balance

        service = BankrollServiceV2(client=client, refresh_interval_seconds=1.0)

        with pytest.raises(asyncio.TimeoutError):
            await service._fetch_and_update()

    @pytest.mark.asyncio
    async def test_get_equity_for_risk_calc_async_returns_cached_value(self):
        """The async equity helper must return the cached value without calling get_balance."""
        import asyncio
        from datetime import datetime, timezone
        from decimal import Decimal
        from merid.event_venues.kalshi.bankroll_service_v2 import (
            BankrollServiceV2, get_equity_for_risk_calc_async,
        )
        from merid.event_venues.kalshi.types import InternalBankroll, BalanceState

        client = MagicMock()
        client.get_balance = AsyncMock()

        service = BankrollServiceV2(client=client, refresh_interval_seconds=1.0)
        service._current = InternalBankroll(
            equity_usd=Decimal("1234.56"),
            available_cash_usd=Decimal("1000.00"),
            max_riskable_frac=Decimal("0.02"),
            as_of=datetime.now(timezone.utc),
            source="kalshi",
            state=BalanceState.FRESH,
        )

        # Prime the singleton for the helper.
        from merid.event_venues.kalshi.bankroll_service_v2 import set_bankroll_service
        set_bankroll_service(service)

        try:
            equity = await get_equity_for_risk_calc_async()
            assert equity == 1234.56
            # get_balance should not have been called by the async cache read.
            client.get_balance.assert_not_called()
        finally:
            # Avoid leaking the singleton into other tests.
            from merid.event_venues.kalshi.bankroll_service_v2 import _BANKROLL_SERVICE_V2
            import merid.event_venues.kalshi.bankroll_service_v2 as bsv2
            bsv2._BANKROLL_SERVICE_V2 = None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

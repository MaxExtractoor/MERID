"""Tail-fee realization regression tests.

The /portfolio/settlements ``fee_cost`` field is the exchange's settlement-time
fee (zero for binary markets), not the entry fee.  The settlement poller must
overwrite the API-derived PnL with the fills-ledger cost-basis + fee record so
cheap-tail realized PnL reflects the full cost stack.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from merid.event_venues.kalshi.settlement_poller import (
    KalshiSettlement,
    KalshiSettlementPoller,
    PollerConfig,
    SettlementStatus,
)


class TestTailFeeRealization:
    """Tail-fee realization: settlement PnL must include entry fees."""

    @pytest.fixture
    def poller(self):
        return KalshiSettlementPoller(MagicMock(), PollerConfig())

    def test_hydrate_pnl_from_ledger_overrides_api_pnl(self, poller):
        """A cheap-tail NO position that loses should show PnL = -price - fee."""
        with patch(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger"
        ) as mock_get_ledger:
            ledger = MagicMock()
            # 1 contract held NO at 49c, 2c entry fee, market resolves YES -> lose 51c.
            ledger.get_settlement_pnl_dollars.return_value = Decimal("-0.51")
            mock_get_ledger.return_value = ledger

            settlement = KalshiSettlement(
                market_id="KXBTC15M-TEST-00",
                ticker="KXBTC-15M",
                title="BTC 15m",
                category="crypto",
                status=SettlementStatus.SETTLED,
                settlement_price_cents=100,
                realized_pnl_cents=-49.0,  # API fallback omits entry fee
            )

            corrected = poller._hydrate_pnl_from_ledger(settlement)
            assert corrected.realized_pnl_cents == -51.0
            ledger.get_settlement_pnl_dollars.assert_called_once_with(
                "KXBTC15M-TEST-00", "yes"
            )

    def test_hydrate_pnl_from_ledger_falls_back_when_no_position(self, poller):
        """If the fills ledger has no open position, keep the API-derived PnL."""
        with patch(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger"
        ) as mock_get_ledger:
            ledger = MagicMock()
            ledger.get_settlement_pnl_dollars.return_value = None
            mock_get_ledger.return_value = ledger

            settlement = KalshiSettlement(
                market_id="KXBTC15M-TEST-00",
                ticker="KXBTC-15M",
                title="BTC 15m",
                category="crypto",
                status=SettlementStatus.SETTLED,
                settlement_price_cents=100,
                realized_pnl_cents=-49.0,
            )

            corrected = poller._hydrate_pnl_from_ledger(settlement)
            assert corrected.realized_pnl_cents == -49.0

    def test_hydrate_pnl_from_ledger_ignores_pending_settlements(self, poller):
        """Non-settled markets should not have their PnL overwritten."""
        with patch(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger"
        ) as mock_get_ledger:
            mock_get_ledger.return_value = MagicMock()

            settlement = KalshiSettlement(
                market_id="KXBTC15M-TEST-00",
                ticker="KXBTC-15M",
                title="BTC 15m",
                category="crypto",
                status=SettlementStatus.PENDING,
                realized_pnl_cents=None,
            )

            corrected = poller._hydrate_pnl_from_ledger(settlement)
            assert corrected is settlement
            mock_get_ledger.return_value.get_settlement_pnl_dollars.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

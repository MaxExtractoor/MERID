"""Contract tests for the fail-closed port -> ledger conversion layer.

These tests cover the anti-corruption boundary between the normalized
``KalshiExecutionPort`` DTOs (``Fill``, ``Position``) and the legacy ledger
dicts.  The conversion must:

- preserve source timestamps and identity fields,
- normalize signed NO exposure to canonical side + absolute count,
- fail closed on missing identity/quantity fields,
- exercise partial fills, zero-size positions, cancellations, settled positions,
  and historical records.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.kalshi.port import Fill, Position
from merid.event_venues.kalshi.port_ledger_adapter import (
    port_fill_to_ledger_dict,
    port_position_to_ledger_dict,
    PortLedgerAdapterError,
)


class TestPortFillToLedgerDict:
    """Happy path and edge cases for fill conversion."""

    def test_happy_path_preserves_fields(self):
        ts = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        fill = Fill(
            fill_id="fill-123",
            trade_id="trade-456",
            order_id="order-789",
            client_order_id="client-abc",
            ticker="KXBTC15M-260801",
            side="buy",
            outcome="yes",
            size=Decimal("5"),
            price_cents=55,
            fee_usd=Decimal("0.02"),
            timestamp=ts,
            raw_data={"source": "rest"},
        )

        result = port_fill_to_ledger_dict(fill)

        assert result["fill_id"] == "fill-123"
        assert result["trade_id"] == "trade-456"
        assert result["order_id"] == "order-789"
        assert result["client_order_id"] == "client-abc"
        assert result["market_ticker"] == "KXBTC15M-260801"
        assert result["ticker"] == "KXBTC15M-260801"
        assert result["action"] == "buy"
        assert result["side"] == "yes"
        assert result["outcome_side"] == "yes"
        assert result["count"] == "5"
        assert result["count_fp"] == "5"
        assert result["size"] == "5"
        assert result["price"] == "0.55"
        assert result["price_dollars"] == "0.55"
        assert result["fee"] == "0.02"
        assert result["fee_paid"] == "0.02"
        assert result["timestamp"] == ts.timestamp()
        assert result["created_time"] == ts.timestamp()
        assert result["source"] == "http_poller"
        assert result["raw_data"] == {"source": "rest"}
        assert result["ingested_at"] is not None

    def test_partial_fill(self):
        fill = Fill(
            fill_id="fill-partial",
            order_id="order-x",
            ticker="KXETH15M-260801",
            side="sell",
            outcome="no",
            size=Decimal("3"),
            price_cents=47,
            fee_usd=None,
            timestamp=datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        result = port_fill_to_ledger_dict(fill)
        assert result["count"] == "3"
        assert result["side"] == "no"
        assert result["action"] == "sell"
        assert result["fee"] == "0"  # fee missing is defaulted to "0" for the ledger

    def test_explicit_leg_prices_forwarded(self):
        """Kalshi V2 fills report both yes_price_dollars and no_price_dollars."""
        fill = Fill(
            fill_id="fill-v2",
            order_id="order-v2",
            ticker="KXBTC15M-260802",
            side="sell",
            outcome="no",
            size=Decimal("2"),
            price_cents=38,
            fee_usd=Decimal("0.01"),
            timestamp=datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc),
            raw_data={
                "yes_price_dollars": "0.6200",
                "no_price_dollars": "0.3800",
            },
        )
        result = port_fill_to_ledger_dict(fill)
        assert result["yes_price_dollars"] == "0.6200"
        assert result["no_price_dollars"] == "0.3800"
        # Execution side is NO, so the execution price is the NO leg.
        assert Decimal(result["price"]) == Decimal("0.38")
        assert Decimal(result["price_dollars"]) == Decimal("0.38")

    def test_historical_fill_without_timestamp(self):
        """Historical fills may have no source timestamp; the adapter must not invent one."""
        fill = Fill(
            fill_id="fill-hist",
            order_id="order-y",
            ticker="KXSOL15M-260801",
            side="buy",
            outcome="yes",
            size=Decimal("1"),
            price_cents=60,
            timestamp=None,
        )
        result = port_fill_to_ledger_dict(fill)
        assert result["timestamp"] is None
        assert result["created_time"] is None
        assert result["ingested_at"] is not None

    def test_missing_fill_id_fails_closed(self):
        fill = Fill(
            fill_id="",
            order_id="order-z",
            ticker="KXBTC15M-260801",
            side="buy",
            outcome="yes",
            size=Decimal("1"),
            price_cents=50,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_fill_to_ledger_dict(fill)
        assert exc_info.value.field == "fill_id"

    def test_missing_ticker_fails_closed(self):
        fill = Fill(
            fill_id="fill-abc",
            order_id="order-z",
            ticker="",
            side="buy",
            outcome="yes",
            size=Decimal("1"),
            price_cents=50,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_fill_to_ledger_dict(fill)
        assert exc_info.value.field == "ticker"

    def test_zero_or_negative_size_fails_closed(self):
        for size in [Decimal("0"), Decimal("-1")]:
            fill = Fill(
                fill_id="fill-neg",
                order_id="order-z",
                ticker="KXBTC15M-260801",
                side="buy",
                outcome="yes",
                size=size,
                price_cents=50,
            )
            with pytest.raises(PortLedgerAdapterError) as exc_info:
                port_fill_to_ledger_dict(fill)
            assert exc_info.value.field == "fill.size"

    def test_missing_price_fails_closed(self):
        fill = Fill(
            fill_id="fill-abc",
            order_id="order-z",
            ticker="KXBTC15M-260801",
            side="buy",
            outcome="yes",
            size=Decimal("1"),
            price_cents=None,  # type: ignore[arg-type]
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_fill_to_ledger_dict(fill)
        assert exc_info.value.field == "price_cents"

    @pytest.mark.parametrize("side", ["", "HOLD", "unknown"])
    def test_invalid_side_fails_closed(self, side):
        fill = Fill(
            fill_id="fill-abc",
            order_id="order-z",
            ticker="KXBTC15M-260801",
            side=side,
            outcome="yes",
            size=Decimal("1"),
            price_cents=50,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_fill_to_ledger_dict(fill)
        assert exc_info.value.field == "fill.side"

    @pytest.mark.parametrize("outcome", ["", "maybe", "unknown"])
    def test_invalid_outcome_fails_closed(self, outcome):
        fill = Fill(
            fill_id="fill-abc",
            order_id="order-z",
            ticker="KXBTC15M-260801",
            side="buy",
            outcome=outcome,
            size=Decimal("1"),
            price_cents=50,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_fill_to_ledger_dict(fill)
        assert exc_info.value.field == "fill.outcome"


class TestPortPositionToLedgerDict:
    """Happy path and edge cases for position conversion."""

    def test_happy_path_yes_position(self):
        position = Position(
            ticker="KXBTC15M-260801",
            outcome="yes",
            size=Decimal("10"),
            average_entry_price_cents=54,
            realized_pnl_usd=Decimal("1.20"),
            unrealized_pnl_usd=Decimal("0.50"),
            raw_data={"venue": "kalshi"},
        )
        result = port_position_to_ledger_dict(position)
        assert result["market_ticker"] == "KXBTC15M-260801"
        assert result["ticker"] == "KXBTC15M-260801"
        assert result["side"] == "yes"
        assert result["outcome"] == "yes"
        assert result["contracts"] == 10
        assert result["count"] == 10
        assert result["quantity"] == 10
        assert result["avg_price_cents"] == 54
        assert result["avg_price"] == 54
        assert result["realized_pnl_usd"] == "1.20"
        assert result["unrealized_pnl_usd"] == "0.50"
        assert result["raw_data"] == {"venue": "kalshi"}

    def test_signed_no_exposure_is_normalized(self):
        """Kalshi REST returns negative size for NO positions."""
        position = Position(
            ticker="KXETH15M-260801",
            outcome="",
            size=Decimal("-7"),
            average_entry_price_cents=48,
        )
        result = port_position_to_ledger_dict(position)
        assert result["side"] == "no"
        assert result["contracts"] == 7

    def test_negative_size_with_yes_outcome_flips(self):
        position = Position(
            ticker="KXSOL15M-260801",
            outcome="yes",
            size=Decimal("-3"),
            average_entry_price_cents=61,
        )
        result = port_position_to_ledger_dict(position)
        assert result["side"] == "no"
        assert result["contracts"] == 3

    def test_settled_zero_position(self):
        """A closed position with size 0 should not raise."""
        position = Position(
            ticker="KXXRP15M-260801",
            outcome="yes",
            size=Decimal("0"),
            average_entry_price_cents=0,
        )
        result = port_position_to_ledger_dict(position)
        assert result["contracts"] == 0
        assert result["avg_price_cents"] == 0

    def test_missing_ticker_fails_closed(self):
        position = Position(
            ticker="",
            outcome="yes",
            size=Decimal("1"),
            average_entry_price_cents=50,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_position_to_ledger_dict(position)
        assert exc_info.value.field == "ticker"

    def test_missing_size_fails_closed(self):
        position = Position(
            ticker="KXBTC15M-260801",
            outcome="yes",
            size=None,  # type: ignore[arg-type]
            average_entry_price_cents=50,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_position_to_ledger_dict(position)
        assert exc_info.value.field == "size"

    def test_non_zero_position_missing_outcome_fails_closed(self):
        position = Position(
            ticker="KXBTC15M-260801",
            outcome="",
            size=Decimal("1"),
            average_entry_price_cents=50,
        )
        # size > 0 and empty outcome -> raises (no implied side)
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_position_to_ledger_dict(position)
        assert exc_info.value.field == "outcome"

    def test_non_zero_position_zero_avg_price_fails_closed(self):
        position = Position(
            ticker="KXBTC15M-260801",
            outcome="yes",
            size=Decimal("1"),
            average_entry_price_cents=0,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_position_to_ledger_dict(position)
        assert exc_info.value.field == "average_entry_price_cents"

    def test_invalid_outcome_fails_closed(self):
        position = Position(
            ticker="KXBTC15M-260801",
            outcome="maybe",
            size=Decimal("1"),
            average_entry_price_cents=50,
        )
        with pytest.raises(PortLedgerAdapterError) as exc_info:
            port_position_to_ledger_dict(position)
        assert exc_info.value.field == "outcome"

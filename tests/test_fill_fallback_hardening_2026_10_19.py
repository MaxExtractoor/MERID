"""Regression tests for the 2026-10-19 fill/fallback hardening audit.

Covers:
- fills_ledger missing-action inference must not fire when an authoritative
  cached position exists (restart with cold ledger + live position must not
  record a close as a phantom opening buy).
- The inference still fires for a genuinely flat book (no intent, no prior
  fills, no cached position) so WS fills missing ``action`` are not
  needlessly quarantined.
- BackendPosition preserves fractional counts as Decimal (0.75-contract
  positions must not truncate to an invisible 0).
- BackendPosition rejects malformed side values.
- RiskProjectionEngine counts fractional positions.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# fills_ledger missing-action inference
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def ledger():
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
    return KalshiFillsLedger()


def _orphan_fill(ticker="KXETH15M-FALLBACK-TEST"):
    """A V2 fill with outcome_side but no action and no correlating intent."""
    return {
        "fill_id": f"fill-orphan-{ticker}",
        "market_ticker": ticker,
        "outcome_side": "no",
        "book_side": "ask",
        "side": "no",
        # action deliberately omitted — the unsafe fallback this audit fixed
        "yes_price_dollars": "0.6800",
        "no_price_dollars": "0.3200",
        "count_fp": "1",
        "fee_cost": "0",
        "created_time": datetime.now(timezone.utc).isoformat(),
    }


class TestMissingActionInference:
    @pytest.mark.asyncio
    async def test_infers_buy_only_when_no_position_anywhere(self, ledger):
        """No intent, no prior ledger fills, no cached position -> opening buy."""
        from merid.event_venues.kalshi import position_cache as pc_mod

        ticker = "KXETH15M-FALLBACK-FLAT"
        cache = MagicMock()
        cache.get_position.return_value = None
        with patch.object(pc_mod, "_position_cache_instance", cache):
            fill = ledger._parse_fill(_orphan_fill(ticker), "websocket")

        assert fill is not None
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_position_side == "no"
        assert fill.canonical_yes_delta_cc == -100

    @pytest.mark.asyncio
    async def test_no_buy_inference_when_position_exists(self, ledger):
        """A live cached position means a missing action could be a close —
        leave it unresolved so the fill quarantines instead of recording a
        phantom opening buy."""
        from merid.event_venues.kalshi import position_cache as pc_mod

        ticker = "KXETH15M-FALLBACK-HELD"
        pos = MagicMock()
        pos.quantity_cc = 100  # authoritative non-zero position
        cache = MagicMock()
        cache.get_position.return_value = pos
        with patch.object(pc_mod, "_position_cache_instance", cache):
            fill = ledger._parse_fill(_orphan_fill(ticker), "websocket")

        assert fill is not None
        # Action unresolved -> untrusted canonical effect -> quarantine.
        assert fill.canonical_position_action is None
        assert fill.unmatched is True

    @pytest.mark.asyncio
    async def test_no_cache_instance_falls_back_to_flat_inference(self, ledger):
        """No cache singleton (never instantiated) -> flat-book inference
        keeps the legacy buy default; the parser must not instantiate one."""
        from merid.event_venues.kalshi import position_cache as pc_mod

        ticker = "KXETH15M-FALLBACK-NOCACHE"
        with patch.object(pc_mod, "_position_cache_instance", None):
            fill = ledger._parse_fill(_orphan_fill(ticker), "websocket")
            # The parse must NOT have created a cache to answer the lookup.
            assert pc_mod._position_cache_instance is None

        assert fill is not None
        assert fill.canonical_position_action == "buy"


# ─────────────────────────────────────────────────────────────────────────────
# BackendPosition fractional counts
# ─────────────────────────────────────────────────────────────────────────────


class TestBackendPositionFractional:
    def test_fractional_count_preserved_as_decimal(self):
        from merid.event_venues.kalshi.risk_projection import BackendPosition

        pos = BackendPosition.from_raw(
            {
                "ticker": "KXBTC15M-TEST",
                "side": "yes",
                "count": "0.75",
                "avg_price": "0.55",
                "total_cost": "0.4125",
                "created_at": "2026-10-19T12:00:00Z",
            }
        )
        assert pos.count == Decimal("0.75")
        assert pos.to_dict()["count"] == "0.75"

    def test_fractional_count_not_truncated(self):
        """The pre-fix int() cast turned 0.75 contracts into an invisible 0."""
        from merid.event_venues.kalshi.risk_projection import BackendPosition

        pos = BackendPosition.from_raw(
            {
                "ticker": "KXBTC15M-TEST",
                "side": "no",
                "count": "0.01",
                "avg_price": "0.30",
                "total_cost": "0.003",
            }
        )
        assert pos.count == Decimal("0.01")
        assert pos.count > 0

    def test_invalid_side_rejected(self):
        from merid.event_venues.kalshi.risk_projection import (
            BackendPosition,
            SchemaError,
        )

        with pytest.raises(SchemaError):
            BackendPosition.from_raw(
                {
                    "ticker": "KXBTC15M-TEST",
                    "side": "maybe",
                    "count": "1",
                    "avg_price": "0.50",
                    "total_cost": "0.50",
                }
            )

    def test_missing_count_rejected(self):
        from merid.event_venues.kalshi.risk_projection import (
            BackendPosition,
            SchemaError,
        )

        with pytest.raises(SchemaError):
            BackendPosition.from_raw(
                {
                    "ticker": "KXBTC15M-TEST",
                    "side": "yes",
                    "avg_price": "0.50",
                    "total_cost": "0.50",
                }
            )

    def test_projection_counts_fractional_positions(self):
        from merid.event_venues.kalshi.risk_projection import (
            BackendBalance,
            BackendPosition,
            BackendSnapshot,
            RiskProjectionEngine,
        )

        pos = BackendPosition(
            ticker="KXBTC15M-TEST",
            side="yes",
            count=Decimal("0.75"),
            avg_price_dollars=Decimal("0.55"),
            total_cost_dollars=Decimal("0.4125"),
            unrealized_pnl_dollars=Decimal("0"),
            realized_pnl_dollars=Decimal("0"),
            created_at=datetime.now(timezone.utc),
        )
        snapshot = BackendSnapshot(
            positions=[pos],
            balance=BackendBalance(
                available_usd=Decimal("10"), locked_usd=Decimal("0")
            ),
            fills=[],
            timestamp=datetime.now(timezone.utc),
        )
        projection = RiskProjectionEngine().compute_projection(snapshot)
        assert projection.position_count == 1
        assert projection.total_exposure_dollars == Decimal("0.4125")


# ─────────────────────────────────────────────────────────────────────────────
# client._parse_order degraded-payload surface
# ─────────────────────────────────────────────────────────────────────────────


class TestOrderParseDegradedPayload:
    def test_degraded_order_logs_and_defaults(self, caplog):
        """A payload with no action/book_side/outcome must not crash; the
        'buy' placeholder is kept for consumer sign-math compatibility but the
        degradation is logged for audit."""
        from merid.event_venues.kalshi.client import KalshiVenueClient

        client = KalshiVenueClient.__new__(KalshiVenueClient)
        raw = {
            "order_id": "ord-degraded-1",
            "ticker": "KXBTC15M-DEGRADED",
            "count_fp": "1.0",
            "status": "resting",
        }
        import logging

        with caplog.at_level(logging.WARNING):
            order = client._to_placed_order(raw)

        assert order is not None
        assert order.side == "buy"  # placeholder preserved for compat
        assert any("ORDER-PARSE-DEGRADED" in r.message for r in caplog.records)

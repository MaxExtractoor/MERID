"""
Regression tests for the 2026-09-24 "immediate loss exit" inversion.

Live incident: a BUY NO@70c entry was sold at SELL NO@60c ~22s later for a
real loss, and the local position cache briefly held a phantom 1.9-contract
NO position with a YES-space 31c basis that read +51.3c unrealized PnL.

Root causes fixed:
1. ``eps.entry_fill_price_cents`` persisted the raw execution-side price
   (YES leg) for counterparty-form fills, poisoning the monitor's entry basis
   for NO positions.  It must persist the position-side (held outcome) price.
2. Edge-realization (``current >= model_fair``) fired on UNDERWATER
   convergence — the model's fair value fell to a falling bid and the
   position was cut <1s after entry at a locked-in loss.  Edge-realization
   is a profit capture and now requires ``unrealized_pnl_cents > 0``;
   underwater invalidation is deferred to EDGE_DECAY (hold + confirmations).
"""

import asyncio
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
    OrderIntent,
)
from merid.event_venues.kalshi.position_cache import (
    KalshiPositionCache,
    ENTRY_PROVENANCE_AVAILABLE,
)
from merid.position_management.position import Position, PositionSide
from merid.position_management.position_monitor import PositionMonitor


@pytest.fixture(autouse=True)
async def _clear_cache(monkeypatch):
    """Reset the singleton cache and neutralize environment checks."""
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_expired_ticker", lambda t: False)
    monkeypatch.setattr("merid.event_venues.kalshi.position_cache._is_test_ticker", lambda t: False)
    cache = KalshiPositionCache()
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0
    yield
    await cache.clear()
    cache._last_sync = None
    cache._last_rest_sync_timestamp = 0.0


class TestEntryProvenancePositionSidePrice:
    """Counterparty-form fills must persist the held-side price as entry basis."""

    @pytest.mark.asyncio
    async def test_sell_yes_form_buy_no_persists_no_leg_as_basis(self):
        """A BUY NO fill reported as SELL YES@31 must write 69c, not 31c."""
        if not ENTRY_PROVENANCE_AVAILABLE:
            pytest.skip("entry provenance store unavailable")

        from merid.event_venues.kalshi.position_cache import (
            EntryProvenanceSnapshot,
            get_entry_provenance_store,
        )

        cache = KalshiPositionCache()
        market_id = "KXXRP15M-INVERSION-NO"
        client_order_id = "test-inv-no-01"

        store = get_entry_provenance_store()
        snapshot = EntryProvenanceSnapshot(
            snapshot_id="snap-inv-no-01",
            client_order_id=client_order_id,
            ticker=market_id,
            asset="XRP",
            outcome_side="no",
        )
        store.register(snapshot)

        # Counterparty-form fill: exchange reports SELL YES@31 for a BUY NO.
        await cache.on_fill(
            market_id=market_id,
            contracts=1,
            quantity_cc=90,
            price_cents=31,
            fee_cents=0,
            side="yes",
            action="sell",
            client_order_id=client_order_id,
            fill_id="fill-inv-no-01",
            is_exit=False,
            canonicalization_state="TRUSTED_LIVE_V1",
            yes_price_cents=31,
            no_price_cents=69,
        )

        pos = cache._positions[market_id]
        # The fresh signed position is long NO at the NO leg price.
        assert pos.side == "no"
        assert pos.avg_price_cents == 69

        # The durable provenance basis must be the NO-space price too —
        # 31c here produced the phantom +51.3c PnL that triggered the bad exit.
        eps = store.get(client_order_id)
        assert eps.entry_fill_price_cents == 69, (
            f"provenance basis must be NO-space 69c, got {eps.entry_fill_price_cents}"
        )


class TestEdgeRealizationProfitGate:
    """Edge-realization may only fire while the position is in profit."""

    def _monitor(self) -> PositionMonitor:
        return PositionMonitor()

    def _position(self, **kwargs) -> Position:
        entry_price = kwargs.get("avg_entry_price_cents", 50)
        defaults = {
            "risk_params_state": "original_persisted",
            "risk_params_schema_version": 2,
            "client_order_id": "test-client",
            "entry_fill_id": "test-fill",
            "fill_source": "test",
            "entry_book_capture_quality": "AT_FILL",
            "entry_executable_bid_cents": entry_price - 1,
            "entry_executable_ask_cents": entry_price + 1,
            "entry_fill_price_cents": entry_price,
        }
        defaults.update(kwargs)
        return Position(**defaults)

    def _stub_fair_value(self, monkeypatch, fair_cents: int):
        """Point the monitor's fair-value lookup at a fixed value."""
        monkeypatch.setattr(
            "merid.position_management.position_monitor._get_fair_value_cents",
            lambda state, held: fair_cents,
        )
        # 2026-10-05: the monitor now anchors discretionary exits on the MODEL
        # fair only (_get_model_fair_value_cents); the implied_prob fallback is
        # not consulted.  Stub both so the fixed value reaches the gate.
        monkeypatch.setattr(
            "merid.position_management.position_monitor._get_model_fair_value_cents",
            lambda state, held: fair_cents,
        )
        # 2026-09-25: loss/thesis exit candidates are EV-gated by the
        # settlement evaluator (_LOSS_EXIT_EV_GATED_REASONS), which needs a
        # live book state this class does not provide.  These tests exercise
        # the trigger-level profit/underwater gate itself; disable the EV
        # layer so trigger semantics are what is asserted.
        monkeypatch.setenv("MERID_LOSS_EXIT_EV_GATE", "0")
        # The lookup requires a non-None unified/kalshi market state.
        stub_state = SimpleNamespace()
        stub_store = SimpleNamespace(
            get_unified=lambda market_id: stub_state,
            get=lambda market_id: stub_state,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
            lambda: stub_store,
        )

    def test_underwater_convergence_does_not_exit(self, monkeypatch):
        """NO@70 entry, bid 62, model fair 50 (NO space): bid >= fair holds but
        the position is underwater — the loss lock must be suppressed."""
        monitor = self._monitor()
        self._stub_fair_value(monkeypatch, 50)  # fair_no=50 <= bid 62

        callback = Mock()
        monitor.register_exit_intent_callback(callback)

        position = self._position(
            market_id="KXXRP15M-INV-UW",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=70,
            all_in_entry_basis_cents=70,
        )
        monitor.add_position(position)

        result = asyncio.run(monitor._legacy_check_position(position, 62))

        # No CURRENT_EDGE_REVERSAL candidate may be emitted underwater.
        from merid.position_management.exit_policy import ExitReason
        assert result is None or result.reason != ExitReason.CURRENT_EDGE_REVERSAL
        callback.assert_not_called()

    def test_in_profit_convergence_still_exits(self, monkeypatch):
        """The profit path is preserved: bid >= fair while in profit still
        produces the edge-realization candidate."""
        monitor = self._monitor()
        self._stub_fair_value(monkeypatch, 55)

        # Prevent the emitted intent from touching external systems.
        emitted = []

        async def _capture(position, reason, exit_price_cents, **kwargs):
            emitted.append((reason, exit_price_cents))

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)

        position = self._position(
            market_id="KXBTC15M-INV-TP",
            series_ticker="KXBTC15M",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            all_in_entry_basis_cents=50,
            # Lift the auto-derived TP above the test bid so the resolver does
            # not prefer TAKE_PROFIT (priority 55) over CURRENT_EDGE_REVERSAL.
            take_profit_price_cents=80,
        )
        monitor.add_position(position)

        result = asyncio.run(monitor._legacy_check_position(position, 62))

        from merid.position_management.exit_policy import ExitReason
        assert result is not None
        assert result.reason == ExitReason.CURRENT_EDGE_REVERSAL
        assert emitted and emitted[0][0] == ExitReason.CURRENT_EDGE_REVERSAL


class TestCounterpartyFormCanonicalization:
    """The REST /fills payload reports fills in book/counterparty form.

    For the 2026-09-24 incident the BUY_NO entry's fills arrived over REST as
    ``action=sell side=no`` (book-side encoding, ask->no).  Adopting the
    reported action verbatim produced ``no/sell`` (+YES delta) — the opposite
    of the user's BUY_NO intent — and opened a phantom position on restart.
    When the execution form's signed delta disagrees with the recorded
    intent's, the canonical effect must follow the intent.
    """

    @pytest.fixture
    async def ledger(self, monkeypatch, tmp_path):
        db_path = tmp_path / "kalshi_fills.db"
        monkeypatch.setenv("MERID_FILLS_DB_PATH", str(db_path))
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
        KalshiFillsLedger._initialized = False
        KalshiFillsLedger._instance = None
        l = KalshiFillsLedger()
        l._fills = {}
        l._intents = {}
        l._fills_by_order = {}
        l._fills_by_market = {}
        yield l
        await l.shutdown()
        KalshiFillsLedger._initialized = False
        KalshiFillsLedger._instance = None

    def _intent(self, ledger, side="no", action="buy", entry_or_exit="entry"):
        intent = OrderIntent(
            intent_id="intent_cp_001",
            ticker="KXXRP15M-TEST",
            side=side,
            action=action,
            count=100,
            price_cents=70,
            client_order_id="co_cp_001",
            order_id="ord_cp_001",
            entry_or_exit=entry_or_exit,
            reduce_only=(entry_or_exit == "exit"),
        )
        ledger.record_intent(intent)
        return intent

    def _rest_form_raw(self, fill_id="fill_cp_001"):
        # The exact REST form from production: action=sell side=no for a
        # taker BUY_NO fill (book-side encoding, is_taker=True).
        return {
            "fill_id": fill_id,
            "trade_id": fill_id,
            "order_id": "ord_cp_001",
            "client_order_id": "co_cp_001",
            "market_ticker": "KXXRP15M-TEST",
            "ticker": "KXXRP15M-TEST",
            "action": "sell",
            "side": "no",
            "outcome_side": "no",
            "book_side": "ask",
            "count_fp": "0.90",
            "yes_price_dollars": "0.30",
            "no_price_dollars": "0.70",
            "fee_cost": "0.0133",
            "is_taker": True,
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

    @pytest.mark.asyncio
    async def test_sell_no_form_on_buy_no_intent_canonicalizes_to_intent(self, ledger):
        """REST 'sell no@70' on a buy-no intent -> canonical no/buy, delta -90,
        proceeds paid at the NO leg (-0.63 - fee), never a phantom +delta."""
        self._intent(ledger, side="no", action="buy")
        fill = ledger._parse_fill(self._rest_form_raw(), "http_poller")

        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == -90
        assert fill.canonical_leg_price_cents == 70
        assert fill.canonicalization_state == "TRUSTED_LIVE_V1"
        assert fill.unmatched is not True
        # User paid for NO@70 on 0.9 contracts + fee.
        assert fill.proceeds_dollars == pytest.approx(Decimal("-0.6433"), abs=Decimal("0.001"))

    @pytest.mark.asyncio
    async def test_sell_yes_form_on_buy_no_intent_unaffected(self, ledger):
        """WS-form 'sell yes@30' already yields the intent's delta (-90); the
        counterparty override must not disturb it."""
        self._intent(ledger, side="no", action="buy")
        raw = self._rest_form_raw("fill_cp_ws")
        raw["side"] = "yes"
        raw["outcome_side"] = "yes"
        raw["book_side"] = "bid"
        fill = ledger._parse_fill(raw, "ws")

        # Deltas agree (-90 == -90): no override, execution form preserved.
        assert fill.canonical_position_side == "yes"
        assert fill.canonical_position_action == "sell"
        assert fill.canonical_yes_delta_cc == -90

    @pytest.mark.asyncio
    async def test_counterparty_form_exit_fill(self, ledger):
        """Maker-form 'buy no@60' on a sell-no exit intent -> canonical
        no/sell, +delta (closes the long NO position)."""
        self._intent(ledger, side="no", action="sell", entry_or_exit="exit")
        raw = self._rest_form_raw("fill_cp_exit")
        raw["action"] = "buy"
        raw["side"] = "no"
        raw["outcome_side"] = "no"
        raw["book_side"] = "ask"
        raw["yes_price_dollars"] = "0.40"
        raw["no_price_dollars"] = "0.60"
        fill = ledger._parse_fill(raw, "http_poller")

        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "sell"
        assert fill.canonical_yes_delta_cc == 90
        # No prior NO holding in this fixture: the sell is modeled as a
        # pair-mint — user pays the complement YES leg (0.9 * 0.40 - fee).
        assert fill.proceeds_dollars == pytest.approx(Decimal("-0.3733"), abs=Decimal("0.001"))

"""Regression: REST-covered entry fills must still give a position exit
parentage (2026-10-28 audit).

Observed live on KXDOGE15M-26OCT281300-00 (6x NO@90, settled YES, -540c):

  - The maker entry rested 43s and filled at 16:51:58Z.  Kalshi credited the
    position instantly, so the 16:52:01 REST positions snapshot created a
    ``rest_sync`` cache record before the http_poller ingest reached the
    canonical fill.
  - The next sync marked the ledger fill "covered by REST" in
    ``_applied_fill_ids``, so ``on_fill`` never ran its covered-fill
    provenance migration; ``rehydrate_cached_position`` could not help
    either because the pinned_fav lane registers no entry-policy snapshot.
  - The monitor position stayed SIGNAL_ONLY with no ``entry_fill_id`` /
    ``entry_order_id`` / ``entry_intent_id`` / ``client_order_id``, so
    ``context_from_position`` returned ``None`` and no arbiter attempt was
    ever minted.  All 13 hard_profit_lock exits over ~70s (NO bid 91-96c)
    were router-rejected ``exit_arbiter:no_approved_attempt`` and the
    position rode to settlement.
  - Fleet check: 191 SIGNAL_ONLY exit attempts across BTC/ETH/SOL/XRP/DOGE
    produced 0 fills; all 32 filled exits were CANONICAL_FILL parentage.

Fixed contract pinned here:

  1. ``sync_from_rest`` coverage marking restores linkage on unlinked
     positions from covered entry fills (the provenance a REST snapshot
     cannot carry), mirroring the ``on_fill`` covered-path migration.
  2. ``_generation_id_of`` falls back through the full durable chain —
     order id, signal id (non-sentinel), then a ``position:``-scoped id —
     so a position that is genuinely unlinked still gets an arbiter
     context instead of a guaranteed router rejection.
  3. Parentage stays honest: a restored/fallback generation never
     promotes a signal or position id into ``entry_fill_id``/parentage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from merid.position_management.exit_pipeline import (
    _generation_id_of,
    approve_intent,
    context_from_position,
)
from merid.position_management.exit_arbiter import (
    AttemptState,
    ExitArbiter,
    ExitAttemptStore,
    ExitBook,
)
from merid.position_management.position_exit_state import (
    PositionExitStateStore,
)
from merid.event_venues.kalshi.position_cache import (
    _backfill_entry_risk_contract,
    _backfill_linkage_from_covered_fills,
    _select_covered_entry_fill,
)


# ---------------------------------------------------------------------------
# _generation_id_of / context_from_position fallback chain
# ---------------------------------------------------------------------------

class TestGenerationIdFallback:
    def test_canonical_fill_id_wins(self):
        pos = SimpleNamespace(
            entry_fill_id="fill-abc", client_order_id="merid_x",
            entry_signal_id="sig_y", position_id="KXBTC15M-T",
            market_id="KXBTC15M-T",
        )
        assert _generation_id_of(pos) == "fill-abc"

    def test_entry_order_id_used_when_fill_ids_missing(self):
        pos = SimpleNamespace(
            entry_fill_id=None, entry_intent_id=None, client_order_id=None,
            entry_order_id="ord-123", entry_signal_id="rest_sync",
            position_id="KXBTC15M-T", market_id="KXBTC15M-T",
        )
        assert _generation_id_of(pos) == "ord-123"

    def test_signal_id_used_when_non_sentinel(self):
        pos = SimpleNamespace(
            entry_fill_id=None, entry_intent_id=None, client_order_id=None,
            entry_order_id=None, entry_signal_id="sig-real-1",
            position_id="KXBTC15M-T", market_id="KXBTC15M-T",
        )
        assert _generation_id_of(pos) == "sig-real-1"

    def test_sentinel_signal_falls_through_to_position_id(self):
        """The 'rest_sync' marker must never be promoted into a generation —
        the position-scoped fallback is honest and still position-unique."""
        pos = SimpleNamespace(
            entry_fill_id=None, entry_intent_id=None, client_order_id=None,
            entry_order_id=None, entry_signal_id="rest_sync",
            position_id="KXDOGE15M-26OCT281300-00",
            market_id="KXDOGE15M-26OCT281300-00",
        )
        assert _generation_id_of(pos) == "position:KXDOGE15M-26OCT281300-00"

    def test_market_id_last_resort(self):
        """CachedPosition-style records carry market_id but no position_id."""
        pos = SimpleNamespace(
            entry_fill_id=None, entry_intent_id=None, client_order_id=None,
            entry_order_id=None, entry_signal_id=None,
            market_id="KXETH15M-26OCT281200-00",
        )
        assert _generation_id_of(pos) == "position:KXETH15M-26OCT281200-00"

    def test_truly_empty_position_returns_none(self):
        pos = SimpleNamespace(
            entry_fill_id=None, entry_intent_id=None, client_order_id=None,
            entry_order_id=None, entry_signal_id=None,
            position_id=None, market_id=None,
        )
        assert _generation_id_of(pos) is None


class TestOrphanedPositionExitE2E:
    """An orphaned (SIGNAL_ONLY) position must still mint an arbiter attempt
    that satisfies the router's token gate — the exact gate that rejected all
    13 DOGE exits live."""

    def _arbiter(self, tmp_path) -> ExitArbiter:
        return ExitArbiter(
            state_store=PositionExitStateStore(tmp_path / "exit_state.json"),
            attempt_store=ExitAttemptStore(tmp_path / "exit_attempts.json"),
        )

    def _orphan_position(self):
        return SimpleNamespace(
            market_id="KXDOGE15M-26OCT281300-00",
            position_id="KXDOGE15M-26OCT281300-00",
            side="no",
            size=6,
            avg_entry_price_cents=90,
            entry_fill_id=None,
            parent_entry_fill_id=None,
            entry_order_id=None,
            entry_intent_id=None,
            client_order_id=None,
            entry_signal_id="rest_sync",
            fill_source="rest_sync",
            trailing_param=None,
        )

    def test_orphan_gets_context_and_approved_attempt(self, tmp_path):
        pos = self._orphan_position()
        ctx = context_from_position(pos, remaining_cc=600)
        assert ctx is not None
        assert ctx.generation_id == "position:KXDOGE15M-26OCT281300-00"

        arb = self._arbiter(tmp_path)
        intent = SimpleNamespace(
            intent_id="intent_exit_orphan1",
            price_cents=92,
            count=6, count_fp=6, qty_cc=None,
            exit_reason="hard_profit_lock", reason="exit:hard_profit_lock",
            source="position_monitor_exit", agent_id="DOGE_15M",
            exit_class=None, emergency_type=None,
            authorization_source="position_monitor",
            position_generation_id=None, exit_attempt_id=None,
        )
        prepared = approve_intent(intent, ctx, issuer="position_monitor",
                                  arbiter=arb)
        assert prepared.approved is True
        assert intent.exit_attempt_id
        assert intent.position_generation_id == ctx.generation_id

        # Router-side gate: same key construction as order_router.
        key = f"KXDOGE15M-26OCT281300-00|{intent.position_generation_id}"
        attempt = arb.validate_attempt_token(key, intent.exit_attempt_id)
        assert attempt is not None
        assert attempt.state == AttemptState.SUBMITTING

    def test_canonical_fill_parentage_unchanged(self, tmp_path):
        """Positions with a real entry fill keep their fill generation —
        the fallback never displaces honest parentage."""
        pos = self._orphan_position()
        pos.entry_fill_id = "07278edf-8911-8eaa-25aa-f302e089abc1"
        ctx = context_from_position(pos, remaining_cc=600)
        assert ctx is not None
        assert ctx.generation_id == "07278edf-8911-8eaa-25aa-f302e089abc1"


# ---------------------------------------------------------------------------
# sync_from_rest covered-fill linkage backfill
# ---------------------------------------------------------------------------

def _fill(fill_id="f1", created=None, *, is_exit=False, delta=-600,
          coid="merid_2448d28fb8e94099a62b",
          order="01a1836c-47d0-7114-af94-afe21c9df001",
          intent="intent_ea782076f2d64e22b41946beca460cf5"):
    return SimpleNamespace(
        fill_id=fill_id,
        created_time=created or datetime(2026, 10, 28, 16, 51, 58,
                                         tzinfo=timezone.utc),
        is_exit=is_exit,
        canonical_yes_delta_cc=delta,
        canonical_position_side="yes",
        canonical_position_action="sell",
        side="yes", action="sell",
        quantity_cc=600,
        client_order_id=coid, order_id=order, intent_id=intent,
        canonical_leg_price_cents=10,
        yes_price_dollars=None, no_price_dollars=None,
        price_cents=10,
    )


def _pos(**kw):
    defaults = dict(
        market_id="KXDOGE15M-26OCT281300-00",
        entry_fill_id=None, client_order_id=None, entry_order_id=None,
        entry_intent_id=None, entry_signal_id="rest_sync",
        entry_fill_price_cents=None, entry_fill_timestamp=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestCoveredFillLinkageBackfill:
    def test_backfills_from_covered_entry_fill(self):
        pos = _pos()
        fills = [_fill()]
        assert _backfill_linkage_from_covered_fills(pos, fills, -600) is True
        assert pos.entry_fill_id == "f1"
        assert pos.client_order_id == "merid_2448d28fb8e94099a62b"
        assert pos.entry_order_id == "01a1836c-47d0-7114-af94-afe21c9df001"
        assert pos.entry_intent_id == "intent_ea782076f2d64e22b41946beca460cf5"
        assert pos.entry_signal_id == "merid_2448d28fb8e94099a62b"
        assert pos.entry_fill_timestamp is not None

    def test_skips_exit_fills(self):
        """A covered exit fill must never be stamped as the entry."""
        pos = _pos()
        fills = [_fill(is_exit=True)]
        assert _backfill_linkage_from_covered_fills(pos, fills, -600) is False
        assert pos.entry_fill_id is None

    def test_skips_opposite_sign_fills(self):
        """A fill that does not open the held side is not the entry."""
        pos = _pos()
        fills = [_fill(delta=+600)]
        assert _backfill_linkage_from_covered_fills(pos, fills, -600) is False
        assert pos.entry_fill_id is None

    def test_never_overwrites_existing_linkage(self):
        pos = _pos(client_order_id="merid_original")
        fills = [_fill()]
        assert _backfill_linkage_from_covered_fills(pos, fills, -600) is False
        assert pos.client_order_id == "merid_original"
        assert pos.entry_fill_id is None

    def test_latest_opening_fill_wins(self):
        """Among covered same-direction fills the most recent is the current
        position's entry — positions are serial per market, so an earlier
        one belongs to a prior (already-closed) position."""
        pos = _pos()
        late = datetime(2026, 10, 28, 16, 53, 0, tzinfo=timezone.utc)
        fills = [_fill(fill_id="f_late", created=late),
                 _fill(fill_id="f_early")]
        assert _backfill_linkage_from_covered_fills(pos, fills, -600) is True
        assert pos.entry_fill_id == "f_late"

    def test_reentry_prior_position_fill_not_stolen(self):
        """Re-entry race: covered fills contain a prior position's entry +
        exit plus the current position's entry.  The backfill must stamp the
        current entry, not resurrect the prior position's provenance."""
        pos = _pos()
        t1 = datetime(2026, 10, 28, 16, 30, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 28, 16, 31, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 28, 16, 33, 0, tzinfo=timezone.utc)
        fills = [
            _fill(fill_id="f_prior_entry", created=t1, delta=-300),
            _fill(fill_id="f_prior_exit", created=t2, delta=+300,
                  is_exit=True),
            _fill(fill_id="f_current_entry", created=t3, delta=-600,
                  coid="merid_cur", order="ord_cur", intent="intent_cur"),
        ]
        assert _backfill_linkage_from_covered_fills(pos, fills, -600) is True
        assert pos.entry_fill_id == "f_current_entry"
        assert pos.client_order_id == "merid_cur"

    def test_zero_exposure_no_backfill(self):
        pos = _pos()
        assert _backfill_linkage_from_covered_fills(
            pos, [_fill()], 0) is False

    def test_sentinel_signal_replaced_only_by_real_coid(self):
        pos = _pos()
        fill_no_coid = _fill(coid=None)
        assert _backfill_linkage_from_covered_fills(
            pos, [fill_no_coid], -600) is True
        # fill_id still restores (fill linkage is the durable anchor),
        # but the 'rest_sync' signal marker is left untouched when the fill
        # carries no client_order_id of its own.
        assert pos.entry_fill_id == "f1"
        assert pos.entry_signal_id == "rest_sync"


# ---------------------------------------------------------------------------
# risk-contract restore (no-edge tail-loss salvage eligibility)
# ---------------------------------------------------------------------------
#
# The same REST-coverage race stripped ``entry_authorized_net_edge_c`` — the
# persisted authorized net claim the no-edge salvage discriminator needs.
# The durable claim lives in strategy_decision_side_ev keyed by the fill's
# decision_trace_id.

_CLAIMS = {
    "side": "no", "selected": 1, "decision_lane": "pinned_fav",
    "gate_ev_cents": -3.976, "expected_net_ev_cents": -3.976,
    "gross_edge_cents": 2.188, "enforced_edge_bound_cents": -12.0,
    "executable_entry_price_cents": 90, "calibrated_probability": 0.9219,
}


class _FakeAudit:
    def __init__(self, claims=None):
        self._claims = claims
        self.calls = []

    def get_side_ev_claims(self, decision_id, side):
        self.calls.append((decision_id, side))
        return self._claims


def _fill_with_trace(**kw):
    f = _fill(**kw)
    f.decision_trace_id = "cand_3a88c7373f41108cbe85f861:maker_bid"
    return f


def _contract_pos(**kw):
    defaults = dict(
        entry_authorized_net_edge_c=None, no_edge_salvage_eligible=None,
        decision_lane=None,
    )
    defaults.update(kw)
    return _pos(**defaults)


class TestEntryRiskContractRestore:
    def test_restores_contract_from_decision_audit(self, monkeypatch):
        import merid.execution.decision_audit_ledger as dal
        audit = _FakeAudit(dict(_CLAIMS))
        monkeypatch.setattr(dal, "get_decision_audit_ledger", lambda: audit)

        pos = _contract_pos()
        fills = [_fill_with_trace()]
        assert _backfill_entry_risk_contract(pos, fills, -600) is True
        assert pos.entry_authorized_net_edge_c == -3.976
        assert pos.entry_authorized_net_edge_source == (
            "decision_audit:strategy_decision_side_ev")
        assert pos.entry_gross_edge_c == 2.188
        assert pos.entry_admission_lane == "pinned_fav"
        assert pos.entry_effective_threshold_c == -12.0
        assert pos.risk_decision_id == "cand_3a88c7373f41108cbe85f861:maker_bid"
        assert pos.net_claim_state == "KNOWN_NONPOSITIVE"
        assert pos.no_edge_salvage_eligible is True
        assert pos.decision_lane == "pinned_fav"
        # Lookup used the held side (NO position -> side='no').
        assert audit.calls == [("cand_3a88c7373f41108cbe85f861:maker_bid", "no")]

    def test_never_overwrites_existing_contract(self, monkeypatch):
        import merid.execution.decision_audit_ledger as dal
        audit = _FakeAudit(dict(_CLAIMS))
        monkeypatch.setattr(dal, "get_decision_audit_ledger", lambda: audit)

        pos = _contract_pos(entry_authorized_net_edge_c=-7.5)
        assert _backfill_entry_risk_contract(
            pos, [_fill_with_trace()], -600) is False
        assert pos.entry_authorized_net_edge_c == -7.5
        assert audit.calls == []  # no lookup attempted

    def test_no_lookup_without_trace_id(self, monkeypatch):
        import merid.execution.decision_audit_ledger as dal
        audit = _FakeAudit(dict(_CLAIMS))
        monkeypatch.setattr(dal, "get_decision_audit_ledger", lambda: audit)

        pos = _contract_pos()
        fill = _fill()  # no decision_trace_id
        assert _backfill_entry_risk_contract(pos, [fill], -600) is False
        assert audit.calls == []

    def test_missing_claims_row_leaves_position_untouched(self, monkeypatch):
        import merid.execution.decision_audit_ledger as dal
        audit = _FakeAudit(None)
        monkeypatch.setattr(dal, "get_decision_audit_ledger", lambda: audit)

        pos = _contract_pos()
        assert _backfill_entry_risk_contract(
            pos, [_fill_with_trace()], -600) is False
        assert pos.entry_authorized_net_edge_c is None
        assert pos.no_edge_salvage_eligible is None

    def test_select_covered_entry_fill_picks_latest_same_direction(self):
        t1 = datetime(2026, 10, 28, 16, 30, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 28, 16, 31, 0, tzinfo=timezone.utc)
        t3 = datetime(2026, 10, 28, 16, 33, 0, tzinfo=timezone.utc)
        fills = [
            _fill(fill_id="f_prior_entry", created=t1, delta=-300),
            _fill(fill_id="f_prior_exit", created=t2, delta=+300,
                  is_exit=True),
            _fill(fill_id="f_current_entry", created=t3, delta=-600),
        ]
        pick = _select_covered_entry_fill(fills, -600)
        assert pick is not None and pick.fill_id == "f_current_entry"


# ---------------------------------------------------------------------------
# record_settlement fills-ledger fallback (2026-10-28 attribution gap)
# ---------------------------------------------------------------------------

class _LedgerFill:
    def __init__(self, **kw):
        self.is_exit = False
        self.intent_id = "intent_live"
        self.fill_id = "fill_live"
        self.fill_source = "canonical"
        self.count_fp = "6.00"
        self.canonical_yes_delta_cc = -600
        self.yes_price_dollars = 0.10
        self.no_price_dollars = 0.90
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeLedger:
    def __init__(self, fills):
        self._fills = fills

    def get_fills_by_market(self, ticker):
        return self._fills


def _make_attribution_table():
    from merid.monitoring.trade_attribution_fact_table import TradeAttributionTable
    return TradeAttributionTable(db_path=r"data\_test_attr_fallback.db")


def _queued_settlement_row(table):
    import json as _json
    row = table._queue[-1]
    row = dict(row)
    row["metadata"] = _json.loads(row["metadata"])
    return row


class TestSettlementFillsLedgerFallback:
    def test_missing_position_joins_ledger(self, monkeypatch):
        """position=None (pre-fix orphan path): settlement row must still
        carry intent_id / avg_price / fill_source from the fills ledger."""
        import merid.event_venues.kalshi.fills_ledger as fl
        monkeypatch.setattr(
            fl, "get_fills_ledger", lambda: _FakeLedger([_LedgerFill()]))
        t = _make_attribution_table()
        t.record_settlement(
            "KXDOGE15M-26OCT281300-00", "yes", position=None,
            realized_pnl_cents=-540)
        row = _queued_settlement_row(t)
        assert row["intent_id"] == "intent_live"
        assert row["side"] == "no"          # negative yes-delta -> NO entry
        assert row["metadata"]["avg_price_cents"] == 90
        assert row["metadata"]["entry_intent_id"] == "intent_live"
        assert row["metadata"]["fill_source"] == "canonical"
        assert row["metadata"]["entry_fill_id"] == "fill_live"
        assert row["metadata"]["linkage_source"] == "fills_ledger"

    def test_orphaned_position_uses_ledger_linkage(self, monkeypatch):
        """A position present but unlinked (all entry ids None) heals the
        same way - position fields still win where populated."""
        import merid.event_venues.kalshi.fills_ledger as fl
        monkeypatch.setattr(
            fl, "get_fills_ledger", lambda: _FakeLedger([_LedgerFill()]))
        pos = SimpleNamespace(
            entry_intent_id=None, entry_fill_id=None, client_order_id=None,
            side="no", contracts=6.0, avg_price_cents=90,
            fill_source="rest_sync")
        t = _make_attribution_table()
        t.record_settlement(
            "KXDOGE15M-26OCT281300-00", "yes", position=pos,
            realized_pnl_cents=-540)
        row = _queued_settlement_row(t)
        assert row["intent_id"] == "intent_live"
        assert row["count_fp"] == "6.0"     # position field wins
        assert row["metadata"]["avg_price_cents"] == 90
        assert row["metadata"]["fill_source"] == "rest_sync"
        assert row["metadata"]["linkage_source"] == "fills_ledger"

    def test_linked_position_never_queries_ledger(self, monkeypatch):
        import merid.event_venues.kalshi.fills_ledger as fl
        calls = []
        class _Probe:
            def get_fills_by_market(self, ticker):
                calls.append(ticker); return [_LedgerFill()]
        monkeypatch.setattr(fl, "get_fills_ledger", lambda: _Probe())
        pos = SimpleNamespace(
            entry_intent_id="intent_pos", entry_fill_id="fill_pos",
            client_order_id="merid_pos", side="no", contracts=6.0,
            avg_price_cents=90, fill_source="canonical")
        t = _make_attribution_table()
        t.record_settlement(
            "KXDOGE15M-26OCT281300-00", "yes", position=pos,
            realized_pnl_cents=-540)
        row = _queued_settlement_row(t)
        assert calls == []
        assert row["intent_id"] == "intent_pos"
        assert row["metadata"]["linkage_source"] == "position"

    def test_yes_side_entry_price_from_yes_leg(self, monkeypatch):
        import merid.event_venues.kalshi.fills_ledger as fl
        monkeypatch.setattr(fl, "get_fills_ledger", lambda: _FakeLedger(
            [_LedgerFill(canonical_yes_delta_cc=+600,
                         yes_price_dollars=0.92, no_price_dollars=0.08)]))
        t = _make_attribution_table()
        t.record_settlement("KXBTC15M-26OCT281300-00", "yes", position=None,
                            realized_pnl_cents=48)
        row = _queued_settlement_row(t)
        assert row["side"] == "yes"
        assert row["metadata"]["avg_price_cents"] == 92

    def test_no_ledger_rows_still_writes_row(self, monkeypatch):
        """No fills at all -> row still written, linkage_source None."""
        import merid.event_venues.kalshi.fills_ledger as fl
        monkeypatch.setattr(fl, "get_fills_ledger", lambda: _FakeLedger([]))
        t = _make_attribution_table()
        t.record_settlement("KXXXX-UNKNOWN", "no", position=None,
                            realized_pnl_cents=-90)
        row = _queued_settlement_row(t)
        assert row["ticker"] == "KXXXX-UNKNOWN"
        assert row["metadata"]["linkage_source"] is None
        assert row["intent_id"] is None

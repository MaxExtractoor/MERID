"""Tail-loss floor must route as LOSS_CAP, not HARD_STOP.

2026-10-19 incident: the position monitor's catastrophic tail-loss floor
(``MERID_TAIL_LOSS_DROP_CENTS``/``FLOOR_CENTS`` salvage) emitted
``trigger_reason="HARD_STOP"`` candidates.  The 2026-10-17 price-stop
shadow freeze puts ``HARD_STOP`` in ``SHADOWED_PRICE_STOP_TRIGGERS`` —
record-only, never submitted — so every tail-floor salvage died at the
shadow gate while ``tail_loss_floor_fired`` latched true:

* KXXRP15M-26OCT191630-30 YES@70: floor emitted exec=39c at tte=307s,
  shadowed, settled at ~0 (realized -71c instead of ~-31c).
* KXDOGE15M-26OCT191630-30 YES@69: floor emitted exec=35c at tte=307s,
  shadowed, settled at ~0 (-70c instead of ~-34c).
* KXETH15M-26OCT191645-45 NO@36: floor emitted exec=18c at tte=413s,
  shadowed, while the position was still live.

The taxonomy was already built for this: ``LOSS_CAP`` is the non-shadowed
mandatory-risk trigger (``_MANDATORY_RISK_TRIGGER_REASONS``,
``LOSS_SELL_EXEMPT_TRIGGERS``, ``_OPERATIONAL_TRIGGER_REASONS``,
firewall ``POSITION_LOSS_BUDGET``, ``MERID_EXIT_ALLOWED_REASONS``,
envelope/veto exempt).  The floor now emits LOSS_CAP; these tests pin
the trigger classification, its membership in the price-stop set (so the
settlement-phase gate and fair-value bypass treat it as an explicit
price trigger), and the exit-reason mapping (without which it fell back
to STOP_LOSS -> canonical stop_loss -> discretionary -> dead again).
"""

import asyncio
import inspect
from decimal import Decimal
from types import SimpleNamespace

import merid.event_venues.kalshi.stop_candidate as sc
import merid.position_management.position_monitor as pm
from merid.event_venues.kalshi.settlement_aligned_exit import (
    ExitClass,
    classify_trigger_reason,
)


def test_loss_cap_is_not_shadowed():
    """LOSS_CAP must never sit in the record-only trigger set."""
    assert "LOSS_CAP" not in sc.SHADOWED_PRICE_STOP_TRIGGERS


def test_hard_stop_remains_shadowed():
    """The ordinary armed bracket stop stays shadow-only — only the
    catastrophic tail floor was re-classed, not the price-stop freeze."""
    assert "HARD_STOP" in sc.SHADOWED_PRICE_STOP_TRIGGERS


def test_loss_cap_is_price_stop_trigger():
    """Tail-floor emissions carry no edge persistence or fair value;
    they must take the explicit-price-trigger branches downstream."""
    assert "LOSS_CAP" in sc.PRICE_STOP_TRIGGER_REASONS


def test_loss_cap_classifies_operational():
    """The submit path's classify gate must see LOSS_CAP as a
    live-allowed class (not UNKNOWN — that fails closed, and not
    DISCRETIONARY — that is observe-only while the EV gate is off)."""
    cls = classify_trigger_reason("LOSS_CAP")
    assert cls.live_allowed, f"LOSS_CAP classified {cls}"


def test_loss_cap_maps_to_loss_cap_exit_reason():
    """Without the mapping the intent exit_reason defaulted to
    STOP_LOSS -> canonical stop_loss -> discretionary -> gated again."""
    assert sc._STOP_TRIGGER_TO_EXIT_REASON.get("LOSS_CAP") == "LOSS_CAP"


def test_settlement_phase_allows_loss_cap_without_edge_persistence():
    """The monitor emits consecutive_edge_below=0; outside the close
    window the candidate must still be allowed through."""
    ok, reason = sc.settlement_phase_allows_stop(
        300.0, "LOSS_CAP", consecutive_edge_below=0
    )
    assert ok, reason


def test_settlement_phase_blocks_loss_cap_inside_close_window():
    """The close-window hold policy still applies to LOSS_CAP."""
    ok, reason = sc.settlement_phase_allows_stop(
        30.0, "LOSS_CAP", consecutive_edge_below=0
    )
    assert not ok
    assert "settlement_close_window" in reason


def test_tail_floor_emits_loss_cap_trigger():
    """Source-level pin: the position monitor's tail-loss floor block
    must emit trigger_reason="LOSS_CAP" (the armed bracket stop-loss at
    ~line 5984 keeps its deliberate HARD_STOP/shadowed class)."""
    src = inspect.getsource(pm)
    floor_idx = src.index("TAIL-LOSS-FLOOR triggered")
    # The emit block sits within ~2.5k chars after the trigger log line.
    emit_block = src[floor_idx:floor_idx + 4000]
    assert 'trigger_reason="LOSS_CAP"' in emit_block
    assert 'trigger_reason="HARD_STOP"' not in emit_block


def test_loss_sell_exempt_includes_loss_cap():
    """A catastrophic salvage sells below entry by construction — it
    must stay exempt from the profit-only breakeven floor."""
    assert "LOSS_CAP" in sc.LOSS_SELL_EXEMPT_TRIGGERS


class TestNoEdgeSalvageGate:
    """2026-10-21: MERID_NO_EDGE_LOSS_SALVAGE_ENABLED re-arms the tail-loss
    floor for bounded-lane entries (entry_edge <= 0) while
    MERID_LOSS_EXITS_ENABLED=0 keeps model-edge positions riding.

    Live failure: XRP NO@89 / SOL NO@90 (pinned_fav, net claim
    entry_edge_pct=-2.89 while gross entry_edge read +0.006) missed their
    lock IOCs and settled ~0 (-89c/-90c) while the designed no-edge floor
    sat suppressed by the blanket disable."""

    def test_emission_gate_scopes_to_no_edge(self):
        """Source pin: the suppress branch must let no-edge salvage through."""
        src = inspect.getsource(pm)
        suppress_idx = src.index("LOSS-EXIT-DISABLED")
        gate_block = src[max(0, suppress_idx - 2500):suppress_idx]
        assert "no_edge_loss_salvage_enabled" in gate_block
        assert "_no_edge" in gate_block

    def test_monitor_imports_salvage_flag(self):
        src = inspect.getsource(pm)
        assert "no_edge_loss_salvage_enabled" in src

    def test_flag_default_on(self, monkeypatch):
        monkeypatch.delenv("MERID_NO_EDGE_LOSS_SALVAGE_ENABLED", raising=False)
        assert sc.no_edge_loss_salvage_enabled() is True

    def test_flag_off_restores_full_disable(self, monkeypatch):
        monkeypatch.setenv("MERID_NO_EDGE_LOSS_SALVAGE_ENABLED", "0")
        assert sc.no_edge_loss_salvage_enabled() is False


class TestHardLockQuoteFreshness:
    """2026-10-21: the lock's trigger trust bound is tighter than the
    generic 10s exit bound — a stale REST bid >= threshold must not latch
    an IOC that is dead before it reaches the exchange."""

    def test_default_bound(self, monkeypatch):
        monkeypatch.delenv("MERID_HARD_LOCK_QUOTE_MAX_AGE_MS", raising=False)
        assert pm._hard_lock_quote_max_age_ms() == 2500.0

    def test_env_override_and_floor(self, monkeypatch):
        monkeypatch.setenv("MERID_HARD_LOCK_QUOTE_MAX_AGE_MS", "1200")
        assert pm._hard_lock_quote_max_age_ms() == 1200.0
        # The 500ms floor keeps a pathological config from trusting nothing.
        monkeypatch.setenv("MERID_HARD_LOCK_QUOTE_MAX_AGE_MS", "100")
        assert pm._hard_lock_quote_max_age_ms() == 500.0

    def test_lock_trust_checks_use_bound(self):
        """Both trust re-checks (poll path + fast path) use the bound."""
        src = inspect.getsource(pm)
        # Replaces the generic EXIT_PRICE_MAX_AGE_MS in the two lock
        # trust checks; the rest of the monitor keeps the generic bound.
        assert src.count("is_fresh(_hard_lock_quote_max_age_ms())") == 2


class TestNoEdgeDiscriminator:
    """2026-10-21: the no-edge signal must read the *net* claimed edge.

    Live failure: XRP NO@89 carried entry_edge=+0.0062 (gross model-vs-
    market — positive on any maker fill at the bid) while the lane's net
    claim was entry_edge_pct=-2.89.  Reading the gross stamp alone
    classified a bounded-lane admission as model-edge and suppressed every
    no-edge salvage for the whole pinned_fav/quota cohort."""

    def test_net_claim_negative_marks_no_edge(self):
        pos = SimpleNamespace(entry_edge_pct=-2.89, entry_edge=0.0062)
        assert pm._position_no_edge_claim(pos) is True

    def test_either_stamp_negative_marks_no_edge(self):
        assert pm._position_no_edge_claim(
            SimpleNamespace(entry_edge_pct=0.03, entry_edge=-0.05)
        ) is True

    def test_all_claims_positive_is_model_edge(self):
        pos = SimpleNamespace(entry_edge_pct=0.05, entry_edge=0.02)
        assert pm._position_no_edge_claim(pos) is False

    def test_missing_claims_is_model_edge(self):
        # Default-stamped positions keep the conservative ride posture.
        assert pm._position_no_edge_claim(
            SimpleNamespace(entry_edge_pct=0.03, entry_edge=None)
        ) is False
        assert pm._position_no_edge_claim(SimpleNamespace()) is False


class TestCandidateFloorEntryEdge:
    """The floor resolver's edge read combines both stamped claims."""

    def test_net_claim_wins_over_positive_gross(self):
        cand = SimpleNamespace(
            claimed_entry_edge_pct=-2.89,
            claimed_entry_edge=0.0062,
            entry_edge_cents=1.6,
        )
        assert sc._candidate_floor_entry_edge(cand) == -2.89

    def test_min_of_claims(self):
        cand = SimpleNamespace(
            claimed_entry_edge_pct=0.05,
            claimed_entry_edge=-0.02,
            entry_edge_cents=1.0,
        )
        assert sc._candidate_floor_entry_edge(cand) == -0.02

    def test_all_positive_returns_positive(self):
        cand = SimpleNamespace(
            claimed_entry_edge_pct=5.0,
            claimed_entry_edge=0.05,
            entry_edge_cents=-9.0,
        )
        assert sc._candidate_floor_entry_edge(cand) == 0.05

    def test_fallback_when_no_claims(self):
        cand = SimpleNamespace(
            claimed_entry_edge_pct=None,
            claimed_entry_edge=None,
            entry_edge_cents=-3.0,
        )
        assert sc._candidate_floor_entry_edge(cand) == -3.0


class TestChaseFloor:
    """``_hard_lock_chase_floor_cents`` — the deepest bid a chase may take."""

    def test_no_edge_floor_is_tail_drop(self):
        pos = SimpleNamespace(
            avg_entry_price_cents=89, entry_edge_pct=-2.89, entry_edge=0.0062
        )
        assert pm._hard_lock_chase_floor_cents(pos) == 75  # 89 - 14

    def test_model_edge_floor_is_breakeven_plus(self):
        pos = SimpleNamespace(
            avg_entry_price_cents=74, entry_edge_pct=0.03, entry_edge=0.05
        )
        assert pm._hard_lock_chase_floor_cents(pos) == 75  # 74 + 1

    def test_no_entry_disables_chase(self):
        pos = SimpleNamespace(
            avg_entry_price_cents=0, entry_edge_pct=-2.89
        )
        assert pm._hard_lock_chase_floor_cents(pos) == 100

    def test_no_edge_drop_env_override(self, monkeypatch):
        monkeypatch.setenv("MERID_TAIL_LOSS_DROP_NO_EDGE_CENTS", "20")
        pos = SimpleNamespace(avg_entry_price_cents=89, entry_edge_pct=-2.89)
        assert pm._hard_lock_chase_floor_cents(pos) == 69


class TestChaseLadderWiring:
    """Source pins for the post-latch chase ladder in the poll path."""

    def test_opportunity_lost_block_has_chase(self):
        src = inspect.getsource(pm)
        lost_idx = src.index("BID_BELOW_LOCK_AFTER_LATCH")
        # The chase ladder must be evaluated inside the trusted-below-
        # threshold block, before the obligation terminalizes.
        block = src[max(0, lost_idx - 9000):lost_idx]
        assert "_chase_possible" in block
        assert "_hard_lock_chase_floor_cents(position)" in block
        assert "HARD_LOCK_CHASE" in block

    def test_chase_emits_exit_intent(self):
        src = inspect.getsource(pm)
        chase_idx = src.index("[HARD-LOCK-CHASE]")
        block = src[chase_idx:chase_idx + 3000]
        assert "_emit_exit_intent" in block
        assert "HARD_PROFIT_LOCK" in block

    def test_chase_attempts_bounded_and_persisted(self):
        src = inspect.getsource(pm)
        # attempt counter + cooldown live on the persisted pending record
        # so a restart cannot reset the ladder.
        assert 'chase_attempts' in src
        assert 'chase_last_attempt_ts' in src
        assert "_hard_lock_chase_max_attempts()" in src
        assert "_hard_lock_chase_interval_s()" in src

    def test_chase_respects_in_flight(self):
        src = inspect.getsource(pm)
        chase_idx = src.index("_chase_possible = (")
        block = src[chase_idx:chase_idx + 1500]
        # A dispatched IOC must own the obligation — no stacked orders.
        assert "_is_exit_intent_in_flight" in block


class TestHardLockChaseEndToEnd:
    """Drive the real monitor eval: a latched lock seeing a trusted
    below-threshold bid must chase (bounded re-emit), not discard the
    obligation — the exact XRP NO@89 failure shape.

    Fixture mirrors the live position: no-edge admission
    (entry_edge_pct=-2.89), latched at 94c, book faded to 87."""

    def _position(self, **kw):
        from merid.position_management.position import Position, PositionSide

        defaults = dict(
            market_id="KXXRP15M-TESTLOCK",
            series_ticker="KXXRP15M",
            side=PositionSide.NO,
            size=Decimal("1"),
            avg_entry_price_cents=89,
            stop_loss_enabled=False,
            take_profit_price_cents=None,
            fill_source="TEST",
            entry_edge_pct=-2.89,
            entry_edge=0.0062,
        )
        defaults.update(kw)
        return Position(**defaults)

    def _snapshot(self, bid: int):
        from merid.position_management.position import PositionSide
        from merid.position_management.exit_audit import ExitPriceSnapshot

        return ExitPriceSnapshot(
            market_id="KXXRP15M-TESTLOCK",
            position_side=PositionSide.NO,
            mid_cents=bid,
            own_side_bid_cents=bid,
            own_side_ask_cents=min(99, bid + 2),
            opposite_bid_cents=100 - bid - 2,
            opposite_ask_cents=100 - bid,
            book_age_ms=50,
            data_source="test",
            data_quality="GOOD",
            executable=True,
            has_bid_size=True,
            snapshot_id="snap-lock-1",
            seconds_to_expiry=300.0,
        )

    def _monitor(self, monkeypatch):
        monitor = pm.PositionMonitor()
        monitor._loop = None
        monkeypatch.setattr(monitor, "_is_expired_market", lambda *a, **k: False)
        emitted = []
        monkeypatch.setattr(monitor, "_is_exit_intent_in_flight", lambda pid: False)

        async def _capture(*a, **k):
            emitted.append(a)

        monkeypatch.setattr(monitor, "_emit_exit_intent", _capture)
        return monitor, emitted

    def test_missed_lock_chases_instead_of_terminalizing(self, monkeypatch):
        """latched 94c, trusted bid 87 < 90 threshold: chase emits at the
        fresh bid (the guard prices bid-sweep), obligation persists."""
        monkeypatch.delenv("MERID_HARD_LOCK_CHASE_ENABLED", raising=False)
        monkeypatch.setenv("MERID_HARD_LOCK_CHASE_INTERVAL_S", "0.25")
        monitor, emitted = self._monitor(monkeypatch)
        position = self._position()
        monitor.add_position(position)
        monitor._latch_hard_lock(
            position, bid_cents=94, threshold_cents=90,
            trusted=True, via="test",
        )

        asyncio.run(monitor._check_position(position, self._snapshot(87)))

        assert position.hard_lock_pending is not None, (
            "obligation must survive a missed threshold bid"
        )
        assert position.hard_lock_pending["chase_attempts"] == 1
        assert len(emitted) >= 1
        # The emitted intent carries HARD_PROFIT_LOCK at the fresh bid.
        assert emitted[0][1] == pm.ExitReason.HARD_PROFIT_LOCK
        assert emitted[0][2] == 87
        events = [e["event"] for e in position.hard_lock_pending.get("events", [])]
        assert "HARD_LOCK_CHASE" in events

    def test_chase_terminalizes_below_floor(self, monkeypatch):
        """Bid below the no-edge salvage floor (89-14=75): nothing
        salvageable -> the tail LOSS_CAP band owns the exit and the lock
        obligation terminalizes."""
        monitor, emitted = self._monitor(monkeypatch)
        position = self._position()
        monitor.add_position(position)
        monitor._latch_hard_lock(
            position, bid_cents=94, threshold_cents=90,
            trusted=True, via="test",
        )

        asyncio.run(monitor._check_position(position, self._snapshot(70)))

        assert position.hard_lock_pending is None
        assert emitted == []

    def test_chase_attempts_exhausted_terminalizes(self, monkeypatch):
        """Bounded ladder: after MAX attempts the obligation terminalizes —
        a persistent fade cannot loop IOCs forever."""
        monkeypatch.setenv("MERID_HARD_LOCK_CHASE_MAX_ATTEMPTS", "2")
        monkeypatch.setenv("MERID_HARD_LOCK_CHASE_INTERVAL_S", "0.25")
        monitor, emitted = self._monitor(monkeypatch)
        position = self._position()
        monitor.add_position(position)
        monitor._latch_hard_lock(
            position, bid_cents=94, threshold_cents=90,
            trusted=True, via="test",
        )
        snap = self._snapshot(87)

        asyncio.run(monitor._check_position(position, snap))
        assert len(emitted) == 1
        # Inside the cooldown: no re-emit, obligation survives.
        asyncio.run(monitor._check_position(position, snap))
        assert len(emitted) == 1
        # Cooldown elapsed -> second chase.
        position.hard_lock_pending["chase_last_attempt_ts"] = 0.0
        asyncio.run(monitor._check_position(position, snap))
        assert len(emitted) == 2
        # Budget exhausted -> terminalize.
        position.hard_lock_pending["chase_last_attempt_ts"] = 0.0
        asyncio.run(monitor._check_position(position, snap))
        assert position.hard_lock_pending is None
        assert len(emitted) == 2

    def test_chase_respects_in_flight_intent(self, monkeypatch):
        """A dispatched IOC owns the obligation — no stacked orders."""
        monitor, emitted = self._monitor(monkeypatch)
        monkeypatch.setattr(
            monitor, "_is_exit_intent_in_flight", lambda pid: True
        )
        position = self._position()
        monitor.add_position(position)
        monitor._latch_hard_lock(
            position, bid_cents=94, threshold_cents=90,
            trusted=True, via="test",
        )

        asyncio.run(monitor._check_position(position, self._snapshot(87)))

        assert emitted == []
        assert position.hard_lock_pending is not None

    def test_model_edge_chase_floors_at_breakeven(self, monkeypatch):
        """Entry 89 model-edge position: chase floor = entry+1 = 90 — a
        below-90 bid (89) is a loss and does not chase; the lock
        obligation terminalizes to the ride doctrine."""
        monitor, emitted = self._monitor(monkeypatch)
        position = self._position(
            entry_edge_pct=0.05, entry_edge=0.02,
        )
        monitor.add_position(position)
        monitor._latch_hard_lock(
            position, bid_cents=94, threshold_cents=90,
            trusted=True, via="test",
        )

        asyncio.run(monitor._check_position(position, self._snapshot(89)))

        # bid 89 < floor 90 -> below the model-edge chase floor -> terminal.
        assert position.hard_lock_pending is None
        assert emitted == []

    def test_chase_disabled_restores_single_shot(self, monkeypatch):
        """MERID_HARD_LOCK_CHASE_ENABLED=0 restores the legacy terminalize-
        on-first-below-threshold behavior."""
        monkeypatch.setenv("MERID_HARD_LOCK_CHASE_ENABLED", "0")
        monitor, emitted = self._monitor(monkeypatch)
        position = self._position()
        monitor.add_position(position)
        monitor._latch_hard_lock(
            position, bid_cents=94, threshold_cents=90,
            trusted=True, via="test",
        )

        asyncio.run(monitor._check_position(position, self._snapshot(87)))

        assert position.hard_lock_pending is None
        assert emitted == []

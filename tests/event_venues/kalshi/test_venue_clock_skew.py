"""Regression matrix for the venue clock-domain repair (2026-10-31).

The pre-fix pipeline compared raw ``time.time() - venue_ts`` on a host
~3.02s ahead of Kalshi, so corrected ~900ms events appeared ~3.9s old and
manufactured the shed/invalidation storm.  These tests pin the corrected
semantics through the shared helper AND the two production consumers:

* ``decide_delta_shed`` — the ws.py overload-shed predicate.
* ``KalshiMarketStateStore._book_event_timing`` — the enqueue freshness
  gate feeding ``BOOK_EVENT_TOO_OLD``.

Sign convention: ``server_minus_local_seconds`` (same as WS auth).
corrected_age = (local_wall + s) - venue_ts.
"""

from __future__ import annotations

import time

import pytest

from merid.event_venues.kalshi.venue_clock import (
    SHED_FORWARD,
    SHED_FORWARD_ANOMALY,
    SHED_FORWARD_IMPLAUSIBLE,
    SHED_FORWARD_UNVERIFIED,
    SHED_RESIDENCE,
    SHED_VENUE_AGE,
    STATUS_ANOMALY_NEGATIVE_AGE,
    STATUS_MEASURED,
    STATUS_NO_VENUE_TS,
    STATUS_UNVERIFIED_CLOCK_STEP,
    STATUS_UNVERIFIED_EXPIRED,
    STATUS_UNVERIFIED_NO_OFFSET,
    VenueClockCalibration,
    decide_delta_shed,
    get_venue_clock,
    parse_venue_ts_ms,
)


def _calibrated(offset_s: float, **kw):
    """Return (clock, wall0, mono0) with a measurement anchored at now."""
    clk = VenueClockCalibration("kalshi-test", **kw)
    w0 = time.time()
    m0 = time.monotonic()
    clk.record_measurement(
        offset_s,
        source="test",
        precision_seconds=1.0,
        rtt_seconds=0.05,
        measured_at_wall=w0,
        measured_at_monotonic=m0,
    )
    return clk, w0, m0


def _venue_ms(offset_s: float, now_wall_ms: float, true_age_ms: float) -> float:
    """A venue timestamp for an event that is ``true_age_ms`` old in
    *server* time, observed on a host offset by ``offset_s``."""
    return (now_wall_ms + offset_s * 1000.0) - true_age_ms


# ── sign + magnitude correctness ───────────────────────────────────────────
@pytest.mark.parametrize("offset_s", [-3.02, 3.02])
def test_corrected_age_both_signs(offset_s):
    """True age 900ms corrects to ~900ms under either skew direction."""
    clk, w0, m0 = _calibrated(offset_s)
    now_w_ms = w0 * 1000.0 + 50.0
    venue_ms = _venue_ms(offset_s, now_w_ms, 900.0)
    t = clk.evaluate_venue_ts(
        venue_ms,
        now_wall_ms=now_w_ms,
        now_monotonic_ns=int((m0 + 0.05) * 1e9),
    )
    assert t.freshness_status == STATUS_MEASURED
    assert t.corrected_venue_age_ms == pytest.approx(900.0, abs=1.0)
    # Raw age is poisoned by the offset in BOTH directions — this is the
    # defect.  -3.02s: raw = 900 + 3020 = 3920ms.  +3.02s: raw = -2120ms.
    assert t.raw_venue_age_ms == pytest.approx(900.0 - offset_s * 1000.0, abs=1.0)


def test_auth_measurement_metadata_recorded():
    """Source, precision and RTT must be retrievable, not assumed exact."""
    clk, w0, m0 = _calibrated(-3.02)
    st = clk.offset_state(now_wall=w0, now_monotonic=m0)
    assert st.valid and st.invalid_reason is None
    assert st.source == "test"
    assert st.precision_seconds == pytest.approx(1.0)
    assert st.rtt_seconds == pytest.approx(0.05)
    assert st.measurement_age_s == pytest.approx(0.0, abs=0.01)


# ── shed decisions ──────────────────────────────────────────────────────────
def test_truly_old_frame_drops_on_corrected_age():
    """Verified-stale venue evidence still sheds (no relaxation)."""
    clk, w0, m0 = _calibrated(-3.02)
    now_w_ms = w0 * 1000.0
    venue_ms = _venue_ms(-3.02, now_w_ms, 6000.0)
    t = clk.evaluate_venue_ts(venue_ms, now_wall_ms=now_w_ms,
                              now_monotonic_ns=int(m0 * 1e9))
    dec = decide_delta_shed(
        queue_residence_ms=120.0, residence_bound_ms=4000.0,
        timing=t, venue_age_bound_ms=3750.0,
    )
    assert dec.drop and dec.reason == SHED_VENUE_AGE


def test_skewed_fresh_frame_is_not_dropped():
    """The production failure mode: raw 3950ms / corrected 930ms forwards."""
    clk, w0, m0 = _calibrated(-3.02)
    now_w_ms = w0 * 1000.0
    venue_ms = _venue_ms(-3.02, now_w_ms, 930.0)  # raw age = 3950 > 3750
    t = clk.evaluate_venue_ts(venue_ms, now_wall_ms=now_w_ms,
                              now_monotonic_ns=int(m0 * 1e9))
    assert t.raw_venue_age_ms == pytest.approx(3950.0, abs=1.0)
    dec = decide_delta_shed(
        queue_residence_ms=940.0, residence_bound_ms=4000.0,
        timing=t, venue_age_bound_ms=3750.0,
    )
    assert not dec.drop and dec.reason == SHED_FORWARD


def test_residence_bound_is_authoritative():
    """Long queue residence sheds even with a recent venue timestamp."""
    clk, w0, m0 = _calibrated(-3.02)
    now_w_ms = w0 * 1000.0
    venue_ms = _venue_ms(-3.02, now_w_ms, 200.0)
    t = clk.evaluate_venue_ts(venue_ms, now_wall_ms=now_w_ms,
                              now_monotonic_ns=int(m0 * 1e9))
    dec = decide_delta_shed(
        queue_residence_ms=5000.0, residence_bound_ms=4000.0,
        timing=t, venue_age_bound_ms=3750.0,
    )
    assert dec.drop and dec.reason == SHED_RESIDENCE


# ── unknown / expired / stepped calibration ─────────────────────────────────
def test_unknown_offset_is_explicitly_unverified():
    clk = VenueClockCalibration("kalshi-test")
    t = clk.evaluate_venue_ts(time.time() * 1000.0 - 100.0)
    assert t.freshness_status == STATUS_UNVERIFIED_NO_OFFSET
    assert t.corrected_venue_age_ms is None
    assert not t.offset_valid
    # Residence still arbitrates; the frame is NOT silently fresh.
    dec = decide_delta_shed(
        queue_residence_ms=50.0, residence_bound_ms=4000.0,
        timing=t, venue_age_bound_ms=3750.0,
    )
    assert not dec.drop and dec.reason == SHED_FORWARD_UNVERIFIED
    dec2 = decide_delta_shed(
        queue_residence_ms=5000.0, residence_bound_ms=4000.0,
        timing=t, venue_age_bound_ms=3750.0,
    )
    assert dec2.drop and dec2.reason == SHED_RESIDENCE


def test_expired_offset_unverified():
    clk, w0, m0 = _calibrated(-3.02, max_offset_age_s=60.0)
    t = clk.evaluate_venue_ts(
        _venue_ms(-3.02, w0 * 1000.0, 900.0),
        now_wall_ms=w0 * 1000.0,
        now_monotonic_ns=int((m0 + 120.0) * 1e9),  # 120s after measurement
    )
    assert t.freshness_status == STATUS_UNVERIFIED_EXPIRED
    assert t.corrected_venue_age_ms is None


def test_host_clock_step_invalidates_calibration():
    """A host resync after measurement must not silently reuse the offset."""
    clk, w0, m0 = _calibrated(-3.02, step_tolerance_s=0.5)
    # Host wall clock corrected +3.1s (the resync this defect motivates).
    t = clk.evaluate_venue_ts(
        _venue_ms(-3.02, w0 * 1000.0, 900.0),
        now_wall_ms=(w0 + 3.1) * 1000.0,
        now_monotonic_ns=int((m0 + 0.1) * 1e9),
    )
    assert t.freshness_status == STATUS_UNVERIFIED_CLOCK_STEP
    assert t.corrected_venue_age_ms is None
    # A fresh measurement restores calibration.
    w1 = w0 + 3.1
    m1 = m0 + 0.2
    clk.record_measurement(
        -0.02, source="re-auth", precision_seconds=1.0,
        measured_at_wall=w1, measured_at_monotonic=m1,
    )
    t2 = clk.evaluate_venue_ts(
        (w1 - 0.02) * 1000.0 - 900.0,
        now_wall_ms=w1 * 1000.0,
        now_monotonic_ns=int(m1 * 1e9),
    )
    assert t2.freshness_status == STATUS_MEASURED
    assert t2.corrected_venue_age_ms == pytest.approx(900.0, abs=1.0)


# ── anomalies ───────────────────────────────────────────────────────────────
def test_materially_negative_age_is_anomaly_not_zero():
    """Corrected age far in the future => broken calibration; do not clamp."""
    clk, w0, m0 = _calibrated(-3.02)
    now_w_ms = w0 * 1000.0
    venue_ms = _venue_ms(-3.02, now_w_ms, -5000.0)  # venue ts 5s in future
    t = clk.evaluate_venue_ts(venue_ms, now_wall_ms=now_w_ms,
                              now_monotonic_ns=int(m0 * 1e9))
    assert t.freshness_status == STATUS_ANOMALY_NEGATIVE_AGE
    assert t.corrected_venue_age_ms == pytest.approx(-5000.0, abs=1.0)
    dec = decide_delta_shed(
        queue_residence_ms=50.0, residence_bound_ms=4000.0,
        timing=t, venue_age_bound_ms=3750.0,
    )
    assert not dec.drop and dec.reason == SHED_FORWARD_ANOMALY


def test_implausible_corrected_age_does_not_shed():
    """An absurd corrected age (>4x bound) is untrusted, not a drop reason."""
    clk, w0, m0 = _calibrated(-3.02)
    now_w_ms = w0 * 1000.0
    venue_ms = _venue_ms(-3.02, now_w_ms, 60_000.0)
    t = clk.evaluate_venue_ts(venue_ms, now_wall_ms=now_w_ms,
                              now_monotonic_ns=int(m0 * 1e9))
    dec = decide_delta_shed(
        queue_residence_ms=50.0, residence_bound_ms=4000.0,
        timing=t, venue_age_bound_ms=3750.0,
    )
    assert not dec.drop and dec.reason == SHED_FORWARD_IMPLAUSIBLE


def test_missing_venue_ts_falls_back_to_residence():
    clk, w0, m0 = _calibrated(-3.02)
    t = clk.evaluate_venue_ts(None, now_wall_ms=w0 * 1000.0,
                              now_monotonic_ns=int(m0 * 1e9))
    assert t.freshness_status == STATUS_NO_VENUE_TS


# ── conflated-stream semantics ──────────────────────────────────────────────
def test_conflated_timestamp_regression_is_not_dropped():
    """Kalshi conflation: a later message may carry an EARLIER ts.  Under a
    valid offset, decreasing timestamps just report decreasing corrected
    ages — nothing about ts order alone may trigger a drop."""
    clk, w0, m0 = _calibrated(-3.02)
    now_w_ms = w0 * 1000.0
    ages = []
    for i, true_age in enumerate([800.0, 1200.0, 600.0]):  # non-monotonic ts
        venue_ms = _venue_ms(-3.02, now_w_ms, true_age)
        t = clk.evaluate_venue_ts(
            venue_ms, now_wall_ms=now_w_ms,
            now_monotonic_ns=int((m0 + i * 0.01) * 1e9),
        )
        dec = decide_delta_shed(
            queue_residence_ms=50.0, residence_bound_ms=4000.0,
            timing=t, venue_age_bound_ms=3750.0,
        )
        assert not dec.drop
        ages.append(t.corrected_venue_age_ms)
    assert ages[2] < ages[1]  # ts regression observed, no continuity action


# ── pipeline consistency: shed + enqueue gate ───────────────────────────────
def test_book_event_timing_uses_corrected_age():
    """market_state._book_event_timing must return the corrected age and
    label its source; uncompensated age caused premature BOOK_EVENT_TOO_OLD."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    clk = get_venue_clock("kalshi")
    try:
        w0 = time.time()
        m0 = time.monotonic()
        clk.record_measurement(
            -3.02, source="test", precision_seconds=1.0,
            measured_at_wall=w0, measured_at_monotonic=m0,
        )
        now_w_ms = w0 * 1000.0
        venue_ms = _venue_ms(-3.02, now_w_ms, 900.0)  # raw ~3920ms
        msg = {
            "ts": venue_ms / 1000.0,
            "_t_bridge_recv_ns": int(m0 * 1e9),
            "_t_bridge_recv_wall_ms": now_w_ms - 40.0,
        }
        age_ms, wait_ms, hops = KalshiMarketStateStore._book_event_timing(
            object(), msg
        )
        assert hops["venue_age_status"] == STATUS_MEASURED
        assert hops["event_age_src"] == "venue_ts_corrected"
        assert age_ms == pytest.approx(900.0, abs=5.0)
        assert hops["corr_venue_age_ms"] == pytest.approx(age_ms, abs=1.0)
        assert hops["raw_venue_age_ms"] == pytest.approx(3920.0, abs=10.0)
        assert hops["offset_s"] == pytest.approx(-3.02)
        # Under the pre-fix code this frame tripped BOOK_EVENT_TOO_OLD
        # (>4000ms); corrected it is well inside the bound.
        assert age_ms < 4000.0
    finally:
        clk.invalidate("test teardown")


def test_book_event_timing_unverified_offset_falls_back_labeled():
    """With no calibration the gate uses the local bridge-recv age but the
    hops expose that venue age was unverifiable — never a disguised fresh."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    clk = get_venue_clock("kalshi")
    clk.invalidate("force unverified")
    now_w_ms = time.time() * 1000.0
    msg = {
        "ts": now_w_ms / 1000.0 - 0.9,
        "_t_bridge_recv_ns": time.monotonic_ns() - 40_000_000,
        "_t_bridge_recv_wall_ms": now_w_ms - 40.0,
    }
    age_ms, wait_ms, hops = KalshiMarketStateStore._book_event_timing(
        object(), msg
    )
    assert hops["venue_age_status"] == STATUS_UNVERIFIED_NO_OFFSET
    assert hops["event_age_src"] == "bridge_recv_wall(unverified_no_offset)"
    assert age_ms == pytest.approx(40.0, abs=15.0)
    assert wait_ms == pytest.approx(40.0, abs=15.0)


def test_parse_venue_ts_ms_forms():
    assert parse_venue_ts_ms(None) is None
    assert parse_venue_ts_ms("bogus") is None
    assert parse_venue_ts_ms(1_700_000_000_000) == 1_700_000_000_000
    assert parse_venue_ts_ms(1_700_000_000.0) == 1_700_000_000_000
    assert parse_venue_ts_ms("2026-10-31T21:00:00Z") == pytest.approx(
        1793480400000.0
    )


# ── end-to-end: unverified venue age must not become trading freshness ─────

_TICKER = "KXBTC15M-T"


def _store():
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    store = KalshiMarketStateStore()
    store._main_event_loop = None  # never schedule coroutines from tests
    return store


def _book(store, seq=100):
    store._ob.apply_snapshot(
        _TICKER,
        {"ticker": _TICKER, "yes": [[0.48, 5]], "no": [[0.50, 4]], "seq": seq},
    )
    state = store._get_or_create(_TICKER)
    state.snapshot_complete = True
    state.data_quality = "GOOD"
    state.book_consistency = "GOOD"
    state.transition = "VALID"
    state.executable = True
    return state


def _fresh_gate_prereqs(state):
    """Satisfy every ws_fresh leg EXCEPT the event-age-verification leg."""
    state.quote_owner = "WS_FRESH_VERIFIED"
    state.last_ws_update_ts = time.monotonic()


def test_unverified_venue_age_does_not_pass_freshness_gate():
    """Boundary spec: unverifiable -> retained for reconstruction -> status
    survives -> freshness gate does NOT pass on receipt age alone."""
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

    clk = get_venue_clock("kalshi")
    clk.invalidate("force unverified")
    store = _store()
    _book(store)
    now_w_ms = time.time() * 1000.0
    msg = {
        "side": "yes",
        "price_dollars": 0.49,
        "delta_fp": 3.0,
        "seq": 101,
        "ts": now_w_ms / 1000.0 - 0.9,   # venue ts present but unverifiable
        "_t_bridge_recv_ns": time.monotonic_ns() - 30_000_000,
        "_t_bridge_recv_wall_ms": now_w_ms - 30.0,
    }
    store._apply_delta_internal(_TICKER, msg)
    state = store.get(_TICKER)
    # Reconstruction preserved: the delta applied, book not invalidated.
    assert state.data_quality == "GOOD"
    assert state.executable is True
    # Status survived through state.
    assert state.ws_last_event_age_status == STATUS_UNVERIFIED_NO_OFFSET
    assert "bridge_recv_wall(unverified_no_offset)" in (
        state.ws_last_event_age_src or ""
    )
    # Freshness gate: recent RECEIPT (ws_age_ms ~0, event_age ~30ms) must
    # not stand in for verified venue freshness.
    _fresh_gate_prereqs(state)
    gate = store.get_quote_gate_state(_TICKER)
    assert gate["ws_event_age_verified"] is False
    assert gate["ws_event_age_status"] == STATUS_UNVERIFIED_NO_OFFSET
    assert gate["ws_fresh"] is False
    assert gate["effective_fresh"] is False


def test_measured_venue_age_passes_freshness_gate():
    """Positive control: calibrated offset restores verified freshness."""
    clk = get_venue_clock("kalshi")
    try:
        w0 = time.time()
        m0 = time.monotonic()
        clk.record_measurement(
            -3.02, source="test", precision_seconds=1.0,
            measured_at_wall=w0, measured_at_monotonic=m0,
        )
        store = _store()
        _book(store)
        now_w_ms = w0 * 1000.0
        msg = {
            "side": "yes",
            "price_dollars": 0.49,
            "delta_fp": 3.0,
            "seq": 101,
            "ts": _venue_ms(-3.02, now_w_ms, 900.0) / 1000.0,
            "_t_bridge_recv_ns": int(m0 * 1e9) - 30_000_000,
            "_t_bridge_recv_wall_ms": now_w_ms - 30.0,
        }
        store._apply_delta_internal(_TICKER, msg)
        state = store.get(_TICKER)
        assert state.ws_last_event_age_status == STATUS_MEASURED
        assert state.ws_last_event_age_ms == pytest.approx(900.0, abs=50.0)
        _fresh_gate_prereqs(state)
        gate = store.get_quote_gate_state(_TICKER)
        assert gate["ws_event_age_verified"] is True
        assert gate["ws_fresh"] is True
        assert gate["effective_fresh"] is True
    finally:
        clk.invalidate("test teardown")


def test_no_venue_ts_uses_receipt_recency():
    """A frame class with no venue ts has nothing to verify — local receipt
    recency remains the honest freshness measure and may pass."""
    clk = get_venue_clock("kalshi")
    clk.invalidate("not needed for no-ts frames")
    store = _store()
    _book(store)
    msg = {
        "side": "yes",
        "price_dollars": 0.49,
        "delta_fp": 3.0,
        "seq": 101,
        "_t_bridge_recv_ns": time.monotonic_ns() - 30_000_000,
        "_t_bridge_recv_wall_ms": time.time() * 1000.0 - 30.0,
    }
    store._apply_delta_internal(_TICKER, msg)
    state = store.get(_TICKER)
    assert state.ws_last_event_age_status == STATUS_NO_VENUE_TS
    _fresh_gate_prereqs(state)
    gate = store.get_quote_gate_state(_TICKER)
    assert gate["ws_event_age_verified"] is True  # n/a: nothing to verify
    assert gate["ws_fresh"] is True

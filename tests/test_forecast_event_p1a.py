"""P1a: same-event forecast telemetry + scheduled shadow — behavior tests.

The instrumentation contract (experiment spec §4/§8):

- Telemetry enabled vs disabled produces identical probability outputs,
  admission decisions, return values, and exception behavior.
- Scheduled-shadow evaluations emit one same-event envelope per
  (contract, horizon) opportunity with the five frozen arms and never
  write production side effects (model-cal log, EPC obs, state checksum,
  decision ledger, rejection log, cell funnel, canary counter).
- Early returns and exceptions still land as partial/failed events.
- Stage values reproduce production output exactly (no reconstruction).
"""
import json
import math
import time
from dataclasses import asdict

import pytest

from merid.prediction import forecast_event as _fe
from merid.prediction import shadow_evaluator as _se
from merid.prediction import model_calibration_log as _mcl
from merid.prediction import trade_decision as _td


def _args(**over):
    args = dict(
        run_id="p1a_test",
        decision_id="p1a_test_1",
        ticker="KXBTC15M-26OCT161445-45",  # close 2026-10-16T18:45Z (14:45 ET)
        asset="BTC",
        spot_price=100.0,
        strike_price=100.0,
        seconds_to_expiry=600.0,
        yes_bid_cents=50.0,
        yes_ask_cents=52.0,
        no_bid_cents=48.0,
        no_ask_cents=50.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        annualized_vol=0.60,
        model_uncertainty=0.05,
        data_quality="live",
        regime="normal",
        min_required_edge=0.02,
        settlement_reference="cfb_rti_live",
        route="taker",
        entry_price_basis="ask",
    )
    args.update(over)
    return args


@pytest.fixture
def sink(tmp_path, monkeypatch):
    p = tmp_path / "forecast_events.jsonl"
    monkeypatch.setenv("MERID_FORECAST_EVENT_LOG_PATH", str(p))
    # also redirect the opportunity ledger: tests must not write rows into
    # the production segment ledger at the default path
    monkeypatch.setenv("MERID_FORECAST_OPP_LOG_PATH",
                       str(tmp_path / "forecast_opportunities.jsonl"))
    monkeypatch.setenv("MERID_FORECAST_EVENT_LOG_ENABLED", "1")
    monkeypatch.delenv("MERID_Q0_CALIBRATOR_PATH", raising=False)
    _fe.reset_for_tests()
    _se.reset_for_tests()
    _mcl.reset_for_tests()
    yield p
    _fe.reset_for_tests()
    _se.reset_for_tests()
    _mcl.reset_for_tests()


def _events(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _norm(d):
    """Decision asdict minus wall-clock fields."""
    out = asdict(d)
    out.pop("timestamp_utc", None)
    return out


def _ticker_for_close(close_utc_ts: float, asset: str = "BTC") -> str:
    """Build a canonical KX*15M ticker whose close is ``close_utc_ts``.

    The embedded body is the ET wall-clock window end — inverse of
    ``scheduled_close_from_ticker``.
    """
    import datetime
    from zoneinfo import ZoneInfo
    dt = datetime.datetime.fromtimestamp(
        close_utc_ts, tz=datetime.timezone.utc).astimezone(
            ZoneInfo("America/New_York"))
    mon = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][dt.month - 1]
    return (f"KX{asset}15M-{dt:%y}{mon}{dt.day:02d}"
            f"{dt.hour:02d}{dt.minute:02d}-{dt.minute:02d}")


# ----------------------------------------------------------- preservation --

def test_telemetry_off_produces_identical_decision(sink, monkeypatch):
    monkeypatch.setenv("MERID_FORECAST_EVENT_LOG_ENABLED", "0")
    d_off = _td.compute_trade_decision(**_args())
    assert _events(sink) == []  # disabled call emitted nothing
    monkeypatch.setenv("MERID_FORECAST_EVENT_LOG_ENABLED", "1")
    d_on = _td.compute_trade_decision(**_args(decision_id="p1a_test_2"))
    a, b = _norm(d_off), _norm(d_on)
    a.pop("decision_id"); b.pop("decision_id")
    assert a == b
    assert len(_events(sink)) == 1


def test_telemetry_disabled_emits_nothing(sink, monkeypatch):
    monkeypatch.setenv("MERID_FORECAST_EVENT_LOG_ENABLED", "0")
    _td.compute_trade_decision(**_args())
    assert _events(sink) == []


# ------------------------------------------------------------- event shape --

def test_full_chain_event_captures_every_stage(sink):
    d = _td.compute_trade_decision(**_args())
    (ev,) = _events(sink)
    assert ev["forecast_event_id"].startswith("fev_")
    assert ev["evaluation_source"] == "production"
    assert ev["opportunity_id"] == "p1a_test_1"
    assert ev["market_ticker"] == "KXBTC15M-26OCT161445-45"
    assert ev["boundary_source"] == "ticker_parsed_et"
    import datetime
    exp_close = datetime.datetime(
        2026, 10, 16, 18, 45, tzinfo=datetime.timezone.utc).timestamp()
    assert ev["scheduled_contract_close_ts"] == pytest.approx(exp_close, abs=1)
    # stage reproduction — values are the actual production variables,
    # not reconstructions
    ind = d.indicators
    assert ev["raw_p_yes"] == pytest.approx(ind["p_yes_raw"])
    assert ev["post_anchor_p_yes"] == pytest.approx(ind["p_yes_post_anchor"])
    assert ev["post_walkforward_p_yes"] == pytest.approx(ind["fe_post_walkforward_p_yes"])
    assert ev["post_epc_p_yes"] == pytest.approx(ind["fe_post_epc_p_yes"])
    assert ev["post_tail_p_yes"] == pytest.approx(ind["fe_post_tail_p_yes"])
    assert ev["post_stream_p_yes"] == pytest.approx(ind["fe_post_stream_p_yes"])
    assert ev["final_p_yes"] == pytest.approx(ind["fe_final_p_yes"])
    assert ev["market_anchor_prob_used"] == pytest.approx(ind["market_anchor_prob"])
    # full-chain coverage: no stage silently fell back
    for stage, present in ev["stage_coverage"].items():
        assert present, stage
    assert ev["terminal_state"] in ("completed", "partial")
    assert ev["evaluation_start_ts"] <= ev["evaluation_end_ts"]


def test_partial_event_on_early_return(sink):
    _td.compute_trade_decision(**_args(seconds_to_expiry=10.0,
                                       decision_id="p1a_early"))
    (ev,) = _events(sink)
    assert ev["terminal_state"] == "partial"
    assert ev["terminal_reason"] == "final_minute_entry_disabled"
    assert ev["forecast_availability"] == "unavailable"
    assert ev["final_p_yes"] is None
    assert ev["input_validity"] == "unassessed"  # strategy screen, not bad input


def test_invalid_input_event(sink):
    _td.compute_trade_decision(**_args(seconds_to_expiry=-5.0,
                                       decision_id="p1a_bad"))
    (ev,) = _events(sink)
    assert ev["terminal_state"] == "partial"
    assert ev["terminal_reason"] == "expired_or_no_time"
    assert ev["input_validity"] == "invalid"


def test_failed_event_on_exception(sink, monkeypatch):
    def _boom(**kw):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(_td, "_compute_trade_decision_impl", _boom)
    with pytest.raises(RuntimeError):
        _td.compute_trade_decision(**_args())
    (ev,) = _events(sink)
    assert ev["terminal_state"] == "failed"
    assert "RuntimeError" in ev["terminal_reason"]


def test_events_have_single_identity(sink):
    _td.compute_trade_decision(**_args())
    _td.compute_trade_decision(**_args(decision_id="p1a_test_2"))
    evs = _events(sink)
    assert len(evs) == 2
    assert evs[0]["forecast_event_id"] != evs[1]["forecast_event_id"]
    # no minute-bucket join needed: every stage value in one record
    assert all(isinstance(e["stage_coverage"], dict) for e in evs)


# --------------------------------------------------------------- boundary --

def test_scheduled_close_from_ticker():
    """Ticker time is the ET window end — verified vs venue close_time."""
    import datetime
    # October = EDT (UTC-4): 14:45 ET -> 18:45 UTC == Kalshi close_time
    ts = _fe.scheduled_close_from_ticker("KXBTC15M-26OCT161445-45")
    want = datetime.datetime(2026, 10, 16, 18, 45,
                             tzinfo=datetime.timezone.utc).timestamp()
    assert ts == pytest.approx(want)
    # January = EST (UTC-5): 14:45 ET -> 19:45 UTC — DST-aware, not a
    # fixed UTC-4 offset.
    ts_winter = _fe.scheduled_close_from_ticker("KXBTC15M-26JAN161445-45")
    want_winter = datetime.datetime(2026, 1, 16, 19, 45,
                                    tzinfo=datetime.timezone.utc).timestamp()
    assert ts_winter == pytest.approx(want_winter)
    # Date boundary: 00:15 ET on the 17th is still the 16th late evening UTC
    ts_bnd = _fe.scheduled_close_from_ticker("KXBTC15M-26OCT170015-15")
    want_bnd = datetime.datetime(2026, 10, 17, 4, 15,
                                 tzinfo=datetime.timezone.utc).timestamp()
    assert ts_bnd == pytest.approx(want_bnd)
    assert _fe.scheduled_close_from_ticker("garbage") is None
    assert _fe.scheduled_close_from_ticker(None) is None


def test_unparseable_ticker_flags_reconstructed_boundary(sink):
    _td.compute_trade_decision(
        **_args(ticker="KXBTC15M-NOTIME", decision_id="p1a_recon"))
    (ev,) = _events(sink)
    assert ev["boundary_source"] == "reconstructed_tte"
    assert ev["scheduled_contract_close_ts"] is not None


# -------------------------------------------------------------- suppression --

def test_suppression_blocks_model_cal_and_checksum(sink, tmp_path, monkeypatch):
    mcl_path = tmp_path / "model_cal.jsonl"
    monkeypatch.setenv("MERID_MODEL_CAL_LOG_PATH", str(mcl_path))
    calls = {"n": 0}
    orig = _td.record_state_checksum
    def _count(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    monkeypatch.setattr(_td, "record_state_checksum", _count)

    with _fe.suppress_side_effects():
        _td._compute_trade_decision_impl(
            **_args(decision_id="p1a_suppressed"))
    assert calls["n"] == 0
    assert not mcl_path.exists()  # suppressed eval wrote nothing

    _td._compute_trade_decision_impl(**_args(decision_id="p1a_normal"))
    assert calls["n"] == 1  # main return path records exactly once
    assert mcl_path.exists() and mcl_path.read_text().strip()


# ------------------------------------------------------------------ shadow --

def test_shadow_emits_one_event_per_horizon_with_arms(sink, monkeypatch):
    # close = now+500: both horizon targets are deterministically due
    # (600-500=100, 540-500=40 < 540), delays land in 'late' territory for
    # h600 — this test covers arms/stage capture, not delay semantics.
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600,540")
    monkeypatch.setenv("MERID_SHADOW_TIME_BUDGET_MS", "10000")
    mcl_path = sink.parent / "model_cal.jsonl"
    monkeypatch.setenv("MERID_MODEL_CAL_LOG_PATH", str(mcl_path))
    ticker = _ticker_for_close(time.time() + 500)
    out = _se.maybe_emit_scheduled(
        ticker=ticker, asset="BTC", base_kwargs=_args())
    assert len(out) == 2
    evs = _events(sink)
    assert len(evs) == 2
    for ev in evs:
        assert ev["evaluation_source"] == "scheduled_shadow"
        assert ev["opportunity_id"].startswith(
            f"forecast_ablation_v1|{ticker}|h")
        assert ev["execution_inputs"] == "standardized_taker_ask"
        assert ev["scheduled_horizon_s"] in (600, 540)
        assert ev["scheduling_delay_s"] is not None and ev["scheduling_delay_s"] >= 0
        # with a 30s bound and horizons 20s apart only one can be 'emitted'
        assert ev["opportunity_status"] in ("emitted", "late")
        assert ev["record_id"] and ev["content_hash"]
        arms = ev["arms"]
        assert set(arms) >= {"M", "Q0", "P", "A", "R"}
        assert arms["M"] == pytest.approx(ev["market_anchor_prob_used"])
        assert arms["R"] == pytest.approx(ev["raw_p_yes"])
        assert arms["P"] == pytest.approx(ev["final_p_yes"])
        assert arms["A"] == pytest.approx(ev["post_walkforward_p_yes"])
        assert ev["terminal_state"] in ("completed", "partial")
    # shadow wrote no model-cal rows
    assert not mcl_path.exists()


def test_shadow_late_event_flagged_not_backfilled(sink, monkeypatch):
    # close = now+360: h600 target crossed 240s ago > 30s permitted delay.
    # The event is still emitted (diagnostic) but flagged 'late' — the
    # runner excludes it from the confirmatory horizon.
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    monkeypatch.setenv("MERID_SHADOW_MAX_DELAY_S", "30")
    ticker = _ticker_for_close(time.time() + 360)
    out = _se.maybe_emit_scheduled(
        ticker=ticker, asset="BTC", base_kwargs=_args())
    assert len(out) == 1
    (ev,) = _events(sink)
    assert ev["scheduling_delay_s"] > 30
    assert ev["opportunity_status"] == "late"


def test_shadow_missed_after_close_no_backfill(sink, monkeypatch):
    # Contract already closed: evaluation after close must NOT silently
    # backfill — the opportunity resolves as 'missed' with no event.
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    ticker = _ticker_for_close(time.time() - 60)
    out = _se.maybe_emit_scheduled(
        ticker=ticker, asset="BTC", base_kwargs=_args())
    assert out == [] and _events(sink) == []
    rec = _se.emitted_opportunities()[f"{ticker}:h600"]
    assert rec["status"] == "missed"


def test_shadow_dedupes_per_contract_horizon(sink, monkeypatch):
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    ticker = _ticker_for_close(time.time() + 600)
    for _ in range(3):
        _se.maybe_emit_scheduled(
            ticker=ticker, asset="BTC", base_kwargs=_args())
    assert len(_events(sink)) == 1
    assert f"{ticker}:h600" in _se.emitted_opportunities()


def test_shadow_disabled(sink, monkeypatch):
    monkeypatch.setenv("MERID_SCHEDULED_SHADOW_ENABLED", "0")
    ticker = _ticker_for_close(time.time() + 600)
    out = _se.maybe_emit_scheduled(
        ticker=ticker, asset="BTC", base_kwargs=_args())
    assert out == [] and _events(sink) == []


def test_shadow_not_yet_due(sink, monkeypatch):
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    # contract closes far in the future: h600 target is not crossed yet —
    # the opportunity is still REGISTERED (expected-opportunity accounting)
    # even though nothing emits.
    ticker = _ticker_for_close(time.time() + 3600)
    out = _se.maybe_emit_scheduled(ticker=ticker, asset="BTC",
                                   base_kwargs=_args())
    assert out == [] and _events(sink) == []
    rec = _se.emitted_opportunities()[f"{ticker}:h600"]
    assert rec["status"] == "scheduled"


def test_q0_arm_from_frozen_artifact(sink, tmp_path, monkeypatch):
    art = tmp_path / "q0.json"
    art.write_text(json.dumps({
        "schema": "q0_calibrator/v1",
        "tables": {"BTC|600": [[0.40, 0.42], [0.60, 0.62]]},
    }))
    monkeypatch.setenv("MERID_Q0_CALIBRATOR_PATH", str(art))
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    _se.maybe_emit_scheduled(
        ticker=_ticker_for_close(time.time() + 600), asset="BTC",
        base_kwargs=_args())
    (ev,) = _events(sink)
    m = ev["arms"]["M"]
    assert ev["arms"]["Q0"] == pytest.approx(0.42 + (0.62 - 0.42) * (m - 0.40) / 0.20, abs=1e-9)
    assert ev["q0_artifact_hash"] is not None


def test_shadow_exception_counts_failed_event(sink, monkeypatch):
    def _boom(**kw):
        raise RuntimeError("shadow fail")
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    ticker = _ticker_for_close(time.time() + 600)
    out = _se.maybe_emit_scheduled(
        ticker=ticker, asset="BTC",
        base_kwargs=_args(), call_decision=_boom)
    assert len(out) == 1  # opportunity consumed and accounted
    assert out[0]["scheduled_horizon_s"] == 600
    assert _se.emitted_opportunities()[f"{ticker}:h600"]["status"] == "unavailable"

# ------------------------------------------------------------- ablation (P1b) --

from merid.analysis.forecast_audit import ablation_runner as _ar


def _synth_events(tmp_path, n=40):
    ev_path = tmp_path / "fev.jsonl"
    oc_path = tmp_path / "out.jsonl"
    evs, ocs = [], []
    for i in range(n):
        tick = f"KXBTC15M-26OCT{10 + i // 6:02d}{(12 + i % 6):02d}15-15"
        close = 1760000000 + i * 900
        m = 0.30 + 0.40 * ((i * 37) % 100) / 100.0
        evs.append({
            "schema_version": 1, "forecast_event_id": f"fev_{i:04d}",
            "market_ticker": tick, "asset": "BTC",
            "opportunity_id": f"opp_{i}", "scheduled_horizon_s": 600,
            "evaluation_source": "scheduled_shadow",
            "scheduled_contract_close_ts": close,
            "market_anchor_prob_used": m, "raw_p_yes": m + 0.02,
            "post_walkforward_p_yes": m + 0.008, "final_p_yes": m + 0.004,
            "forecast_availability": "available",
            "admission_result": "enter" if i % 3 else "no_trade",
            "terminal_state": "completed",
            "arms": {"M": m, "Q0": m, "P": m + 0.004,
                     "A": m + 0.008, "R": m + 0.02},
        })
        ocs.append({"ticker": tick, "resolved_yes": i % 2,
                    "observed_at_utc": close + 60,
                    "settlement_timestamp_utc": close})
    ev_path.write_text("\n".join(json.dumps(e) for e in evs))
    oc_path.write_text("\n".join(json.dumps(o) for o in ocs))
    return ev_path, oc_path


def test_ablation_runner_pairs_on_same_events(tmp_path):
    ev_path, oc_path = _synth_events(tmp_path)
    out = tmp_path / "rep.json"
    rc = _ar.main(["--events", str(ev_path), "--outcomes", str(oc_path),
                   "--replicates", "100", "--out", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    pop = rep["population"]
    assert pop["events_total"] == 40 and pop["units_with_outcome"] == 40
    assert pop["admitted"] == 26
    res = rep["all_completed"]["P_vs_A"]
    # P = m+0.004 is slightly worse than A = m+0.008? No: A has larger offset
    # -> d = L(A) - L(P) < 0 expected direction checked by sign only
    assert res["n"] == 40
    assert res["statistical_verdict"] in ("PASS", "FAIL", "INCONCLUSIVE")
    assert res["deployment_gate_passed"] is False
    # admitted cohort is a strict subset view
    res_ad = rep["policy_admitted"]["P_vs_A"]
    assert res_ad["n"] == 26


def test_ablation_common_support_excludes_missing_arms(tmp_path):
    ev_path, oc_path = _synth_events(tmp_path)
    lines = ev_path.read_text().splitlines()
    evs = [json.loads(l) for l in lines]
    del evs[0]["arms"]["Q0"]
    del evs[1]["final_p_yes"]
    ev_path.write_text("\n".join(json.dumps(e) for e in evs))
    out = tmp_path / "rep.json"
    _ar.main(["--events", str(ev_path), "--outcomes", str(oc_path),
              "--replicates", "50", "--out", str(out)])
    rep = json.loads(out.read_text())
    assert rep["all_completed"]["Q0_vs_M"]["n"] == 39
    assert rep["all_completed"]["P_vs_A"]["n"] == 39
    assert rep["all_completed"]["A_vs_R"]["n"] == 40


def test_ablation_dedupes_event_ids(tmp_path):
    ev_path, oc_path = _synth_events(tmp_path, n=10)
    lines = ev_path.read_text().splitlines()
    ev_path.write_text("\n".join(lines + lines[:5]))  # replayed ids
    evs, stats = _ar.load_forecast_events(ev_path)
    assert len(evs) == 10 and stats["duplicate_ids"] == 5

# ============================================================ pilot gates ==

# ------------------------------------------------- isolation (ContextVar) --

def test_suppression_nested_and_exception_restore(sink):
    assert not _fe.side_effects_suppressed()
    with _fe.suppress_side_effects():
        assert _fe.side_effects_suppressed()
        with _fe.suppress_side_effects():
            assert _fe.side_effects_suppressed()
        assert _fe.side_effects_suppressed()  # nested exit keeps outer scope
    assert not _fe.side_effects_suppressed()
    try:
        with _fe.suppress_side_effects():
            raise RuntimeError("x")
    except RuntimeError:
        pass
    assert not _fe.side_effects_suppressed()  # exception restored


def test_suppression_does_not_leak_to_worker_thread(sink):
    import threading
    seen = {}
    def _probe():
        seen["suppressed"] = _fe.side_effects_suppressed()
    with _fe.suppress_side_effects():
        t = threading.Thread(target=_probe); t.start(); t.join()
        assert _fe.side_effects_suppressed()
    assert seen["suppressed"] is False  # worker thread has own context


def test_production_eval_after_shadow_sees_unchanged_state(sink, monkeypatch):
    """A shadow evaluation must not advance adaptive/rolling state that a
    later production evaluation observes."""
    from merid.prediction import streaming_calibration as _sc
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    before = dict(getattr(_sc, "_cache", {}) or {})
    ticker = _ticker_for_close(time.time() + 600)
    _se.maybe_emit_scheduled(ticker=ticker, asset="BTC", base_kwargs=_args())
    after_shadow = dict(getattr(_sc, "_cache", {}) or {})
    assert after_shadow == before or (
        set(after_shadow) - set(before) == set() and
        all(after_shadow[k] == before[k] for k in before)
    )
    # production eval after shadow still records its checksum (guard lifted)
    calls = {"n": 0}
    orig = _td.record_state_checksum
    monkeypatch.setattr(_td, "record_state_checksum",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1),
                                         orig(*a, **k)))
    _td._compute_trade_decision_impl(**_args(decision_id="p1a_post_shadow"))
    assert calls["n"] == 1


def test_mutable_input_bundle_not_shared_across_arms(sink, monkeypatch):
    """The shadow kwargs bundle is a copy: per-eval overrides (decision_id,
    route, basis) never mutate the caller's production dict."""
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600")
    base = _args()
    snapshot = dict(base)
    _se.maybe_emit_scheduled(
        ticker=_ticker_for_close(time.time() + 600), asset="BTC",
        base_kwargs=base)
    assert base == snapshot  # caller's bundle untouched


# ---------------------------------------------------------- route / basis --

def test_route_basis_changes_economics_not_forecast(sink):
    """Estimand evidence: entry_price_basis/route affect the entry reference
    price and economics; the canonical probability chain (raw->...->final)
    must be identical.  If this ever diverges, shadow events are the
    production ALGORITHM under standardized inputs, not the deployed pass."""
    d_taker = _td._compute_trade_decision_impl(
        **_args(decision_id="rb_t", route="taker", entry_price_basis="ask"))
    d_maker = _td._compute_trade_decision_impl(
        **_args(decision_id="rb_m", route="maker", entry_price_basis="bid"))
    keys = ["p_yes_raw", "p_yes_pre_anchor", "p_yes_post_anchor",
            "fe_post_walkforward_p_yes", "fe_post_epc_p_yes",
            "fe_post_tail_p_yes", "fe_post_stream_p_yes", "fe_final_p_yes",
            "fe_final_p_no_for_no", "market_anchor_prob"]
    for k in keys:
        a, b = d_taker.indicators.get(k), d_maker.indicators.get(k)
        if a is None or b is None:
            assert a == b, k
        else:
            assert a == pytest.approx(b, abs=1e-12), k


# -------------------------------------------------- identity + runner -----

def test_event_has_three_part_identity(sink):
    _td.compute_trade_decision(**_args())
    (ev,) = _events(sink)
    assert ev["opportunity_id"] == "p1a_test_1"
    assert ev["evaluation_id"] == "p1a_test_1"
    assert ev["forecast_event_id"].startswith("fev_")
    assert ev["record_id"].startswith("rec_")
    assert ev["content_hash"]


def test_runner_dedupes_retransmission_not_attempts(tmp_path):
    """Same record_id replayed = idempotent; two different attempts of one
    opportunity are both preserved (no silent first/last-wins)."""
    ev_path, _ = _synth_events(tmp_path, n=2)
    evs = [json.loads(l) for l in ev_path.read_text().splitlines()]
    # two attempts of opportunity opp_0 with distinct eval/record ids
    a1 = dict(evs[0]); a1.update(opportunity_id="opp_X",
                                 evaluation_id="e1", record_id="rec_1",
                                 content_hash="h1",
                                 opportunity_status="emitted",
                                 actual_evaluation_ts=100.0)
    a2 = dict(evs[0]); a2.update(opportunity_id="opp_X",
                                 evaluation_id="e2", record_id="rec_2",
                                 content_hash="h2", forecast_event_id="fev_y",
                                 opportunity_status="emitted",
                                 actual_evaluation_ts=110.0)
    re_tx = dict(a1)  # byte-identical retransmission of attempt 1
    ev_path.write_text("\n".join(json.dumps(e)
                                 for e in (a1, re_tx, a2)))
    loaded, stats = _ar.load_forecast_events(ev_path)
    assert stats["duplicate_ids"] == 1  # retransmission deduped
    assert len(loaded) == 2             # distinct attempts both kept
    selected, sel = _ar.select_attempts(loaded)
    assert len(selected) == 1           # one attempt selected per opportunity
    assert selected[0]["evaluation_id"] == "e1"  # first emitted in order
    assert sel["superseded_attempts"] == 1


def test_runner_reports_conflicting_envelopes(tmp_path):
    ev_path, _ = _synth_events(tmp_path, n=1)
    evs = [json.loads(l) for l in ev_path.read_text().splitlines()]
    c1 = dict(evs[0]); c1.update(evaluation_id="e", record_id="r1",
                                 content_hash="hA")
    c2 = dict(evs[0]); c2.update(evaluation_id="e", record_id="r2",
                                 content_hash="hB")  # same eval id, diff content
    ev_path.write_text("\n".join(json.dumps(e) for e in (c1, c2)))
    loaded, stats = _ar.load_forecast_events(ev_path)
    assert stats["conflicting_records"] == 1
    assert loaded == []  # conflicting evaluation excluded, not resolved


def test_runner_excludes_late_attempts(tmp_path):
    ev_path, oc_path = _synth_events(tmp_path, n=5)
    evs = [json.loads(l) for l in ev_path.read_text().splitlines()]
    late = dict(evs[0])
    late.update(opportunity_id="opp_late", opportunity_status="late",
                record_id="rec_late", actual_evaluation_ts=200.0)
    ev_path.write_text("\n".join(json.dumps(e) for e in evs + [late]))
    out = tmp_path / "rep.json"
    _ar.main(["--events", str(ev_path), "--outcomes", str(oc_path),
              "--replicates", "50", "--out", str(out)])
    rep = json.loads(out.read_text())
    assert rep["population"]["units_with_outcome"] == 5  # late excluded
    assert rep["population"]["attempt_selection"]["late_excluded"] == 1


def test_opportunity_ledger_reconciliation(tmp_path):
    opp_path = tmp_path / "opps.jsonl"
    rows = [
        {"opportunity_id": "o1", "status": "scheduled"},
        {"opportunity_id": "o1", "status": "emitted"},
        {"opportunity_id": "o2", "status": "scheduled",
         "registered_after_target": True},
        {"opportunity_id": "o2", "status": "late"},
        {"opportunity_id": "o3", "status": "scheduled"},
        {"opportunity_id": "o4", "status": "scheduled"},
        {"opportunity_id": "o4", "status": "missed"},
    ]
    opp_path.write_text("\n".join(json.dumps(r) for r in rows))
    led = _ar.load_opportunity_ledger(opp_path)
    assert led["registrations"] == 4
    assert led["by_status"] == {"emitted": 1, "late": 1, "missed": 1,
                              "unresolved": 1}
    assert led["registered_after_target"] == 1

def test_attempt_rule_first_vs_first_emitted(tmp_path):
    """first_attempt is the conservative primary: an earlier failed attempt
    stays the selected unit (counts as unavailable) and never masquerades
    as a later in-tolerance success; first_emitted is the sensitivity."""
    ev_path, _ = _synth_events(tmp_path, n=1)
    evs = [json.loads(l) for l in ev_path.read_text().splitlines()]
    bad = dict(evs[0]); bad.update(opportunity_id="opp_X", evaluation_id="e1",
                                   record_id="r1", opportunity_status="unavailable",
                                   actual_evaluation_ts=100.0, final_p_yes=None,
                                   forecast_availability="unavailable")
    good = dict(evs[0]); good.update(opportunity_id="opp_X", evaluation_id="e2",
                                    record_id="r2", forecast_event_id="fev_z",
                                    opportunity_status="emitted",
                                    actual_evaluation_ts=110.0)
    ev_path.write_text("\n".join(json.dumps(e) for e in (bad, good)))
    loaded, _ = _ar.load_forecast_events(ev_path)
    sel_p, st_p = _ar.select_attempts(loaded, rule="first_attempt")
    assert sel_p[0]["evaluation_id"] == "e1" and sel_p[0].get("_excluded")
    sel_s, st_s = _ar.select_attempts(loaded, rule="first_emitted")
    assert sel_s[0]["evaluation_id"] == "e2" and not sel_s[0].get("_excluded")
    assert st_p["first_vs_first_emitted_divergence"] == 1
    assert st_p["superseded_statuses"] == {"emitted": 1}

def test_weighted_primary_statistic_not_pooled(tmp_path):
    """Weighted estimand = 1/3 * mean at EACH of {600,300,120} — must differ
    from the pooled mean when horizon supports differ."""
    units = []
    close = 1760000000.0
    # h600: n=2 with d=+0.09 ; h300: n=2 with d=-0.03 ; h120: n=4 with d=0
    for h, ds in ((600, [0.09, 0.09]), (300, [-0.03, -0.03]),
                  (120, [0.0] * 4)):
        for i, d in enumerate(ds):
            m = 0.5
            # choose arms so L(A)-L(P)=d with y=1: P=m, A picked s.t.
            # (A-1)^2 - (m-1)^2 = d  ->  A = 1 - sqrt(0.25 + d)
            a = 1.0 - math.sqrt(max(0.25 + d, 0.0))
            ev = {"market_ticker": "T", "asset": "BTC",
                  "evaluation_source": "scheduled_shadow",
                  "arms": {"P": m, "A": a},
                  "final_p_yes": m, "post_walkforward_p_yes": a,
                  "forecast_availability": "available"}
            units.append({"event": ev, "ticker": "T", "asset": "BTC",
                          "horizon_s": h, "close_ts": close + h,
                          "y": 1, "admitted": False, "completed": True,
                          "source": "scheduled_shadow"})
    res = _ar.weighted_primary_statistic(
        units, horizon_weights={600: 1/3, 300: 1/3, 120: 1/3},
        replicates=200, seed=1)
    pooled = (0.09 + 0.09 - 0.03 - 0.03) / 8
    expect = (0.09 - 0.03 + 0.0) / 3
    assert res["point"] == pytest.approx(expect, abs=1e-9)
    assert res["point"] != pytest.approx(pooled, abs=1e-9)  # not pooled
    assert res["valid_draws"] > 0 and res["ci"] is not None
    # missing horizon -> point None and every draw unsupported
    units2 = [u for u in units if u["horizon_s"] != 120]
    res2 = _ar.weighted_primary_statistic(
        units2, horizon_weights={600: 1/3, 300: 1/3, 120: 1/3},
        replicates=50, seed=1)
    assert res2["point"] is None
    assert res2["valid_draws"] == 0
    assert res2["unsupported_draws"] == 50

def test_shadow_time_budget_defers_visibly(sink, monkeypatch):
    """A zero budget must not evaluate: due horizons stay scheduled (retried
    next cycle) and a deferred ledger row records the skip."""
    monkeypatch.setenv("MERID_SHADOW_HORIZONS_S", "600,300")
    monkeypatch.setenv("MERID_SHADOW_TIME_BUDGET_MS", "0")
    opp_path = sink.parent / "opps.jsonl"
    monkeypatch.setenv("MERID_FORECAST_OPP_LOG_PATH", str(opp_path))
    # close=now+200 -> both horizon targets deterministically due
    ticker = _ticker_for_close(time.time() + 200)
    out = _se.maybe_emit_scheduled(ticker=ticker, asset="BTC",
                                   base_kwargs=_args())
    assert out == [] and _events(sink) == []
    # opportunity still due -> retried on a later cycle
    rec = _se.emitted_opportunities()[f"{ticker}:h600"]
    assert rec["status"] == "scheduled"
    rows = [json.loads(l) for l in opp_path.read_text().splitlines()]
    assert any(r["status"] == "deferred" for r in rows)
    # retry with a real budget -> evaluates and emits
    monkeypatch.setenv("MERID_SHADOW_TIME_BUDGET_MS", "5000")
    out = _se.maybe_emit_scheduled(ticker=ticker, asset="BTC",
                                   base_kwargs=_args())
    assert len(out) == 2 and len(_events(sink)) == 2

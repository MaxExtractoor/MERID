"""Tests for the standalone settlement-outcome exporter."""

import json
from pathlib import Path

import pytest

from merid.analysis import settlement_outcome_exporter as ex
from merid.analysis import calibration_report as cr


def _raw_market(ticker="KXBTC15M-26AUG171130-45", status="settled", result="yes",
                series="KXBTC15M", settle_ts="2026-08-16T12:00:00Z"):
    return {
        "ticker": ticker,
        "series_ticker": series,
        "status": status,
        "result": result,
        "settlement_time": settle_ts,
    }


class FakeClient:
    """Minimal fake Kalshi client with cursor pagination."""

    def __init__(self, pages_by_series, fail_on_series=None):
        self.pages_by_series = pages_by_series  # series -> list of (markets, cursor)
        self.fail_on_series = fail_on_series or set()
        self.calls = []

    async def _request_with_resilience(self, method, endpoint, params=None, operation_name=None):
        self.calls.append((endpoint, dict(params)))
        series = params.get("series_ticker")
        if series in self.fail_on_series:
            class R:
                success = False
                error = "boom"
                data = None
            return R()
        cursor = params.get("cursor")
        pages = self.pages_by_series.get(series, [])
        idx = 0 if not cursor else int(cursor)
        if idx >= len(pages):
            class R:
                success = True
                error = None
                data = {"markets": [], "cursor": None}
            return R()
        markets, next_cursor = pages[idx]

        class R:
            success = True
            error = None
            data = {"markets": markets, "cursor": next_cursor}
        return R()


# 1. Definitive YES/NO normalization ---------------------------------------

def test_normalize_definitive_yes_and_no():
    yes = ex.normalize_market_record(_raw_market(result="yes"))
    assert yes is not None
    assert yes.outcome == "yes" and yes.resolved_yes == 1
    assert yes.asset == "BTC" and yes.series_ticker == "KXBTC15M"
    no = ex.normalize_market_record(_raw_market(result="no"))
    assert no is not None
    assert no.outcome == "no" and no.resolved_yes == 0


# 2. Non-definitive outcomes excluded --------------------------------------

@pytest.mark.parametrize("status,result", [
    ("open", ""), ("open", "yes"), ("closed", ""), ("settled", ""),
    ("settled", "unknown"), ("settled", None), ("voided", "no"), ("settled", "tie"),
    ("finalized", ""), ("finalized", "unknown"),
])
def test_non_definitive_excluded(status, result):
    assert ex.normalize_market_record(_raw_market(status=status, result=result)) is None


def test_finalized_status_accepted_with_definitive_result():
    # Kalshi returns status="finalized" for settled 15m crypto markets.
    ev = ex.normalize_market_record(_raw_market(status="finalized", result="yes"))
    assert ev is not None and ev.resolved_yes == 1
    ev_no = ex.normalize_market_record(_raw_market(status="finalized", result="no"))
    assert ev_no is not None and ev_no.resolved_yes == 0


# 3. Series filter ----------------------------------------------------------

def test_unsupported_series_excluded():
    assert ex.normalize_market_record(_raw_market(series="KXBTC")) is None
    assert ex.normalize_market_record(_raw_market(series="INXD-26AUG")) is None
    eligible, _ = ex.event_series_and_eligibility(_raw_market(series="KXETH15M"))
    assert eligible
    eligible, _ = ex.event_series_and_eligibility(_raw_market(series="KXFED"))
    assert not eligible


# 4/5. Idempotency and corrections ------------------------------------------

def test_rerun_appends_zero_duplicates(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    event = ex.normalize_market_record(_raw_market())
    existing, _ = ex.load_existing_outcomes(out)
    rows1, s1 = ex.plan_appends([event], existing)
    assert s1.appended == 1
    ex.append_rows(out, rows1)

    existing2, _ = ex.load_existing_outcomes(out)
    rows2, s2 = ex.plan_appends([event], existing2)
    assert rows2 == []
    assert s2.duplicates_skipped == 1 and s2.appended == 0
    assert len(out.read_text().strip().splitlines()) == 1


def test_conflicting_outcome_appends_correction_and_latest_wins(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    ev_no = ex.normalize_market_record(_raw_market(result="no"))
    ex.append_rows(out, plan_rows := ex.plan_appends([ev_no], {})[0])
    assert "settlement_outcome" in plan_rows[0]["event_type"]

    ev_yes = ex.normalize_market_record(_raw_market(result="yes"))
    existing, _ = ex.load_existing_outcomes(out)
    rows, summary = ex.plan_appends([ev_yes], existing)
    assert summary.corrections == 1
    assert rows[0]["event_type"] == "settlement_correction"
    assert rows[0]["prior_outcome"] == "no"
    assert rows[0]["outcome"] == "yes"
    ex.append_rows(out, rows)

    # Latest-event-wins resolution is deterministic
    outcomes = cr.load_outcomes(out)
    assert outcomes[ev_yes.ticker] == 1
    latest, _ = ex.load_existing_outcomes(out)
    assert latest[ev_yes.ticker]["outcome"] == "yes"


# 6. Malformed existing JSONL ------------------------------------------------

def test_malformed_existing_rows_counted_and_skipped(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    good = ex.normalize_market_record(_raw_market(ticker="KXBTC15M-T1"))
    ex.append_rows(out, ex.plan_appends([good], {})[0])
    with open(out, "a", encoding="utf-8") as f:
        f.write("not json\n")
        f.write(json.dumps({"ticker": "KXBTC15M-T2"}) + "\n")  # no outcome
        f.write(json.dumps({"outcome": "yes"}) + "\n")          # no ticker
    existing, malformed = ex.load_existing_outcomes(out)
    assert malformed == 3
    assert set(existing) == {"KXBTC15M-T1"}


# 7. Pagination honored --------------------------------------------------------

@pytest.mark.asyncio
async def test_pagination_honored():
    pages = [
        ([_raw_market(ticker="KXBTC15M-T1")], "1"),
        ([_raw_market(ticker="KXBTC15M-T2")], "2"),
        ([_raw_market(ticker="KXBTC15M-T3")], None),
    ]
    client = FakeClient({"KXBTC15M": pages})
    items, errors = await ex.fetch_settled_markets(
        client, "KXBTC15M", 1785542400.0, 1786924800.0)
    assert errors == 0
    assert [m["ticker"] for m in items] == ["KXBTC15M-T1", "KXBTC15M-T2", "KXBTC15M-T3"]
    cursors = [c[1].get("cursor") for c in client.calls]
    assert cursors[0] is None and "1" in cursors and "2" in cursors
    # Window params are sent as unix seconds
    assert client.calls[0][1]["min_close_ts"] == 1785542400
    assert client.calls[0][1]["max_close_ts"] == 1786924800


# 8. Dry run writes nothing ----------------------------------------------------

@pytest.mark.asyncio
async def test_dry_run_mutates_nothing(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    client = FakeClient({"KXBTC15M": [([_raw_market()], None)]})
    summary, rc = await ex.run_export(
        out_path=out, client=client, write=False, run_log_path=None,
        start_iso="2026-08-01T00:00:00Z", end_iso="2026-08-17T00:00:00Z",
    )
    assert rc == 0
    assert summary.definitive == 1
    assert summary.appended == 1  # planned
    assert summary.dry_run is True
    assert not out.exists()


# 9. API failure writes nothing and exits nonzero ------------------------------

@pytest.mark.asyncio
async def test_api_failure_writes_nothing(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    client = FakeClient({"KXBTC15M": [([_raw_market()], None)]},
                        fail_on_series={"KXETH15M"})
    summary, rc = await ex.run_export(
        out_path=out, client=client, write=True, run_log_path=None,
        start_iso="2026-08-01T00:00:00Z", end_iso="2026-08-17T00:00:00Z",
    )
    assert rc == 1
    assert summary.api_errors >= 1
    assert not out.exists()


# 10. Loader joins exporter output to telemetry by ticker -----------------------

@pytest.mark.asyncio
async def test_exporter_output_joins_with_calibration_loader(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    ticker = "KXBTC15M-26AUG171130-45"
    client = FakeClient({
        "KXBTC15M": [([_raw_market(ticker=ticker, result="yes")], None)],
    })
    summary, rc = await ex.run_export(
        out_path=out, client=client, write=True, run_log_path=None,
        series_filter=["KXBTC15M"],
        start_iso="2026-08-01T00:00:00Z", end_iso="2026-08-17T00:00:00Z",
    )
    assert rc == 0 and summary.appended == 1

    outcomes = cr.load_outcomes(out)
    assert outcomes[ticker] == 1

    records = [{
        "type": "decision_record", "asset": "BTC", "ticker": ticker,
        "selected_side": "yes", "model_prob_selected": 0.63,
        "market_p_selected": 0.48, "candidate_generated": True,
        "allocator_selected": True,
    }]
    report = cr.build_report(records, outcomes, {})
    assert report["decision_funnel"]["resolved_records"] == 1
    assert report["slices"]["overall"]["brier_derived_model"] == pytest.approx((0.63 - 1) ** 2)


# 11. Client-side window filter ------------------------------------------------

def test_client_side_window_filter():
    start = ex._parse_ts_seconds("2026-08-16T00:00:00Z")
    end = ex._parse_ts_seconds("2026-08-16T01:00:00Z")
    inside = _raw_market(settle_ts="2026-08-16T00:30:00Z")
    inside["close_time"] = "2026-08-16T00:30:00Z"
    outside = _raw_market(settle_ts="2026-08-15T23:00:00Z")
    outside["close_time"] = "2026-08-15T23:00:00Z"
    no_ts = {"ticker": "KXBTC15M-TX", "series_ticker": "KXBTC15M",
             "status": "settled", "result": "yes"}
    assert ex.market_within_window(inside, start, end) is True
    assert ex.market_within_window(outside, start, end) is False
    assert ex.market_within_window(no_ts, start, end) is None


@pytest.mark.asyncio
async def test_out_of_window_markets_excluded_before_write(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    in_window = _raw_market(ticker="KXBTC15M-T1", settle_ts="2026-08-16T00:30:00Z")
    in_window["close_time"] = "2026-08-16T00:30:00Z"
    out_window = _raw_market(ticker="KXBTC15M-T2", settle_ts="2026-08-15T20:00:00Z")
    out_window["close_time"] = "2026-08-15T20:00:00Z"
    client = FakeClient({"KXBTC15M": [([in_window, out_window], None)]})
    summary, rc = await ex.run_export(
        out_path=out, client=client, write=True, run_log_path=None,
        series_filter=["KXBTC15M"],
        start_iso="2026-08-16T00:00:00Z", end_iso="2026-08-16T01:00:00Z",
    )
    assert rc == 0
    assert summary.fetched == 2
    assert summary.definitive == 1
    assert summary.appended == 1
    outcomes = cr.load_outcomes(out)
    assert set(outcomes) == {"KXBTC15M-T1"}


# 12. Health run log -------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_log_written_for_success_and_api_failure(tmp_path):
    out = tmp_path / "outcomes.jsonl"
    run_log = tmp_path / "runs.jsonl"

    ok_client = FakeClient({"KXBTC15M": [([_raw_market()], None)]})
    summary, rc = await ex.run_export(
        out_path=out, client=ok_client, write=True,
        series_filter=["KXBTC15M"], run_log_path=run_log,
        start_iso="2026-08-01T00:00:00Z", end_iso="2026-08-17T00:00:00Z",
    )
    assert rc == 0
    runs = [json.loads(l) for l in run_log.read_text().splitlines() if l.strip()]
    assert len(runs) == 1
    rec = runs[0]
    assert rec["type"] == "exporter_run"
    for field in ("export_run_id", "started_at_utc", "completed_at_utc",
                  "lookback_hours", "fetched", "eligible_15m_crypto", "definitive",
                  "appended", "duplicates_skipped", "corrections",
                  "ambiguous_skipped", "api_errors", "exit_status"):
        assert field in rec
    assert rec["exit_status"] == 0 and rec["appended"] == 1

    bad_client = FakeClient({}, fail_on_series={"KXBTC15M"})
    summary2, rc2 = await ex.run_export(
        out_path=out, client=bad_client, write=True,
        series_filter=["KXBTC15M"], run_log_path=run_log,
        start_iso="2026-08-01T00:00:00Z", end_iso="2026-08-17T00:00:00Z",
    )
    assert rc2 == 1
    runs = [json.loads(l) for l in run_log.read_text().splitlines() if l.strip()]
    assert len(runs) == 2
    assert runs[1]["exit_status"] == 1 and runs[1]["api_errors"] >= 1

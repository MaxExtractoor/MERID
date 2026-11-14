"""Unit tests for merid.analysis.execution_consistency.

Covers the pure helpers and the episode-level verdict semantics that the
2026-11-14 live-fill audit depends on: chase-aware limit bounds, IOC-exit
unverified semantics, tier classification, and slippage sign convention.
"""

import pytest

from merid.analysis import execution_consistency as ec


def _fill(order_id="ord1", ticker="KXXRP15M-26NOV130630-30", side="yes",
          action="buy", qty=100, ypx=0.70, npx=0.30, ts=1000.0,
          coid="coid1", is_taker=None, raw=None):
    return {
        "fill_id": f"f_{order_id}_{ts}", "trade_id": "t1",
        "order_id": order_id, "client_order_id": coid,
        "intent_id": "i1", "market_ticker": ticker, "side": side,
        "action": action, "quantity_cc": qty,
        "yes_price_dollars": ypx, "no_price_dollars": npx,
        "fee_cost": 0.01, "created_time": ts, "is_live": 1,
        "raw_payload": raw, "decision_trace_id": None,
        "canonical_leg_price_cents": None, "asset": ec._asset(ticker),
        "is_taker": is_taker, "ts": ts,
    }


def _attempt(**kw):
    base = {
        "status": "FILLED", "created_at": 900.0, "decision_id": None,
        "intent_id": None, "ticker": None, "side": "buy_yes",
        "action": "buy", "price_cents": 70, "count_fp": 1.0,
        "tif": "gtc", "liquidity_role": "maker", "post_only": True,
        "resolved_mode": "maker", "lane": "pinned_fav",
        "snapshot_ts": None, "decision_id_payload": None,
        "build_sha": "abc", "entry_or_exit": "entry",
        "submission_attempted": True, "route_status": "filled",
        "exchange_order_id": None, "chase_cap_cents": None,
        "entry_price_cents": None, "limit_semantics": "entry_price_only",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _clear_exchange_index():
    ec._ATTEMPT_BY_EXCHANGE_ID = {}
    yield
    ec._ATTEMPT_BY_EXCHANGE_ID = {}


# ------------------------------------------------------------- helpers

def test_asset_mapping():
    assert ec._asset("KXBTC15M-26NOV130630-30") == "BTC"
    assert ec._asset("KXXRP15M-26NOV130630-30") == "XRP"
    assert ec._asset("KXDOGE15M-26NOV130630-30") == "DOGE"
    assert ec._asset("OTHER") == "?"


def test_norm_side_action():
    assert ec._norm_side_action("buy_yes", "buy") == ("yes", True)
    assert ec._norm_side_action("buy_no", "buy") == ("no", True)
    assert ec._norm_side_action("sell_yes", "sell") == ("yes", False)
    assert ec._norm_side_action("yes", "buy") == ("yes", True)
    assert ec._norm_side_action("no", "sell") == ("no", False)
    assert ec._norm_side_action("???", "buy") == (None, True)


def test_leg_price():
    f = _fill(ypx=0.70, npx=0.30)
    assert ec._leg_price(f, "yes") == pytest.approx(70.0)
    assert ec._leg_price(f, "no") == pytest.approx(30.0)
    assert ec._leg_price({**f, "yes_price_dollars": None}, "yes") is None


# ------------------------------------------------------- episode verdicts

def _run(fills, attempts, snaps=None, arch=None):
    snaps = snaps or {"by_decision": {}, "by_ticker": {}}
    ec._ATTEMPT_BY_EXCHANGE_ID = {
        a["exchange_order_id"]: a for a in attempts.values()
        if a.get("exchange_order_id")}
    return ec.analyze(fills, attempts, snaps, arch or {})


def test_chase_cap_buy_is_consistent():
    """Fill at chase cap is consistent — observed live pattern."""
    att = _attempt(chase_cap_cents=98, entry_price_cents=96,
                   limit_semantics="entry_chase_cap",
                   exchange_order_id="ord1")
    rows = _run([_fill(ypx=0.98)], {"coid1": att})
    assert rows[0]["violations"] == []
    assert rows[0]["verdict"] == "instruction_consistent"
    assert rows[0]["bound_source"] == "chase_cap_recorded"


def test_buy_beyond_chase_cap_is_violation():
    att = _attempt(chase_cap_cents=98, entry_price_cents=96,
                   limit_semantics="entry_chase_cap",
                   exchange_order_id="ord1")
    rows = _run([_fill(ypx=0.99)], {"coid1": att})
    assert "buy_fillabove_effective_limit" in rows[0]["violations"]
    assert rows[0]["verdict"] == "genuine_violation"


def test_ioc_exit_breach_is_unverified_not_violation():
    """IOC exit below requested_limit needs the historical order record."""
    att = _attempt(price_cents=70, side=None, action=None,
                   limit_semantics="ioc_exit_requested_limit",
                   exchange_order_id="ord1", entry_or_exit="exit")
    rows = _run([_fill(side="yes", action="sell", ypx=0.67)],
                {"coid1": att})
    assert rows[0]["violations"] == []
    assert "ioc_exit_limit_breach_needs_order_record" in \
        rows[0]["unverified_semantics"]
    assert rows[0]["verdict"] == "timing_indeterminate"


def test_overfill_is_violation():
    att = _attempt(count_fp=1.0, exchange_order_id="ord1")
    rows = _run([_fill(qty=200)], {"coid1": att})
    assert "overfill_vs_order_qty" in rows[0]["violations"]
    assert rows[0]["verdict"] == "genuine_violation"


def test_post_only_taker_fill_is_violation():
    att = _attempt(post_only=True, exchange_order_id="ord1")
    rows = _run([_fill(is_taker=True)], {"coid1": att})
    assert "post_only_taker_fill" in rows[0]["violations"]


def test_tier_a_with_archive_window():
    att = _attempt(exchange_order_id="ord1")
    arch = {"KXXRP15M-26NOV130630-30": [(900.0, 2000.0)]}
    rows = _run([_fill(ts=1000.0)], {"coid1": att}, arch=arch)
    assert rows[0]["tier"] == "A"
    assert rows[0]["verdict"] == "event_replay_comparison"


def test_tier_d_no_attempt():
    rows = _run([_fill()], {})
    assert rows[0]["tier"] == "D"
    assert rows[0]["verdict"] == "coverage_insufficient"


def test_slippage_sign_convention():
    """Buy slippage = fill - decision_ask ; sell = decision_bid - fill."""
    snaps = {"by_decision": {}, "by_ticker": {
        "KXXRP15M-26NOV130630-30": [
            (900.0, 60, 65, 35, 40, 5, True)]}}
    att = _attempt(exchange_order_id="ord1", decision_id=None)
    # buy yes at 70 vs decision ask 65 -> +5 worse
    rows = _run([_fill(ypx=0.70, ts=1000.0)], {"coid1": att}, snaps=snaps)
    assert rows[0]["slippage_cents_vs_decision"] == pytest.approx(5.0)
    # sell yes at 60 vs decision bid 60 -> 0
    rows = _run([_fill(side="yes", action="sell", ypx=0.60, ts=1000.0)],
                {"coid1": _attempt(exchange_order_id="ord1",
                                   side="sell_yes", action="sell")},
                snaps=snaps)
    assert rows[0]["slippage_cents_vs_decision"] == pytest.approx(0.0)


def test_env_default_chase_bound_marks_unverified(monkeypatch):
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "5")
    att = _attempt(price_cents=63, side="buy_no", action="buy",
                   exchange_order_id="ord1")
    rows = _run([_fill(side="no", action="buy", ypx=0.30, npx=0.65,
                       ts=1000.0)], {"coid1": att})
    # NO leg fill 65c <= 63+5 bound -> consistent; bound_source flags that
    # the bound came from current config rather than the payload.
    assert rows[0]["violations"] == []
    assert rows[0]["bound_source"] == "env_default_chase_unverified"
    assert rows[0]["verdict"] == "instruction_consistent"

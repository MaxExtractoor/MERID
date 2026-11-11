import json
import sqlite3

import pytest

from scripts.scalp_policy_comparison import compare, load_data, quote_path_trade
from scripts.window_funnel_report import Funnel, STAGE_POS_EV


def _quotes(target=56):
    return [(float(ts), target if ts >= 32 else 49, 50) for ts in range(22, 88, 5)]


def _candidate(asset):
    return {"ts": 0, "ticker": f"KX{asset}15M-26NOV111600-00", "side": "yes",
            "price": 50, "edge": 4, "required": 2, "tte": 600}


def test_quote_path_uses_delayed_ask_and_first_executable_target():
    trade = quote_path_trade(_quotes(), 0, latency_s=21, target_cents=5)
    assert trade == (22, 50, 32, 56, "target")


def test_quote_path_stops_before_later_winner():
    quotes = [(22, 49, 50), (27, 44, 45), (32, 75, 76)]
    assert quote_path_trade(quotes, 0, latency_s=21, target_cents=5)[-2:] == (44, "stop")


@pytest.mark.parametrize("quotes", [[], [(50, 49, 50)], [(22, 49, 50), (80, 60, 61)],
                                    [(22, 49, 50), (27, 49, 50)]])
def test_quote_path_excludes_missing_or_gapped_coverage(quotes):
    assert quote_path_trade(quotes, 0, latency_s=21, target_cents=5) is None


def test_comparison_diversifies_without_multiplying_window_budget():
    candidates = [_candidate(asset) for asset in ("BTC", "ETH", "SOL")]
    books = {(c["ticker"], c["side"]): _quotes() for c in candidates}
    result = compare(candidates, books, targets=(5,))
    assert result["conservative:target_5c"]["trades"] == 3
    assert result["mixed:target_5c"]["trades"] == 2
    assert result["aggressive:target_5c"]["trades"] == 1
    for rec in result.values():
        assert rec["contracts"] == 6
        assert 0 < rec["quote_path_upper_bound_net_cents"] < 36


def test_comparison_preserves_refresh_ceiling_and_cost_gates():
    c = _candidate("BTC")
    result = compare([c], {(c["ticker"], "yes"): _quotes()}, latency_s=31, targets=(5,))
    assert result["conservative:target_5c"]["trades"] == 0
    c["edge"] = -1
    result = compare([c], {(c["ticker"], "yes"): _quotes()}, targets=(5,))
    assert all(rec["trades"] == 0 for rec in result.values())


def test_quote_timeout_is_not_settlement_or_best_future_price():
    quotes = [(float(ts), 51, 52) for ts in range(22, 88, 5)]
    trade = quote_path_trade(quotes, 0, latency_s=21, target_cents=20)
    assert trade == (22, 52, 82, 51, "timeout")


def test_funnel_does_not_promote_negative_lane_ev_to_positive():
    funnel = Funnel()
    row = ("cand:maker_bid", "cand", 0, "KXBTC15M-T", "BTC", "yes", "ENTER",
           "selected", "pinned_fav", 600, "[]", "{}", -4, -5)
    funnel.add_decision_row(row)
    assert sum(n for (stage, _, _), n in funnel.stage_asset_side.items() if stage == STAGE_POS_EV) == 0
    assert "cand:maker_bid" in funnel.emitted_decisions


def test_funnel_requires_venue_acceptance_evidence():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE strategy_decision_events (decision_id, event_type, stage, reason_code, reason_detail_json)")
    rows = [
        ("stale:taker", "ORDER_SUBMITTED", "EXECUTION", None, json.dumps({"exchange_order_id": None})),
        ("stale:taker", "ROUTER_REJECTED", "EXECUTION", "stale_decision", "{}"),
        ("accepted:taker", "ORDER_SUBMITTED", "EXECUTION", None, json.dumps({"exchange_order_id": "venue-1"})),
        ("filled:taker", "ORDER_FILLED", "EXECUTION", None, "{}"),
    ]
    conn.executemany("INSERT INTO strategy_decision_events VALUES (?,?,?,?,?)", rows)
    funnel = Funnel()
    funnel.emitted_decisions.update(r[0] for r in rows)
    funnel.add_events(conn)
    assert funnel.accepted == {"accepted:taker", "filled:taker"}
    assert funnel.filled == {"filled:taker"}
    assert "stale:taker" in funnel.wire_attempt
    conn.close()


def test_loader_opens_database_read_only_and_handles_no_decisions(tmp_path):
    db = tmp_path / "audit.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE strategy_decisions(decision_ts REAL)")
    assert load_data(db, 0.1) == ([], {})

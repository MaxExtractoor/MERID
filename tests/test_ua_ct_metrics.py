"""Tests for Universal Agent ↔ Kalshi CT shared metrics."""

from merid.prediction import ua_ct_metrics as m


def setup_function() -> None:
    m.reset_for_tests()


def test_record_and_merge_sweep_all() -> None:
    m.record_ct_cycle(
        cycle=2,
        catalog_markets=100,
        universe_markets=12,
        evaluated=5,
        approved=1,
        vetoed=4,
        orders_submitted=0,
    )
    m.record_order_accept()
    m.record_order_reject()
    merged = m.merge_agent_dict(
        "sweep-all",
        {
            "cycles_run": 0,
            "markets_evaluated": 0,
            "orders_placed": 0,
            "orders_rejected": 0,
        },
    )
    assert merged["cycles_run"] == 2
    assert merged["markets_evaluated"] == 5
    assert merged["orders_placed"] == 1
    assert merged["orders_rejected"] == 1
    assert "ct_metrics" in merged


def test_merge_ignores_other_agent() -> None:
    m.record_ct_cycle(
        cycle=1,
        catalog_markets=1,
        universe_markets=1,
        evaluated=3,
        approved=0,
        vetoed=3,
        orders_submitted=0,
    )
    other = m.merge_agent_dict("other", {"markets_evaluated": 9})
    assert other["markets_evaluated"] == 9

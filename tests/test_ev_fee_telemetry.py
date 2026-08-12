"""Unit tests for the EV + fee telemetry analyzer."""

import pytest

from scripts.analyze_ev_fee_telemetry import (
    EvFeeTelemetryAnalyzer,
    FillFeeRecord,
    SignalEvRecord,
)


SIGNAL_LINE = (
    "2026-08-12 01:09:22 | INFO | merid.prediction.agent_grid_15m | [SIGNAL-EV-GATE] "
    "asset=DOGE side=yes action=buy quote_price_cents=16 quote_source=yes_ask "
    "displayed_depth=27 requested_contracts=1 market_probability=0.1600 model_probability=0.1731 "
    "raw_model_edge_cents=1.3139 exchange_fee_cents=2.00 expected_entry_impact_cents=0.00 "
    "expected_exit_fee_reserve_cents=0.00 expected_exit_impact_reserve_cents=0.00 "
    "uncertainty_buffer_cents=0.00 max_slippage_guard_cents=5 all_in_expected_cost_cents=18.00 "
    "robust_cost_cents=23.00 ev_expected_cents=-0.6861 ev_robust_cents=-5.6861 decision=no_trade"
)

FILL_LINE = (
    "2026-08-12 01:06:33 | INFO | merid.event_venues.kalshi.fills_ledger | [FILL-FEE-AUDIT] "
    "fill_id=test-fill-001 ticker=KXBTC15M-26AUG120115-15 order_id=test-order-001 side=yes "
    "action=buy contracts=1.00 limit_price_cents=54 fill_price_cents=54 modeled_fee_cents=2.00 "
    "reported_exchange_fee_cents=2 fee_delta_cents=0.00 series_fee_multiplier=0.0700 "
    "liquidity_role=taker"
)


def test_parse_signal_line():
    record = EvFeeTelemetryAnalyzer.parse_signal_line(SIGNAL_LINE)
    assert record is not None
    assert record.asset == "DOGE"
    assert record.side == "yes"
    assert record.quote_price_cents == 16
    assert record.displayed_depth == 27
    assert record.requested_contracts == 1
    assert record.exchange_fee_cents == 2.0
    assert record.max_slippage_guard_cents == 5
    assert record.ev_robust_cents == pytest.approx(-5.6861)


def test_parse_signal_line_unknown_depth():
    line = SIGNAL_LINE.replace("displayed_depth=27", "displayed_depth=unknown")
    record = EvFeeTelemetryAnalyzer.parse_signal_line(line)
    assert record is not None
    assert record.displayed_depth is None


def test_parse_fill_line():
    record = EvFeeTelemetryAnalyzer.parse_fill_line(FILL_LINE)
    assert record is not None
    assert record.fill_id == "test-fill-001"
    assert record.ticker == "KXBTC15M-26AUG120115-15"
    assert record.side == "yes"
    assert record.fill_price_cents == 54
    assert record.modeled_fee_cents == 2.0
    assert record.reported_exchange_fee_cents == 2
    assert record.liquidity_role == "taker"


def test_what_if_computation():
    analyzer = EvFeeTelemetryAnalyzer(
        signals=[
            SignalEvRecord(
                asset="DOGE",
                side="yes",
                action="buy",
                quote_price_cents=16,
                quote_source="yes_ask",
                displayed_depth=27,
                requested_contracts=1,
                market_probability=0.16,
                model_probability=0.1731,
                raw_model_edge_cents=1.3139,
                exchange_fee_cents=2.0,
                expected_entry_impact_cents=0.0,
                expected_exit_fee_reserve_cents=0.0,
                expected_exit_impact_reserve_cents=0.0,
                uncertainty_buffer_cents=0.0,
                max_slippage_guard_cents=5,
                all_in_expected_cost_cents=18.0,
                robust_cost_cents=23.0,
                ev_expected_cents=-0.6861,
                ev_robust_cents=-5.6861,
                decision="no_trade",
            )
        ]
    )
    what = analyzer.compute_what_if()[0]
    # Parabolic fee at 16c, 1 contract = 1c, so legacy overstates by 1c.
    assert what.parabolic_fee_cents == pytest.approx(1.0)
    assert what.fee_overstatement_cents == pytest.approx(1.0)
    assert what.ev_without_slippage_guard == pytest.approx(-0.6861)
    assert what.ev_with_parabolic_fee == pytest.approx(-4.6861)
    assert what.ev_parabolic_no_slippage_guard == pytest.approx(0.3139)


def test_bucket_signals():
    analyzer = EvFeeTelemetryAnalyzer(
        signals=[
            SignalEvRecord(
                asset="DOGE", side="yes", action="buy", quote_price_cents=16,
                quote_source="yes_ask", displayed_depth=27, requested_contracts=1,
                market_probability=0.16, model_probability=0.1731,
                raw_model_edge_cents=1.3139, exchange_fee_cents=2.0,
                expected_entry_impact_cents=0.0, expected_exit_fee_reserve_cents=0.0,
                expected_exit_impact_reserve_cents=0.0, uncertainty_buffer_cents=0.0,
                max_slippage_guard_cents=5, all_in_expected_cost_cents=18.0,
                robust_cost_cents=23.0, ev_expected_cents=-0.6861,
                ev_robust_cents=-5.6861, decision="no_trade",
            )
        ]
    )
    buckets = analyzer.bucket_signals()
    key = "DOGE|yes|15-19c"
    assert key in buckets
    b = buckets[key]
    assert b.count == 1
    assert b.would_pass_parabolic_no_guard == 1
    assert b.would_pass_without_slippage == 0


def test_bucket_fills():
    analyzer = EvFeeTelemetryAnalyzer(
        fills=[
            FillFeeRecord(
                fill_id="f1", ticker="KXBTC15M-26AUG120115-15", order_id="o1",
                side="yes", action="buy", contracts=1.0, limit_price_cents=54,
                fill_price_cents=54, modeled_fee_cents=2.0,
                reported_exchange_fee_cents=2, fee_delta_cents=0.0,
                series_fee_multiplier=0.07, liquidity_role="taker",
            )
        ]
    )
    buckets = analyzer.bucket_fills()
    key = "KXBTC15M|yes|50-65c"
    assert key in buckets
    b = buckets[key]
    assert b.count == 1
    assert b.has_modeled
    assert b.avg_modeled_fee_cents == pytest.approx(2.0)
    assert b.avg_reported_fee_per_contract_cents == pytest.approx(2.0)
    assert b.avg_canonical_fee_cents == pytest.approx(2.0)

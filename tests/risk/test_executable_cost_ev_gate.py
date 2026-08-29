"""Tests for the executable-cost EV gate."""

from decimal import Decimal

import pytest

from merid.execution.order_decision_schema import OrderDecisionRecord
from merid.risk.executable_cost_ev_gate import (
    EVInput,
    evaluate_executable_cost_ev,
    evaluate_executable_cost_ev_from_record,
)


class TestExecutableCostEVGate:
    """The EV gate must be the sole authority for new entries."""

    def test_positive_net_ev_allows_trade(self, monkeypatch, tmp_path):
        """A trade with positive net EV and acceptable tail risk passes."""
        monkeypatch.setenv("MERID_EV_GATE_MIN_DOLLAR_EV", "0.00")
        monkeypatch.setenv("MERID_EV_GATE_MIN_EV_TO_TAIL_RATIO", "0.00")

        result = evaluate_executable_cost_ev(
            EVInput(
                p_model=Decimal("0.60"),
                p_exec=Decimal("0.50"),
                qty_cc=200,
                entry_fee_per_contract=Decimal("0.01"),
                expected_exit_cost_per_contract=Decimal("0.01"),
                adverse_selection_reserve_per_contract=Decimal("0.00"),
                uncertainty_reserve_per_contract=Decimal("0.00"),
                quote_age_ms=5,
            )
        )

        assert result.allowed is True
        assert result.count == 2
        assert result.gross_ev == Decimal("0.20")
        assert result.net_ev == Decimal("0.16")
        # tail risk = (1 - 0.60) * 2 = 0.80; net/tail = 0.16 / 0.80 = 0.20
        assert result.ev_to_tail_ratio == Decimal("0.2000")

    def test_negative_net_ev_rejects_trade(self, monkeypatch, tmp_path):
        """A trade whose costs exceed gross edge is rejected."""
        monkeypatch.setenv("MERID_EV_GATE_MIN_DOLLAR_EV", "0.00")
        monkeypatch.setenv("MERID_EV_GATE_MIN_EV_TO_TAIL_RATIO", "0.00")

        result = evaluate_executable_cost_ev(
            EVInput(
                p_model=Decimal("0.51"),
                p_exec=Decimal("0.50"),
                qty_cc=100,
                entry_fee_per_contract=Decimal("0.02"),
                expected_exit_cost_per_contract=Decimal("0.02"),
                quote_age_ms=5,
            )
        )

        assert result.allowed is False
        assert any("net_ev_below_min_dollar" in r for r in result.reasons)

    def test_stale_executable_price_rejects(self, monkeypatch, tmp_path):
        """The gate rejects when the executable price is stale; no midpoint fallback."""
        monkeypatch.setenv("MERID_EV_GATE_MIN_DOLLAR_EV", "0.00")
        monkeypatch.setenv("MERID_EV_GATE_MIN_EV_TO_TAIL_RATIO", "0.00")

        result = evaluate_executable_cost_ev(
            EVInput(
                p_model=Decimal("0.60"),
                p_exec=Decimal("0.50"),
                qty_cc=100,
                quote_age_ms=60_000,
                quote_stale_threshold_ms=10_000,
            )
        )

        assert result.allowed is False
        assert "stale_executable_price" in result.reasons[0]

    def test_missing_executable_price_rejects(self, monkeypatch, tmp_path):
        """The gate rejects when p_exec is missing."""
        monkeypatch.setenv("MERID_EV_GATE_MIN_DOLLAR_EV", "0.00")

        result = evaluate_executable_cost_ev(
            EVInput(
                p_model=Decimal("0.60"),
                p_exec=Decimal("NaN"),
                qty_cc=100,
            )
        )

        assert result.allowed is False
        assert "missing_executable_price" in result.reasons

    def test_minimum_dollar_ev_threshold(self, monkeypatch, tmp_path):
        """Trades with net EV below the dollar threshold are rejected."""
        monkeypatch.setenv("MERID_EV_GATE_MIN_DOLLAR_EV", "0.05")
        monkeypatch.setenv("MERID_EV_GATE_MIN_EV_TO_TAIL_RATIO", "0.00")

        result = evaluate_executable_cost_ev(
            EVInput(
                p_model=Decimal("0.55"),
                p_exec=Decimal("0.50"),
                qty_cc=100,
                entry_fee_per_contract=Decimal("0.01"),
                expected_exit_cost_per_contract=Decimal("0.01"),
                quote_age_ms=5,
            )
        )

        # Net EV = 0.05 - 0.02 = 0.03 < 0.05
        assert result.allowed is False
        assert any("net_ev_below_min_dollar" in r for r in result.reasons)

    def test_ev_to_tail_ratio_threshold(self, monkeypatch, tmp_path):
        """Trades with tiny edge relative to tail risk are rejected."""
        monkeypatch.setenv("MERID_EV_GATE_MIN_DOLLAR_EV", "0.00")
        monkeypatch.setenv("MERID_EV_GATE_MIN_EV_TO_TAIL_RATIO", "0.10")

        # p=0.52, exec=0.50, fees 0.01 => net 0.01 on 1 contract.
        # tail risk = 0.48, ratio ~ 0.02 < 0.10
        result = evaluate_executable_cost_ev(
            EVInput(
                p_model=Decimal("0.52"),
                p_exec=Decimal("0.50"),
                qty_cc=100,
                entry_fee_per_contract=Decimal("0.01"),
                expected_exit_cost_per_contract=Decimal("0.00"),
                quote_age_ms=5,
            )
        )

        assert result.allowed is False
        assert any("ev_to_tail_ratio_below_min" in r for r in result.reasons)

    def test_evaluate_from_record(self, monkeypatch, tmp_path):
        """The gate can be evaluated from an OrderDecisionRecord."""
        monkeypatch.setenv("MERID_EV_GATE_MIN_DOLLAR_EV", "0.00")
        monkeypatch.setenv("MERID_EV_GATE_MIN_EV_TO_TAIL_RATIO", "0.00")

        record = OrderDecisionRecord(
            decision_id="dec-001",
            run_id="run-001",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            p_selected=Decimal("0.60"),
            executable_price_cents=50,
            intended_qty_cc=200,
            entry_fee_per_contract=Decimal("0.01"),
            expected_exit_cost_per_contract=Decimal("0.01"),
            executable_price_age_ms=5,
        )

        result = evaluate_executable_cost_ev_from_record(record)
        assert result.allowed is True
        assert result.count == 2
        assert result.net_ev == Decimal("0.16")

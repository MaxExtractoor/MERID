"""Sign-correlation tests for hybrid model components.

These tests compute whether each decomposed delta (velocity, MACD, RSI, OBI,
regime, FVG) pushes the model in the direction of the actual settlement.  A
negative mean signed contribution for a component is evidence the component is
mean-reversion-signed in a momentum market and should be disabled until proven
out-of-sample positive.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from merid.prediction.hybrid_audit import (
    _component_contributions,
    _derive_economic_side,
    _settlement_sign,
    compute_component_sign_correlation,
    generate_decision_to_settlement_audit,
    generate_expiry_alpha_entries,
    generate_intracontract_exit_trades,
    load_fills_csv,
    run_audit,
)


@pytest.fixture
def sample_fills_df():
    """Small synthetic fill ledger with one held-to-expiry and one round-trip."""
    return pd.DataFrame([
        {
            "fill_id": "f-entry-held",
            "market_ticker": "KXBTC15M-TEST",
            "asset": "BTC",
            "entry_or_exit": "entry",
            "is_fully_closed": False,
            "remaining_open_cc": 200,
            "canonical_position_side": "yes",
            "canonical_position_action": "buy",
            "economic_side": "YES",
            "canonical_leg_price_cents": 55,
            "quantity_cc": 200,
            "signed_yes_delta_cc": 200,
            "market_result": "YES",
            "settlement_value_cents": 100,
            "unrealized_gross_pnl_cents": 45,
            "unrealized_fee_cents": 2,
            "unrealized_net_pnl_cents": 43,
            "total_settled_pnl_cents": 43,
            "hold_time_seconds": 900,
            "round_trip_ids": "",
            "paired_fill_ids": "",
            "realized_gross_pnl_cents": 0,
            "realized_fee_cents": 0,
            "realized_net_pnl_cents": 0,
        },
        {
            "fill_id": "f-entry-exit",
            "market_ticker": "KXBTC15M-TEST",
            "asset": "BTC",
            "entry_or_exit": "entry",
            "is_fully_closed": True,
            "remaining_open_cc": 0,
            "canonical_position_side": "no",
            "canonical_position_action": "buy",
            "economic_side": "NO",
            "canonical_leg_price_cents": 45,
            "quantity_cc": 200,
            "signed_yes_delta_cc": -200,
            "market_result": "NO",
            "settlement_value_cents": 0,
            "realized_gross_pnl_cents": 20,
            "realized_fee_cents": 2,
            "realized_net_pnl_cents": 18,
            "total_settled_pnl_cents": 18,
            "hold_time_seconds": 300,
            "round_trip_ids": "rt_001",
            "paired_fill_ids": "f-exit",
        },
        {
            "fill_id": "f-exit",
            "market_ticker": "KXBTC15M-TEST",
            "asset": "BTC",
            "entry_or_exit": "exit",
            "is_fully_closed": True,
            "remaining_open_cc": 0,
            "canonical_position_side": "no",
            "canonical_position_action": "sell",
            "economic_side": "NO",
            "canonical_leg_price_cents": 30,
            "quantity_cc": 200,
            "signed_yes_delta_cc": 200,
            "market_result": "NO",
            "settlement_value_cents": 0,
            "realized_gross_pnl_cents": -20,
            "realized_fee_cents": 0,
            "realized_net_pnl_cents": -20,
            "total_settled_pnl_cents": -20,
            "hold_time_seconds": 300,
            "round_trip_ids": "rt_001",
            "paired_fill_ids": "f-entry-exit",
        },
    ])


def test_derive_economic_side():
    row = pd.Series({"canonical_position_side": "yes", "canonical_position_action": "buy"})
    assert _derive_economic_side(row) == "YES"
    row = pd.Series({"canonical_position_side": "no", "canonical_position_action": "sell"})
    assert _derive_economic_side(row) == "YES"
    row = pd.Series({"canonical_position_side": "yes", "canonical_position_action": "sell"})
    assert _derive_economic_side(row) == "NO"


def test_settlement_sign():
    assert _settlement_sign(pd.Series({"market_result": "YES", "economic_side": "YES"})) == 1.0
    assert _settlement_sign(pd.Series({"market_result": "NO", "economic_side": "YES"})) == -1.0
    assert _settlement_sign(pd.Series({"market_result": "NO", "economic_side": "NO"})) == 1.0
    assert _settlement_sign(pd.Series({"market_result": "", "economic_side": "YES"})) == 0.0


def test_generate_expiry_alpha_entries(sample_fills_df):
    alpha = generate_expiry_alpha_entries(sample_fills_df)
    assert len(alpha) == 1
    assert alpha.iloc[0]["fill_id"] == "f-entry-held"
    assert alpha.iloc[0]["economic_side"] == "YES"


def test_generate_intracontract_exit_trades(sample_fills_df):
    intracontract = generate_intracontract_exit_trades(sample_fills_df)
    assert len(intracontract) == 1
    assert intracontract.iloc[0]["round_trip_id"] == "rt_001"
    # Entry total settled 18 plus exit total settled -20 equals -2 for the round-trip.
    assert intracontract.iloc[0]["realized_net_pnl_cents"] == pytest.approx(-2.0)


def test_component_contributions():
    row = {
        "delta_velocity": 0.10,
        "delta_macd": -0.05,
        "delta_rsi": 0.02,
        "delta_obi": -0.03,
        "delta_regime": 0.01,
        "delta_fvg": -0.02,
        "raw_delta_total": 0.03,
    }
    contribs = _component_contributions(row, settlement_sign=1.0)
    assert contribs["velocity"] == pytest.approx(0.10)
    assert contribs["macd"] == pytest.approx(-0.05)


def test_compute_component_sign_correlation():
    """Synthetic positive and negative examples produce expected means."""
    with tempfile.TemporaryDirectory() as tmpdir:
        decomp_path = Path(tmpdir) / "decomp.jsonl"
        settlement_path = Path(tmpdir) / "settlement.csv"

        records = [
            {
                "decision_id": "d1",
                "p_yes_bachelier": 0.5,
                "delta_velocity": 0.10,
                "delta_macd": -0.05,
                "delta_rsi": 0.02,
                "delta_obi": -0.03,
                "delta_regime": 0.01,
                "delta_fvg": -0.02,
                "raw_delta_total": 0.03,
            },
            {
                "decision_id": "d2",
                "p_yes_bachelier": 0.5,
                "delta_velocity": -0.08,
                "delta_macd": 0.06,
                "delta_rsi": -0.01,
                "delta_obi": 0.04,
                "delta_regime": -0.02,
                "delta_fvg": 0.03,
                "raw_delta_total": 0.02,
            },
        ]
        with open(decomp_path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        # d1: model pushes YES, market settles YES -> velocity positive contribution
        # d2: model pushes NO, market settles NO -> velocity positive contribution
        # We set both settlement signs to +1 for YES and NO by economic side mapping.
        settlement = pd.DataFrame([
            {"decision_id": "d1", "economic_side": "YES", "market_result": "YES"},
            {"decision_id": "d2", "economic_side": "NO", "market_result": "NO"},
        ])
        settlement.to_csv(settlement_path, index=False)

        correlation = compute_component_sign_correlation(decomp_path, settlement, min_samples=1)
        # velocity: d1=+0.10*+1=0.10, d2=-0.08*+1= -0.08 (because economic side matches market)
        # Wait, settlement sign is +1 if market_result==economic_side, so both are +1.
        # mean = (0.10 - 0.08) / 2 = 0.01
        assert correlation["delta_velocity"]["n"] == 2
        assert correlation["delta_velocity"]["mean_signed_contribution"] == pytest.approx(0.01)


def test_held_to_expiry_win_rate_from_last_24h():
    """Compute the held-to-expiry win rate from the existing paired CSV.

    This is an informational test by default; it reports the win rate so the
    regression is visible.  Set `MERID_HELD_EXPIRY_MIN_WIN_RATE` to enforce a
    threshold and fail the build if the rate is below it.
    """
    csv_path = Path(__file__).resolve().parents[1] / "reports" / "last_24h_fills_with_pairing_and_settlement_20260826_141146.csv"
    if not csv_path.exists():
        pytest.skip("no 24h fill sample available")

    df = load_fills_csv(csv_path)
    alpha = generate_expiry_alpha_entries(df)
    if alpha.empty:
        pytest.skip("no held-to-expiry entries")

    alpha["won"] = alpha.apply(lambda r: str(r["market_result"]).upper() == str(r["economic_side"]).upper(), axis=1)
    win_rate = float(alpha["won"].mean())

    n = len(alpha)
    wins = int(alpha["won"].sum())
    print(f"held-to-expiry win rate: {wins}/{n} = {win_rate:.1%}")

    min_rate_env = os.environ.get("MERID_HELD_EXPIRY_MIN_WIN_RATE")
    if min_rate_env:
        min_rate = float(min_rate_env)
        assert win_rate >= min_rate, f"held-to-expiry win rate {win_rate:.2%} below threshold {min_rate:.2%}"

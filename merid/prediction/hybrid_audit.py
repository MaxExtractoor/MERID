"""Hybrid-model audit tools: ledger generation and component sign-correlation.

Produces the three canonical audit ledgers and computes per-component
signed-contribution statistics for model diagnostics.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _derive_economic_side(row: pd.Series) -> str:
    """YES = long exposure to the YES outcome, NO = long NO."""
    side = str(row.get("canonical_position_side", "")).lower()
    action = str(row.get("canonical_position_action", "")).lower()
    if (side == "yes" and action == "buy") or (side == "no" and action == "sell"):
        return "YES"
    return "NO"


def load_fills_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    # Normalize booleans that are stored as 'True'/'False' or 0/1
    for col in ["is_fully_closed", "is_exit", "reduce_only", "is_unmatched", "reconciled"]:
        if col in df.columns:
            df[col] = df[col].map({"True": True, "False": False, "1": True, "0": False, "": None, "None": None})
    numeric_cols = [
        "count_fp", "yes_price_dollars", "no_price_dollars", "fee_cost", "proceeds_dollars",
        "quantity_cc", "signed_yes_delta_cc", "quantity_abs_cc", "paired_quantity_cc",
        "remaining_open_cc", "settlement_value_cents", "realized_gross_pnl_cents",
        "realized_fee_cents", "realized_net_pnl_cents", "unrealized_gross_pnl_cents",
        "unrealized_fee_cents", "unrealized_net_pnl_cents", "total_settled_pnl_cents",
        "hold_time_seconds", "canonical_leg_price_cents", "canonical_yes_delta_cc",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "economic_side" not in df.columns:
        df["economic_side"] = df.apply(_derive_economic_side, axis=1)
    return df


def generate_expiry_alpha_entries(df: pd.DataFrame) -> pd.DataFrame:
    """Held-to-expiry opening fills: still open at settlement."""
    is_entry = df["entry_or_exit"].fillna("").str.lower() == "entry"
    is_held = (df["is_fully_closed"] != True) & (df["remaining_open_cc"] > 0)
    cols = [
        "fill_id", "market_ticker", "asset", "created_time", "canonical_position_side",
        "canonical_position_action", "economic_side", "canonical_leg_price_cents",
        "quantity_cc", "signed_yes_delta_cc", "remaining_open_cc", "market_result",
        "settlement_value_cents", "unrealized_gross_pnl_cents", "unrealized_fee_cents",
        "unrealized_net_pnl_cents", "total_settled_pnl_cents", "hold_time_seconds",
    ]
    return df.loc[is_entry & is_held, [c for c in cols if c in df.columns]].copy()


def generate_intracontract_exit_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Round-trip trades: an entry paired with one or more exits before expiry."""
    rows: List[Dict[str, Any]] = []
    for rt_id, group in df.groupby("round_trip_ids"):
        if not isinstance(rt_id, str) or not rt_id.startswith("rt_"):
            continue
        entry = group[group["entry_or_exit"].fillna("").str.lower() == "entry"]
        exits = group[group["entry_or_exit"].fillna("").str.lower() == "exit"]
        if entry.empty or exits.empty:
            continue
        entry_row = entry.iloc[0]
        # Sum the whole round-trip so we do not double-count by restricting to
        # exit rows (some fills carry a split of the gross/net PnL).
        pnl_net = float(group["total_settled_pnl_cents"].sum()) if "total_settled_pnl_cents" in group.columns else None
        pnl_gross = float(group["realized_gross_pnl_cents"].sum()) if "realized_gross_pnl_cents" in group.columns else None
        rows.append({
            "round_trip_id": rt_id,
            "market_ticker": entry_row.get("market_ticker"),
            "asset": entry_row.get("asset"),
            "entry_fill_id": entry_row.get("fill_id"),
            "entry_created_time": entry_row.get("created_time"),
            "exit_fill_ids": ";".join(exits["fill_id"].astype(str).tolist()),
            "entry_economic_side": entry_row.get("economic_side"),
            "entry_price_cents": entry_row.get("canonical_leg_price_cents"),
            "exit_quantity_cc": int(exits["quantity_cc"].sum()) if "quantity_cc" in exits.columns else None,
            "entry_quantity_cc": int(entry_row.get("quantity_cc")) if pd.notna(entry_row.get("quantity_cc")) else None,
            "realized_net_pnl_cents": pnl_net,
            "realized_gross_pnl_cents": pnl_gross,
            "market_result": entry_row.get("market_result"),
        })
    return pd.DataFrame(rows)


def generate_decision_to_settlement_audit(df: pd.DataFrame) -> pd.DataFrame:
    """Join every opening decision to its settlement result.

    When `decision_trace_id` is missing the join key falls back to `fill_id`
    so the ledger is still useful for historical reports.
    """
    is_entry = df["entry_or_exit"].fillna("").str.lower() == "entry"
    df = df.loc[is_entry].copy()
    if "decision_trace_id" in df.columns and df["decision_trace_id"].notna().any():
        df["decision_id"] = df["decision_trace_id"].fillna(df["fill_id"])
    else:
        df["decision_id"] = df["fill_id"]
    cols = [
        "decision_id", "fill_id", "market_ticker", "asset", "created_time",
        "canonical_position_side", "canonical_position_action", "economic_side",
        "canonical_leg_price_cents", "quantity_cc", "signed_yes_delta_cc",
        "remaining_open_cc", "is_fully_closed", "market_result", "settlement_value_cents",
        "total_settled_pnl_cents", "hold_time_seconds",
    ]
    return df[[c for c in cols if c in df.columns]].copy()


def _component_contributions(row: Dict[str, Any], settlement_sign: float) -> Dict[str, float]:
    """Return signed delta * settlement sign for each named component."""
    components = {
        "velocity": row.get("delta_velocity"),
        "macd": row.get("delta_macd"),
        "rsi": row.get("delta_rsi"),
        "obi": row.get("delta_obi"),
        "regime": row.get("delta_regime"),
        "fvg": row.get("delta_fvg"),
        "total": row.get("raw_delta_total"),
    }
    return {name: _safe_float(value, 0.0) * settlement_sign for name, value in components.items()}


def _settlement_sign(row: pd.Series) -> float:
    """+1 if the economic side was the winning side, -1 if not."""
    market_result = str(row.get("market_result", "")).upper()
    economic_side = str(row.get("economic_side", "")).upper()
    if not market_result or not economic_side:
        return 0.0
    return 1.0 if market_result == economic_side else -1.0


def compute_component_sign_correlation(
    decomposition_path: str | Path,
    settlement_df: pd.DataFrame,
    min_samples: int = 10,
) -> Dict[str, Dict[str, Any]]:
    """Join model-decomposition records to held-to-expiry settlements and compute
    each component's mean signed contribution.

    A positive mean contribution means the component was pushing the model in the
    direction that actually settled.  A negative mean means the component is
    systematically mis-signed (mean-reverting in a momentum market).
    """
    records: List[Dict[str, Any]] = []
    path = Path(decomposition_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not records:
        return {}

    decomp = pd.json_normalize(records)
    if "decision_id" not in decomp.columns and "live.decision_id" in decomp.columns:
        decomp["decision_id"] = decomp["live.decision_id"]
    if "decision_id" not in decomp.columns:
        return {}

    merged = pd.merge(
        decomp,
        settlement_df,
        on="decision_id",
        how="inner",
    )
    if merged.empty:
        return {}

    merged["settlement_sign"] = merged.apply(_settlement_sign, axis=1)
    merged = merged[merged["settlement_sign"] != 0.0]

    component_names = ["delta_velocity", "delta_macd", "delta_rsi", "delta_obi", "delta_regime", "delta_fvg", "raw_delta_total"]
    out: Dict[str, Dict[str, Any]] = {}
    for col in component_names:
        if col not in merged.columns:
            continue
        values = merged[col].astype(float) * merged["settlement_sign"]
        n = len(values.dropna())
        if n < min_samples:
            continue
        mean = float(values.mean())
        stderr = float(values.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0
        out[col] = {
            "n": n,
            "mean_signed_contribution": mean,
            "stderr": stderr,
            "t_statistic": mean / stderr if stderr > 0.0 else 0.0,
        }
    return out


def run_audit(
    fills_csv: str | Path,
    output_dir: str | Path,
    decomposition_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Generate the three audit ledgers and optionally compute sign correlation."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_fills_csv(fills_csv)

    expiry_alpha = generate_expiry_alpha_entries(df)
    expiry_alpha.to_csv(output_dir / "expiry_alpha_entries.csv", index=False)

    intracontract = generate_intracontract_exit_trades(df)
    intracontract.to_csv(output_dir / "intracontract_exit_trades.csv", index=False)

    decision_audit = generate_decision_to_settlement_audit(df)
    decision_audit.to_csv(output_dir / "decision_to_settlement_audit.csv", index=False)

    correlation: Dict[str, Any] = {}
    if decomposition_path:
        correlation = compute_component_sign_correlation(decomposition_path, decision_audit)

    return {
        "expiry_alpha_rows": len(expiry_alpha),
        "intracontract_rows": len(intracontract),
        "decision_audit_rows": len(decision_audit),
        "correlation": correlation,
    }


if __name__ == "__main__":
    fills_csv = os.environ.get("MERID_AUDIT_FILLS_CSV", "reports/last_24h_fills_with_pairing_and_settlement_20260826_141146.csv")
    output_dir = os.environ.get("MERID_AUDIT_OUTPUT_DIR", "reports")
    decomp_path = os.environ.get("MERID_AUDIT_DECOMPOSITION_PATH")
    result = run_audit(fills_csv, output_dir, decomp_path)
    print(json.dumps(result, indent=2, default=str))

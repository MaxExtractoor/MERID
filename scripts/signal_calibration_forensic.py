#!/usr/bin/env python3
"""Signal-vs-settlement calibration forensic.

Joins durable round-trip/settlement records with decision telemetry to compare
model-predicted probabilities at entry to actual settlement outcomes.

Inputs:
- reports/decision_to_settlement_audit.csv
- reports/last_24h_fills_with_pairing_and_settlement_*.csv
- logs/decision_telemetry.jsonl*

Output:
- reports/signal_calibration_forensic_YYYYmmdd_HHMMSS.json

This is read-only and does not touch the exchange, order router, or ledger.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _load_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _find_latest(root: Path, pattern: str) -> Optional[Path]:
    matches = sorted(root.glob(pattern), key=lambda p: p.name, reverse=True)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Telemetry ingestion
# ---------------------------------------------------------------------------

def _derive_economic_side(side: str, action: str) -> str:
    """YES = long YES, NO = long NO."""
    side = (side or "").lower()
    action = (action or "").lower()
    if (side == "yes" and action == "buy") or (side == "no" and action == "sell"):
        return "YES"
    if (side == "yes" and action == "sell") or (side == "no" and action == "buy"):
        return "NO"
    return "UNKNOWN"


def _is_settled_open(row: Dict[str, Any]) -> bool:
    """True for held-to-settlement positions."""
    closed = str(row.get("is_fully_closed", "")).lower() in ("true", "1")
    remaining = _safe_int(row.get("remaining_open_cc"), 0)
    return not closed and remaining > 0


def _is_closed(row: Dict[str, Any]) -> bool:
    return str(row.get("is_fully_closed", "")).lower() in ("true", "1")


class TelemetryIndex:
    def __init__(self, log_paths: Iterable[Path]):
        self.by_decision_id: Dict[str, Dict[str, Any]] = {}
        self.by_ticker: Dict[str, List[Tuple[datetime, Dict[str, Any]]]] = defaultdict(list)
        self.selected_count = 0
        self.rejected_count = 0
        for path in log_paths:
            self._ingest(path)
        for records in self.by_ticker.values():
            records.sort(key=lambda x: x[0])

    def _ingest(self, path: Path) -> None:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") != "decision_record":
                    continue
                if not rec.get("allocator_selected"):
                    self.rejected_count += 1
                    continue
                self.selected_count += 1

                decision_id = rec.get("decision_id")
                if decision_id:
                    self.by_decision_id[decision_id] = rec

                ticker = rec.get("ticker")
                ts = _parse_iso(rec.get("event_ts_utc"))
                if ticker and ts:
                    self.by_ticker[ticker].append((ts, rec))

    def lookup(self, ticker: str, decision_id: Optional[str], window_center: Optional[datetime], window_seconds: float = 60.0) -> Optional[Dict[str, Any]]:
        """Best-effort match by decision_id, then by ticker + nearest time."""
        if decision_id and decision_id in self.by_decision_id:
            return self.by_decision_id[decision_id]

        if not ticker or not window_center:
            return None

        records = self.by_ticker.get(ticker, [])
        if not records:
            return None

        best: Optional[Dict[str, Any]] = None
        best_dt: Optional[timedelta] = None
        for ts, rec in records:
            dt = abs((ts - window_center).total_seconds())
            if dt <= window_seconds:
                if best_dt is None or dt < best_dt:
                    best = rec
                    best_dt = dt
        return best


class DecisionSidecar:
    """Cross-link fills to telemetry using durable intent index and order-decision log.

    The primary join key is ``decision_id`` / ``decision_trace_id`` carried on the
    fill.  When that is absent (older fills, intent-resolution races, or HTTP-poller
    records without provenance), we fall back to the durable intent index and the
    order-decisions log, both of which map ``client_order_id`` / ``order_id`` /
    ``intent_id`` back to the original ``decision_id``.
    """

    def __init__(self, project_root: Path):
        self.by_client_order_id: Dict[str, str] = {}
        self.by_order_id: Dict[str, str] = {}
        self.by_intent_id: Dict[str, str] = {}
        self.durable_records = 0
        self.order_decision_records = 0
        self._load_durable_intent_index(project_root)
        self._load_order_decisions(project_root)

    def _load_durable_intent_index(self, project_root: Path) -> None:
        """Load ``data/kalshi_fills_intent_index.json`` written by fills_ledger."""
        path = project_root / "data" / "kalshi_fills_intent_index.json"
        if not path.exists():
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        for rec in data.values():
            if not isinstance(rec, dict):
                continue
            did = rec.get("decision_id") or rec.get("decision_trace_id")
            if not did:
                continue
            # Only entry intents are relevant for signal calibration.
            if (rec.get("entry_or_exit") or "").lower() != "entry":
                continue
            self.durable_records += 1
            for key in ("client_order_id", "client_tag"):
                val = rec.get(key)
                if val:
                    self.by_client_order_id[str(val)] = did
            order_id = rec.get("order_id")
            if order_id:
                self.by_order_id[str(order_id)] = did
            intent_id = rec.get("intent_id")
            if intent_id:
                self.by_intent_id[str(intent_id)] = did

    def _load_order_decisions(self, project_root: Path) -> None:
        """Load ``logs/order_decisions.jsonl`` written by order_intent_contract."""
        log_dir = project_root / "logs"
        for path in sorted(log_dir.glob("order_decisions*.jsonl*"), key=lambda p: p.name):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(rec, dict):
                            continue
                        purpose = (rec.get("purpose") or rec.get("position_effect") or "").lower()
                        if purpose != "open":
                            continue
                        if rec.get("allowed") is False:
                            continue
                        did = rec.get("decision_id") or rec.get("decision_trace_id")
                        if not did:
                            continue
                        self.order_decision_records += 1
                        coid = rec.get("client_order_id")
                        if coid:
                            self.by_client_order_id[str(coid)] = did
                        order_id = rec.get("order_id")
                        if order_id:
                            self.by_order_id[str(order_id)] = did
                        intent_id = rec.get("intent_id")
                        if intent_id:
                            self.by_intent_id[str(intent_id)] = did
            except Exception:
                continue

    def resolve(self, client_order_id: Optional[str], order_id: Optional[str], intent_id: Optional[str]) -> Optional[str]:
        """Return ``decision_id`` if we can resolve any of the order identifiers."""
        for key in (client_order_id, order_id, intent_id):
            if not key:
                continue
            s = str(key)
            if s in self.by_client_order_id:
                return self.by_client_order_id[s]
            if s in self.by_order_id:
                return self.by_order_id[s]
            if s in self.by_intent_id:
                return self.by_intent_id[s]
        return None


# ---------------------------------------------------------------------------
# Calibration computation
# ---------------------------------------------------------------------------

def _bucket(prob: float, width: float = 0.05) -> str:
    """Probability bucket string, e.g. 0.50-0.55."""
    lower = int(prob / width) * width
    upper = lower + width
    return f"{lower:.2f}-{upper:.2f}"


def _compute_calibration(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {}

    actuals = [1.0 if r["actual_win"] else 0.0 for r in rows]
    probs = [r["model_prob_selected"] for r in rows if r["model_prob_selected"] is not None]
    market_probs = [r["market_p_selected"] for r in rows if r["market_p_selected"] is not None]

    by_bucket: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["model_prob_selected"] is not None:
            by_bucket[_bucket(r["model_prob_selected"])].append(r)

    bucket_table: Dict[str, Any] = {}
    for b, items in sorted(by_bucket.items()):
        wins = sum(1 for r in items if r["actual_win"])
        n = len(items)
        mean_prob = mean([r["model_prob_selected"] for r in items])
        mean_market = mean([r["market_p_selected"] for r in items if r["market_p_selected"] is not None]) if any(r["market_p_selected"] is not None for r in items) else None
        bucket_table[b] = {
            "n": n,
            "wins": wins,
            "actual_win_rate": round(wins / n, 4) if n else 0.0,
            "mean_model_prob": round(mean_prob, 4),
            "mean_market_prob": round(mean_market, 4) if mean_market is not None else None,
            "mean_net_pnl_cents": round(mean([r["net_pnl_cents"] for r in items]), 4),
        }

    def _mean(values: List[float]) -> float:
        return round(mean(values), 4) if values else 0.0

    # Brier score: mean squared error of probability forecasts
    brier = mean([(p - a) ** 2 for p, a in zip(probs, actuals)]) if probs and actuals else 0.0
    mae = mean([abs(p - a) for p, a in zip(probs, actuals)]) if probs and actuals else 0.0

    by_side: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_side[r["selected_side"]].append(r)

    by_side_summary: Dict[str, Any] = {}
    for side, items in sorted(by_side.items()):
        wins = sum(1 for r in items if r["actual_win"])
        n = len(items)
        mean_model = _mean([r["model_prob_selected"] for r in items if r["model_prob_selected"] is not None])
        mean_market = _mean([r["market_p_selected"] for r in items if r["market_p_selected"] is not None])
        mean_pnl = _mean([r["net_pnl_cents"] for r in items])
        by_side_summary[side] = {
            "n": n,
            "wins": wins,
            "actual_win_rate": round(wins / n, 4) if n else 0.0,
            "mean_model_prob": mean_model,
            "mean_market_prob": mean_market,
            "mean_net_pnl_cents": mean_pnl,
        }

    return {
        "n": len(rows),
        "wins": sum(1 for r in rows if r["actual_win"]),
        "actual_win_rate": round(sum(actuals) / len(actuals), 4) if actuals else 0.0,
        "mean_model_prob": _mean(probs),
        "mean_market_prob": _mean(market_probs),
        "mean_net_pnl_cents": _mean([r["net_pnl_cents"] for r in rows]),
        "brier_score": round(brier, 6),
        "mean_absolute_error": round(mae, 4),
        "by_model_prob_bucket": bucket_table,
        "by_selected_side": by_side_summary,
    }


def build_calibration(
    audit_path: Path,
    fills_path: Path,
    telemetry_log_paths: List[Path],
) -> Dict[str, Any]:
    """Join settlement records with telemetry and produce calibration tables."""
    audit_rows = _load_csv(audit_path)

    # Load fills for decision_trace_id and time if needed
    fills_by_id: Dict[str, Dict[str, Any]] = {}
    if fills_path and fills_path.exists():
        for row in _load_csv(fills_path):
            fill_id = row.get("fill_id")
            if fill_id:
                fills_by_id[fill_id] = row

    telemetry = TelemetryIndex(telemetry_log_paths)
    sidecar = DecisionSidecar(PROJECT_ROOT)

    all_matched: List[Dict[str, Any]] = []
    settled_matched: List[Dict[str, Any]] = []
    closed_matched: List[Dict[str, Any]] = []
    unmatched: List[Dict[str, Any]] = []

    sidecar_hits = 0

    for row in audit_rows:
        fill_id = row.get("fill_id") or row.get("decision_id")  # audit uses decision_id as fill_id fallback
        decision_id = row.get("decision_id")  # may be decision_... or fill_id
        ticker = row.get("market_ticker", "")
        created_time = _parse_iso(row.get("created_time"))

        # Try to get decision_trace_id from fills CSV if audit decision_id is just fill_id
        fill = fills_by_id.get(fill_id, {})
        trace_id = fill.get("decision_trace_id")
        if not trace_id:
            trace_id = sidecar.resolve(
                fill.get("client_order_id"),
                fill.get("order_id"),
                fill.get("intent_id"),
            )
            if trace_id:
                sidecar_hits += 1
        if not trace_id:
            trace_id = decision_id

        rec = telemetry.lookup(ticker, trace_id, created_time, window_seconds=90.0)

        if not rec:
            unmatched.append({
                "fill_id": fill_id,
                "ticker": ticker,
                "created_time": str(row.get("created_time")),
                "economic_side": _derive_economic_side(row.get("canonical_position_side"), row.get("canonical_position_action")),
            })
            continue

        selected_side = (rec.get("selected_side") or "").upper()
        model_prob = _safe_float(rec.get("model_prob_selected"))
        market_prob = _safe_float(rec.get("market_p_selected"))
        market_result = (row.get("market_result") or "").upper()

        actual_win = selected_side and market_result and selected_side == market_result
        economic_side = _derive_economic_side(row.get("canonical_position_side"), row.get("canonical_position_action"))

        net_pnl = _safe_float(row.get("total_settled_pnl_cents"), 0.0)

        out = {
            "fill_id": fill_id,
            "ticker": ticker,
            "asset": row.get("asset", "UNKNOWN"),
            "selected_side": selected_side,
            "economic_side": economic_side,
            "model_prob_selected": model_prob,
            "market_p_selected": market_prob,
            "model_edge": round((model_prob or 0.0) - (market_prob or 0.0), 6) if model_prob is not None and market_prob is not None else None,
            "market_result": market_result,
            "actual_win": actual_win,
            "net_pnl_cents": net_pnl,
            "created_time": str(row.get("created_time")),
            "decision_ts": str(rec.get("event_ts_utc")),
            "strategy_intent": rec.get("strategy_intent"),
            "thesis_side": rec.get("thesis_side"),
            "selected_outcome_price_cents": _safe_float(rec.get("selected_outcome_price_cents")),
            "edge_pct": _safe_float(rec.get("edge_pct")),
        }

        all_matched.append(out)
        if _is_settled_open(row):
            settled_matched.append(out)
        elif _is_closed(row):
            closed_matched.append(out)

    # Aggregate
    report = {
        "_meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "telemetry_files": [str(p) for p in telemetry_log_paths],
            "audit_file": str(audit_path),
            "fills_file": str(fills_path) if fills_path else None,
            "telemetry_selected_records": telemetry.selected_count,
            "telemetry_rejected_records": telemetry.rejected_count,
            "audit_rows": len(audit_rows),
            "matched_total": len(all_matched),
            "matched_settled_open": len(settled_matched),
            "matched_closed": len(closed_matched),
            "unmatched": len(unmatched),
            "sidecar_hits": sidecar_hits,
            "durable_intent_index_records": sidecar.durable_records,
            "order_decision_log_records": sidecar.order_decision_records,
        },
        "all_matched": _compute_calibration(all_matched),
        "settled_open_matched": _compute_calibration(settled_matched),
        "closed_matched": _compute_calibration(closed_matched),
        "unmatched_samples": unmatched[:20],
    }

    # By asset × side for the settled-open subset
    by_asset_side: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in settled_matched:
        by_asset_side[(r["asset"], r["selected_side"])].append(r)

    asset_side_summary: Dict[str, Any] = {}
    for (asset, side), items in sorted(by_asset_side.items()):
        wins = sum(1 for r in items if r["actual_win"])
        n = len(items)
        mean_model = round(mean([r["model_prob_selected"] for r in items if r["model_prob_selected"] is not None]), 4) if any(r["model_prob_selected"] is not None for r in items) else 0.0
        mean_market = round(mean([r["market_p_selected"] for r in items if r["market_p_selected"] is not None]), 4) if any(r["market_p_selected"] is not None for r in items) else 0.0
        mean_pnl = round(mean([r["net_pnl_cents"] for r in items]), 4)
        asset_side_summary[f"{asset}__{side}"] = {
            "n": n,
            "wins": wins,
            "actual_win_rate": round(wins / n, 4) if n else 0.0,
            "mean_model_prob": mean_model,
            "mean_market_prob": mean_market,
            "mean_net_pnl_cents": mean_pnl,
        }
    report["settled_open_by_asset_and_selected_side"] = asset_side_summary

    # Telemetry-only summary (independent of audit match)
    all_selected: List[Dict[str, Any]] = []
    for records in telemetry.by_ticker.values():
        for _, rec in records:
            all_selected.append(rec)
    for rec in telemetry.by_decision_id.values():
        if rec not in all_selected:
            all_selected.append(rec)

    def _summarize_telemetry(records: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_asset_side: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for r in records:
            by_asset_side[(r.get("asset", "UNKNOWN"), (r.get("selected_side") or "").upper())].append(r)

        rows: List[Dict[str, Any]] = []
        total_model: List[float] = []
        total_market: List[float] = []
        for (asset, side), items in sorted(by_asset_side.items()):
            model = [r.get("model_prob_selected") for r in items if r.get("model_prob_selected") is not None]
            market = [r.get("market_p_selected") for r in items if r.get("market_p_selected") is not None]
            edge = [(m - mk) for m, mk in zip(model, market)] if model and market else []
            row = {
                "asset": asset,
                "selected_side": side,
                "n": len(items),
                "mean_model_prob": round(mean(model), 4) if model else None,
                "mean_market_prob": round(mean(market), 4) if market else None,
                "mean_edge_pct": round(mean(edge) * 100, 4) if edge else None,
            }
            rows.append(row)
            total_model.extend(model)
            total_market.extend(market)

        total_edge = [(m - mk) for m, mk in zip(total_model, total_market)] if total_model and total_market else []
        return {
            "total_selected_records": len(records),
            "overall_mean_model_prob": round(mean(total_model), 4) if total_model else None,
            "overall_mean_market_prob": round(mean(total_market), 4) if total_market else None,
            "overall_mean_edge_pct": round(mean(total_edge) * 100, 4) if total_edge else None,
            "by_asset_and_side": rows,
        }

    report["telemetry_summary"] = _summarize_telemetry(all_selected)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal-vs-settlement calibration forensic")
    parser.add_argument("--audit", type=Path, default=None, help="decision_to_settlement_audit.csv")
    parser.add_argument("--fills", type=Path, default=None, help="last_24h_fills_with_pairing_and_settlement_*.csv")
    parser.add_argument("--telemetry", type=Path, nargs="+", default=None, help="decision_telemetry.jsonl files")
    parser.add_argument("--out", type=Path, default=None, help="output JSON path")
    args = parser.parse_args()

    reports_dir = PROJECT_ROOT / "reports"
    logs_dir = PROJECT_ROOT / "logs"

    audit_path = args.audit or (reports_dir / "decision_to_settlement_audit.csv")
    fills_path = args.fills or _find_latest(reports_dir, "last_24h_fills_with_pairing_and_settlement_*.csv")

    if args.telemetry:
        telemetry_paths = args.telemetry
    else:
        telemetry_paths = sorted(logs_dir.glob("decision_telemetry.jsonl*"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not audit_path.exists():
        print(f"Audit CSV not found: {audit_path}")
        sys.exit(1)
    if fills_path and not fills_path.exists():
        print(f"Fills CSV not found: {fills_path}")
        sys.exit(1)

    report = build_calibration(audit_path, fills_path, telemetry_paths)

    out_path = args.out or reports_dir / f"signal_calibration_forensic_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()

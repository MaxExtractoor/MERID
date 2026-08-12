#!/usr/bin/env python3
"""Bucketed EV and fee telemetry analyzer for MERID 15m signals and fills.

Reads server logs containing [SIGNAL-EV-GATE] and [FILL-FEE-AUDIT] lines,
produces bucketed summaries, and runs what-if cost-model forecasts.

Examples:
    python scripts/analyze_ev_fee_telemetry.py --log server_output.log
    python scripts/analyze_ev_fee_telemetry.py --log logs/*.log --output ev_report.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SignalEvRecord:
    """Parsed [SIGNAL-EV-GATE] record."""
    asset: str
    side: str
    action: str
    quote_price_cents: int
    quote_source: str
    displayed_depth: Optional[int]
    requested_contracts: int
    market_probability: float
    model_probability: float
    raw_model_edge_cents: float
    exchange_fee_cents: float
    expected_entry_impact_cents: float
    expected_exit_fee_reserve_cents: float
    expected_exit_impact_reserve_cents: float
    uncertainty_buffer_cents: float
    max_slippage_guard_cents: int
    all_in_expected_cost_cents: float
    robust_cost_cents: float
    ev_expected_cents: float
    ev_robust_cents: float
    decision: str


@dataclass
class FillFeeRecord:
    """Parsed [FILL-FEE-AUDIT] record."""
    fill_id: str
    ticker: str
    order_id: Optional[str]
    side: str
    action: str
    contracts: float
    limit_price_cents: Optional[int]
    fill_price_cents: int
    modeled_fee_cents: Optional[float]
    reported_exchange_fee_cents: int
    fee_delta_cents: Optional[float]
    series_fee_multiplier: float
    liquidity_role: Optional[str]


@dataclass
class WhatIfMetrics:
    """Per-record what-if EV metrics."""
    ev_without_slippage_guard: float
    ev_with_parabolic_fee: float
    ev_parabolic_no_slippage_guard: float
    parabolic_fee_cents: float
    fee_overstatement_cents: float


@dataclass
class BucketSummary:
    """Summary of signals within one bucket."""
    bucket_key: str
    count: int = 0
    avg_ev_expected: float = 0.0
    avg_ev_robust: float = 0.0
    avg_all_in_expected: float = 0.0
    avg_robust_cost: float = 0.0
    avg_raw_edge_cents: float = 0.0
    avg_displayed_depth: float = 0.0
    pass_count: int = 0
    no_trade_count: int = 0
    would_pass_without_slippage: int = 0
    would_pass_with_parabolic: int = 0
    would_pass_parabolic_no_guard: int = 0
    avg_fee_overstatement_cents: float = 0.0


@dataclass
class FillBucketSummary:
    """Summary of fills within one bucket."""
    bucket_key: str
    count: int = 0
    modeled_count: int = 0
    has_modeled: bool = False
    modeled_sum: float = 0.0
    reported_sum: float = 0.0
    canonical_sum: float = 0.0
    fee_delta_sum: float = 0.0
    modeled_vs_canonical_delta_sum: float = 0.0
    avg_modeled_fee_cents: float = -1.0
    avg_reported_fee_per_contract_cents: float = 0.0
    avg_canonical_fee_cents: float = 0.0
    avg_fee_delta_cents: float = 0.0
    avg_modeled_vs_canonical_delta: float = 0.0
    report_higher_than_model_count: int = 0
    report_lower_than_model_count: int = 0


class EvFeeTelemetryAnalyzer:
    """Parse and bucket EV-gate and fill-fee-audit telemetry."""

    SIGNAL_PATTERN = re.compile(r"\[SIGNAL-EV-GATE\]\s+(.*)")
    FILL_PATTERN = re.compile(r"\[FILL-FEE-AUDIT\]\s+(.*)")

    def __init__(self, signals: Optional[List[SignalEvRecord]] = None,
                 fills: Optional[List[FillFeeRecord]] = None):
        self.signals: List[SignalEvRecord] = signals or []
        self.fills: List[FillFeeRecord] = fills or []
        self.what_if: List[WhatIfMetrics] = []

    @staticmethod
    def _parse_key_value_pairs(text: str) -> Dict[str, str]:
        """Parse 'key=value key2=value2' pairs that contain no spaces."""
        pairs = {}
        for token in text.split():
            if "=" in token:
                key, value = token.split("=", 1)
                pairs[key] = value
        return pairs

    @classmethod
    def parse_signal_line(cls, line: str) -> Optional[SignalEvRecord]:
        match = cls.SIGNAL_PATTERN.search(line)
        if not match:
            return None
        p = cls._parse_key_value_pairs(match.group(1))

        def _float(key: str, default: float = 0.0) -> float:
            try:
                return float(p.get(key, default))
            except ValueError:
                return default

        def _int(key: str, default: int = 0) -> int:
            try:
                return int(p.get(key, default))
            except ValueError:
                return default

        displayed_depth_str = p.get("displayed_depth", "unknown")
        displayed_depth = None if displayed_depth_str == "unknown" else _int("displayed_depth")

        return SignalEvRecord(
            asset=p.get("asset", ""),
            side=p.get("side", ""),
            action=p.get("action", ""),
            quote_price_cents=_int("quote_price_cents"),
            quote_source=p.get("quote_source", ""),
            displayed_depth=displayed_depth,
            requested_contracts=_int("requested_contracts", 1),
            market_probability=_float("market_probability"),
            model_probability=_float("model_probability"),
            raw_model_edge_cents=_float("raw_model_edge_cents"),
            exchange_fee_cents=_float("exchange_fee_cents"),
            expected_entry_impact_cents=_float("expected_entry_impact_cents"),
            expected_exit_fee_reserve_cents=_float("expected_exit_fee_reserve_cents"),
            expected_exit_impact_reserve_cents=_float("expected_exit_impact_reserve_cents"),
            uncertainty_buffer_cents=_float("uncertainty_buffer_cents"),
            max_slippage_guard_cents=_int("max_slippage_guard_cents"),
            all_in_expected_cost_cents=_float("all_in_expected_cost_cents"),
            robust_cost_cents=_float("robust_cost_cents"),
            ev_expected_cents=_float("ev_expected_cents"),
            ev_robust_cents=_float("ev_robust_cents"),
            decision=p.get("decision", ""),
        )

    @classmethod
    def parse_fill_line(cls, line: str) -> Optional[FillFeeRecord]:
        match = cls.FILL_PATTERN.search(line)
        if not match:
            return None
        p = cls._parse_key_value_pairs(match.group(1))

        def _float(key: str, default: float = 0.0) -> float:
            try:
                return float(p.get(key, default))
            except ValueError:
                return default

        def _int(key: str, default: Optional[int] = None) -> Optional[int]:
            try:
                val = p.get(key)
                if val is None or val == "unknown":
                    return default
                return int(val)
            except ValueError:
                return default

        modeled = p.get("modeled_fee_cents", "unknown")
        modeled_fee = None if modeled == "unknown" else _float("modeled_fee_cents")

        fee_delta = p.get("fee_delta_cents", "unknown")
        fee_delta_cents = None if fee_delta == "unknown" else _float("fee_delta_cents")

        return FillFeeRecord(
            fill_id=p.get("fill_id", ""),
            ticker=p.get("ticker", ""),
            order_id=p.get("order_id") or None,
            side=p.get("side", ""),
            action=p.get("action", ""),
            contracts=_float("contracts", 1.0),
            limit_price_cents=_int("limit_price_cents"),
            fill_price_cents=_int("fill_price_cents") or 0,
            modeled_fee_cents=modeled_fee,
            reported_exchange_fee_cents=_int("reported_exchange_fee_cents") or 0,
            fee_delta_cents=fee_delta_cents,
            series_fee_multiplier=_float("series_fee_multiplier"),
            liquidity_role=p.get("liquidity_role") or None,
        )

    def load_logs(self, log_paths: List[Path]) -> None:
        """Load and parse one or more log files."""
        seen: set = set()
        for path in log_paths:
            if not path.exists():
                print(f"[WARN] Log not found: {path}", file=sys.stderr)
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    if "[SIGNAL-EV-GATE]" in line:
                        record = self.parse_signal_line(line)
                        if record:
                            key = (
                                record.asset, record.side, record.quote_price_cents,
                                record.model_probability, record.decision,
                                record.ev_robust_cents
                            )
                            if key not in seen:
                                seen.add(key)
                                self.signals.append(record)
                    elif "[FILL-FEE-AUDIT]" in line:
                        record = self.parse_fill_line(line)
                        if record:
                            key = (record.fill_id, record.reported_exchange_fee_cents)
                            if key not in seen:
                                seen.add(key)
                                self.fills.append(record)

    def compute_what_if(self) -> List[WhatIfMetrics]:
        """Compute alternative EVs for each signal under different fee/slippage assumptions."""
        from merid.event_venues.kalshi.parabolic_fees import kalshi_taker_fee_cents_parabolic

        results = []
        for s in self.signals:
            price_dollars = s.quote_price_cents / 100.0
            parabolic_fee = float(kalshi_taker_fee_cents_parabolic(price_dollars, s.requested_contracts))
            fee_overstatement = s.exchange_fee_cents - parabolic_fee

            # Lower fee increases EV by the fee delta (all_in_cost drops by same amount).
            ev_with_parabolic = s.ev_robust_cents + fee_overstatement
            # Removing the slippage guard increases EV by the guard amount.
            ev_without_slippage = s.ev_robust_cents + s.max_slippage_guard_cents
            # Combine both.
            ev_parabolic_no_slippage = s.ev_robust_cents + s.max_slippage_guard_cents + fee_overstatement

            results.append(WhatIfMetrics(
                ev_without_slippage_guard=ev_without_slippage,
                ev_with_parabolic_fee=ev_with_parabolic,
                ev_parabolic_no_slippage_guard=ev_parabolic_no_slippage,
                parabolic_fee_cents=parabolic_fee,
                fee_overstatement_cents=fee_overstatement,
            ))

        self.what_if = results
        return results

    @staticmethod
    def _mean(values: List[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _bucket_key(asset: str, side: str, price_cents: int) -> str:
        from merid.metrics.canonical_buckets import get_price_bucket
        return f"{asset}|{side}|{get_price_bucket(price_cents)}"

    def bucket_signals(self) -> Dict[str, BucketSummary]:
        """Bucket parsed signals by asset + side + canonical price bucket."""
        if not self.what_if:
            self.compute_what_if()

        buckets: Dict[str, BucketSummary] = {}
        for s, w in zip(self.signals, self.what_if):
            key = self._bucket_key(s.asset, s.side, s.quote_price_cents)
            b = buckets.setdefault(key, BucketSummary(bucket_key=key))
            b.count += 1
            if s.decision == "pass":
                b.pass_count += 1
            else:
                b.no_trade_count += 1
            if w.ev_without_slippage_guard > 0:
                b.would_pass_without_slippage += 1
            if w.ev_with_parabolic_fee > 0:
                b.would_pass_with_parabolic += 1
            if w.ev_parabolic_no_slippage_guard > 0:
                b.would_pass_parabolic_no_guard += 1

        # Second pass to compute averages.
        for key, b in buckets.items():
            records = [(s, w) for s, w in zip(self.signals, self.what_if)
                       if self._bucket_key(s.asset, s.side, s.quote_price_cents) == key]
            if not records:
                continue
            b.avg_ev_expected = self._mean([s.ev_expected_cents for s, _ in records])
            b.avg_ev_robust = self._mean([s.ev_robust_cents for s, _ in records])
            b.avg_all_in_expected = self._mean([s.all_in_expected_cost_cents for s, _ in records])
            b.avg_robust_cost = self._mean([s.robust_cost_cents for s, _ in records])
            b.avg_raw_edge_cents = self._mean([s.raw_model_edge_cents for s, _ in records])
            depths = [s.displayed_depth for s, _ in records if s.displayed_depth is not None]
            b.avg_displayed_depth = self._mean([float(d) for d in depths]) if depths else 0.0
            b.avg_fee_overstatement_cents = self._mean([w.fee_overstatement_cents for _, w in records])

        return buckets

    def bucket_fills(self) -> Dict[str, FillBucketSummary]:
        """Bucket parsed fills by ticker + side + canonical price bucket."""
        from merid.event_venues.kalshi.parabolic_fees import kalshi_taker_fee_cents_parabolic

        buckets: Dict[str, FillBucketSummary] = {}
        for f in self.fills:
            if f.contracts <= 0:
                continue
            reported_per_contract = f.reported_exchange_fee_cents / f.contracts
            canonical_fee = float(kalshi_taker_fee_cents_parabolic(f.fill_price_cents / 100.0, int(f.contracts)))

            modeled = f.modeled_fee_cents  # may be None if the originating intent was not resolvable
            modeled_for_delta = modeled if modeled is not None else canonical_fee
            delta = f.fee_delta_cents if f.fee_delta_cents is not None else (modeled_for_delta - reported_per_contract)

            key = self._bucket_key(f.ticker.split("-")[0] if "-" in f.ticker else f.ticker,
                                   f.side, f.fill_price_cents)
            b = buckets.setdefault(key, FillBucketSummary(bucket_key=key))
            b.count += 1
            if modeled is not None:
                b.modeled_sum += modeled
                b.modeled_count += 1
            b.reported_sum += reported_per_contract
            b.canonical_sum += canonical_fee
            b.fee_delta_sum += delta
            b.modeled_vs_canonical_delta_sum += modeled_for_delta - canonical_fee
            if reported_per_contract > modeled_for_delta + 1e-9:
                b.report_higher_than_model_count += 1
            elif reported_per_contract < modeled_for_delta - 1e-9:
                b.report_lower_than_model_count += 1

        for b in buckets.values():
            if b.count == 0:
                continue
            b.avg_reported_fee_per_contract_cents = b.reported_sum / b.count
            b.avg_canonical_fee_cents = b.canonical_sum / b.count
            b.avg_fee_delta_cents = b.fee_delta_sum / b.count
            b.avg_modeled_vs_canonical_delta = b.modeled_vs_canonical_delta_sum / b.count
            if b.modeled_count > 0:
                b.avg_modeled_fee_cents = b.modeled_sum / b.modeled_count
                b.has_modeled = True
            else:
                b.avg_modeled_fee_cents = -1.0
                b.has_modeled = False

        return buckets

    def full_report(self) -> Dict:
        """Return a complete report dict."""
        signal_buckets = self.bucket_signals()
        fill_buckets = self.bucket_fills()

        if not self.what_if:
            self.compute_what_if()

        total_signals = len(self.signals)
        pass_count = sum(1 for s in self.signals if s.decision == "pass")
        no_trade_count = total_signals - pass_count

        what_if_summary = {
            "would_pass_without_slippage_guard": sum(1 for w in self.what_if if w.ev_without_slippage_guard > 0),
            "would_pass_with_parabolic_fee": sum(1 for w in self.what_if if w.ev_with_parabolic_fee > 0),
            "would_pass_parabolic_no_slippage_guard": sum(1 for w in self.what_if if w.ev_parabolic_no_slippage_guard > 0),
            "avg_fee_overstatement_cents": self._mean([w.fee_overstatement_cents for w in self.what_if]),
        }

        return {
            "summary": {
                "total_signals": total_signals,
                "pass_count": pass_count,
                "no_trade_count": no_trade_count,
                "total_fills": len(self.fills),
                "what_if": what_if_summary,
            },
            "signal_buckets": {k: asdict(v) for k, v in sorted(signal_buckets.items())},
            "fill_buckets": {k: asdict(v) for k, v in sorted(fill_buckets.items())},
        }

    def print_summary(self, report: Dict) -> None:
        """Print a human-readable summary to stdout."""
        summary = report["summary"]
        print("=" * 80)
        print("MERID EV + Fee Telemetry Analysis")
        print("=" * 80)
        print(f"Total signals evaluated: {summary['total_signals']}")
        print(f"  Passed EV gate:        {summary['pass_count']}")
        print(f"  Rejected (no_trade):   {summary['no_trade_count']}")
        print(f"Total fills audited:     {summary['total_fills']}")
        print()

        what = summary["what_if"]
        print("What-if cost-model forecast (observed signals):")
        print(f"  Would pass without slippage guard:            {what['would_pass_without_slippage_guard']}")
        print(f"  Would pass with parabolic fee (no 2c floor):  {what['would_pass_with_parabolic_fee']}")
        print(f"  Would pass with parabolic fee AND no guard:   {what['would_pass_parabolic_no_slippage_guard']}")
        print(f"  Avg legacy fee overstatement vs parabolic:    {what['avg_fee_overstatement_cents']:.2f}c")
        print()

        if report["signal_buckets"]:
            print("Signal EV buckets:")
            print(f"{'Bucket':<30} {'Cnt':>5} {'Pass':>5} {'NoTrade':>7} {'+NoGuard':>8} {'+Parab':>7} {'+ParNoG':>8} {'AvgEvEx':>9} {'AvgEvRb':>9}")
            for key, b in report["signal_buckets"].items():
                print(f"{key:<30} {b['count']:>5} {b['pass_count']:>5} {b['no_trade_count']:>7} "
                      f"{b['would_pass_without_slippage']:>8} {b['would_pass_with_parabolic']:>7} "
                      f"{b['would_pass_parabolic_no_guard']:>8} {b['avg_ev_expected']:>9.2f} {b['avg_ev_robust']:>9.2f}")
            print()

        if report["fill_buckets"]:
            print("Fill fee buckets:")
            print(f"{'Bucket':<30} {'Cnt':>5} {'ModFee':>8} {'RptFee':>8} {'CanFee':>8} {'Delta':>8} {'Hi':>4} {'Lo':>4}")
            for key, b in report["fill_buckets"].items():
                mod_fee = f"{b['avg_modeled_fee_cents']:>8.2f}" if b.get('has_modeled') else "      --"
                print(f"{key:<30} {b['count']:>5} {mod_fee} "
                      f"{b['avg_reported_fee_per_contract_cents']:>8.2f} {b['avg_canonical_fee_cents']:>8.2f} "
                      f"{b['avg_fee_delta_cents']:>8.2f} {b['report_higher_than_model_count']:>4} "
                      f"{b['report_lower_than_model_count']:>4}")


def resolve_log_paths(patterns: List[str]) -> List[Path]:
    paths: List[Path] = []
    for p in patterns:
        if "*" in p or "?" in p:
            paths.extend(Path(g) for g in glob.glob(p))
        else:
            paths.append(Path(p))
    return paths


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", "-l", nargs="+", default=["server_output.log"],
                        help="Log file(s) or glob patterns to analyze.")
    parser.add_argument("--output", "-o", default=None,
                        help="Path to write JSON report (default: print to stdout).")
    parser.add_argument("--no-summary", action="store_true",
                        help="Skip printing human-readable summary.")
    args = parser.parse_args(argv)

    log_paths = resolve_log_paths(args.log)
    analyzer = EvFeeTelemetryAnalyzer()
    analyzer.load_logs(log_paths)
    analyzer.compute_what_if()
    report = analyzer.full_report()

    if not args.no_summary:
        analyzer.print_summary(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\n[REPORT] Wrote JSON to {args.output}")
    elif args.no_summary:
        print(json.dumps(report, indent=2, default=str))

    return 0


if __name__ == "__main__":
    sys.exit(main())

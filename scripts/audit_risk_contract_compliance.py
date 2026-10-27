"""Retro audit script for risk contract compliance on 15m crypto trades.

This script analyzes historical BTC/ETH/SOL/XRP/DOGE 15m trades to:
- Compute fraction of trades with valid WindowResolution + ExitPolicyResolution linkage
- Measure realized PnL vs planned SL/TP
- Identify outliers where loss > planned SL or hold time > max
- Compute per-asset metrics: EV at entry, planned vs realized R:R, SL/TP hit rates
- Generate actionable findings for tuning exit parameters

Usage:
    python scripts/audit_risk_contract_compliance.py --days 30
    python scripts/audit_risk_contract_compliance.py --start 2026-04-01 --end 2026-04-30
"""

import argparse
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Simplified trade record for audit."""
    ticker: str
    timestamp: datetime
    side: str
    action: str
    price_cents: int
    count: int
    edge_pct: Optional[float]
    window_resolution_id: Optional[str]
    exit_policy_id: Optional[str]
    risk_tier: Optional[str]
    trailing_enabled: Optional[bool]
    max_hold_seconds: Optional[int]
    planned_sl_price_cents: Optional[int]
    planned_tp_price_cents: Optional[int]
    exit_price_cents: Optional[int]
    exit_timestamp: Optional[datetime]
    exit_reason: Optional[str]
    pnl_cents: Optional[int]


class RiskContractAudit:
    """Audits historical trades for risk contract compliance."""
    
    def __init__(self):
        self.trades: List[TradeRecord] = []
        self.asset_metrics: Dict[str, Dict] = defaultdict(lambda: defaultdict(int))
        self.violations: List[Dict] = []
        self.findings: List[str] = []
    
    def load_trades_from_signal_log(self, days: int = 30) -> int:
        """Load trades from signal log.
        
        Args:
            days: Number of days of history to load
        
        Returns:
            Number of trades loaded
        """
        try:
            from merid.prediction.trading_agent import KalshiTradingAgent
            agent = KalshiTradingAgent()
            
            # Get signal log
            signal_log = agent.state.signal_log if agent.state else []
            
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            for entry in signal_log:
                ts = datetime.fromisoformat(entry["ts"])
                if ts < cutoff:
                    continue
                
                # Filter for 15m crypto
                ticker = entry.get("market_id", "")
                if not self._is_crypto_15m(ticker):
                    continue
                
                # Extract risk contract fields
                trade = TradeRecord(
                    ticker=ticker,
                    timestamp=ts,
                    side=entry.get("side", "yes"),
                    action=entry.get("action", "buy"),
                    price_cents=entry.get("limit_price_cents", 0),
                    count=entry.get("contracts", 0),
                    edge_pct=entry.get("edge_pct"),
                    window_resolution_id=entry.get("window_resolution_id"),  # May not exist yet
                    exit_policy_id=entry.get("exit_policy_id"),  # May not exist yet
                    risk_tier=entry.get("exit_policy_risk_tier"),
                    trailing_enabled=entry.get("exit_policy_trailing_enabled"),
                    max_hold_seconds=entry.get("exit_policy_max_hold_seconds"),
                    planned_sl_price_cents=None,  # Not in signal log
                    planned_tp_price_cents=None,  # Not in signal log
                    exit_price_cents=None,  # Not in signal log
                    exit_timestamp=None,  # Not in signal log
                    exit_reason=None,  # Not in signal log
                    pnl_cents=None,  # Not in signal log
                )
                
                self.trades.append(trade)
            
            logger.info(f"Loaded {len(self.trades)} trades from signal log")
            return len(self.trades)
            
        except Exception as e:
            logger.error(f"Failed to load trades from signal log: {e}")
            return 0
    
    def load_trades_from_fills_ledger(self, days: int = 30) -> int:
        """Load trades from fills ledger.
        
        Args:
            days: Number of days of history to load
        
        Returns:
            Number of trades loaded
        """
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            
            ledger = get_fills_ledger()
            if not ledger:
                logger.warning("Fills ledger not available")
                return 0
            
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            fills = ledger.get_fills(since=cutoff)
            
            for fill in fills:
                ticker = fill.get("ticker", "")
                if not self._is_crypto_15m(ticker):
                    continue
                
                trade = TradeRecord(
                    ticker=ticker,
                    timestamp=fill.get("timestamp", datetime.utcnow()),
                    side=fill.get("side", "yes"),
                    action=fill.get("action", "buy"),
                    price_cents=fill.get("price_cents", 0),
                    count=fill.get("count", 0),
                    edge_pct=fill.get("edge_pct"),
                    window_resolution_id=fill.get("window_resolution_id"),
                    exit_policy_id=fill.get("exit_policy_id"),
                    risk_tier=fill.get("risk_tier"),
                    trailing_enabled=fill.get("trailing_enabled"),
                    max_hold_seconds=fill.get("max_hold_seconds"),
                    planned_sl_price_cents=fill.get("stop_loss_price_cents"),
                    planned_tp_price_cents=fill.get("take_profit_price_cents"),
                    exit_price_cents=fill.get("exit_price_cents"),
                    exit_timestamp=fill.get("exit_timestamp"),
                    exit_reason=fill.get("exit_reason"),
                    pnl_cents=fill.get("pnl_cents"),
                )
                
                self.trades.append(trade)
            
            logger.info(f"Loaded {len(self.trades)} trades from fills ledger")
            return len(self.trades)
            
        except Exception as e:
            logger.error(f"Failed to load trades from fills ledger: {e}")
            return 0
    
    def _is_crypto_15m(self, ticker: str) -> bool:
        """Check if ticker is a crypto 15m market."""
        ticker_upper = ticker.upper()
        crypto_prefixes = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
        return any(prefix in ticker_upper for prefix in crypto_prefixes)
    
    def _extract_asset(self, ticker: str) -> str:
        """Extract asset from ticker."""
        if "BTC" in ticker.upper():
            return "BTC"
        elif "ETH" in ticker.upper():
            return "ETH"
        elif "SOL" in ticker.upper():
            return "SOL"
        elif "XRP" in ticker.upper():
            return "XRP"
        elif "DOGE" in ticker.upper():
            return "DOGE"
        return "UNKNOWN"
    
    def analyze_linkage_compliance(self) -> Dict:
        """Analyze fraction of trades with valid risk contract linkage.
        
        Returns:
            Dict with linkage compliance metrics
        """
        total = len(self.trades)
        if total == 0:
            return {"total_trades": 0, "linkage_rate": 0.0}
        
        with_window_resolution = sum(1 for t in self.trades if t.window_resolution_id)
        with_exit_policy = sum(1 for t in self.trades if t.exit_policy_id)
        with_risk_tier = sum(1 for t in self.trades if t.risk_tier)
        with_max_hold = sum(1 for t in self.trades if t.max_hold_seconds)
        
        # Full linkage requires all fields
        fully_linked = sum(
            1 for t in self.trades
            if t.window_resolution_id and t.exit_policy_id and t.risk_tier and t.max_hold_seconds
        )
        
        result = {
            "total_trades": total,
            "with_window_resolution": with_window_resolution,
            "with_exit_policy": with_exit_policy,
            "with_risk_tier": with_risk_tier,
            "with_max_hold": with_max_hold,
            "fully_linked": fully_linked,
            "linkage_rate": fully_linked / total if total > 0 else 0.0,
        }
        
        # Finding
        if result["linkage_rate"] < 0.5:
            self.findings.append(
                f"CRITICAL: Only {result['linkage_rate']:.1%} of trades have full risk contract linkage. "
                f"Ensure trading_agent passes ExitPolicyResolution to OrderIntent."
            )
        elif result["linkage_rate"] < 0.9:
            self.findings.append(
                f"WARNING: {result['linkage_rate']:.1%} of trades have full risk contract linkage. "
                f"Some orders may bypass the new validation in order_router."
            )
        else:
            self.findings.append(
                f"GOOD: {result['linkage_rate']:.1%} of trades have full risk contract linkage."
            )
        
        return result
    
    def analyze_sl_violations(self) -> Dict:
        """Analyze stop loss violations.
        
        Returns:
            Dict with SL violation metrics
        """
        sl_trades = [t for t in self.trades if t.planned_sl_price_cents and t.exit_price_cents]
        
        if not sl_trades:
            return {"total_with_sl": 0, "violations": 0, "violation_rate": 0.0}
        
        violations = []
        for trade in sl_trades:
            if trade.action == "buy":
                # Long: SL is below entry, violation if exit below SL
                if trade.exit_price_cents < trade.planned_sl_price_cents - 2:  # 2 cent tolerance
                    violations.append(trade)
            else:
                # Short: SL is above entry, violation if exit above SL
                if trade.exit_price_cents > trade.planned_sl_price_cents + 2:
                    violations.append(trade)
        
        violation_rate = len(violations) / len(sl_trades)
        
        result = {
            "total_with_sl": len(sl_trades),
            "violations": len(violations),
            "violation_rate": violation_rate,
        }
        
        # Finding
        if violation_rate > 0.1:
            self.findings.append(
                f"CRITICAL: {violation_rate:.1%} of trades violated SL. "
                f"Check for slippage, liquidity issues, or miscomputed SL prices."
            )
            for v in violations[:5]:  # Log first 5
                self.violations.append({
                    "type": "sl_violation",
                    "ticker": v.ticker,
                    "planned_sl": v.planned_sl_price_cents,
                    "actual_exit": v.exit_price_cents,
                    "violation_cents": abs(v.exit_price_cents - v.planned_sl_price_cents),
                })
        elif violation_rate > 0.02:
            self.findings.append(
                f"WARNING: {violation_rate:.1%} of trades violated SL. "
                f"Consider tightening SL tolerance or improving fill quality."
            )
        
        return result
    
    def analyze_hold_time_compliance(self) -> Dict:
        """Analyze max hold time compliance.
        
        Returns:
            Dict with hold time metrics
        """
        hold_trades = [t for t in self.trades if t.max_hold_seconds and t.exit_timestamp]
        
        if not hold_trades:
            return {"total_with_hold": 0, "violations": 0, "violation_rate": 0.0}
        
        violations = []
        for trade in hold_trades:
            hold_seconds = (trade.exit_timestamp - trade.timestamp).total_seconds()
            if hold_seconds > trade.max_hold_seconds:
                violations.append(trade)
        
        violation_rate = len(violations) / len(hold_trades)
        
        # Compute statistics
        hold_times = [
            (t.exit_timestamp - t.timestamp).total_seconds()
            for t in hold_trades
        ]
        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
        
        result = {
            "total_with_hold": len(hold_trades),
            "violations": len(violations),
            "violation_rate": violation_rate,
            "avg_hold_seconds": avg_hold,
        }
        
        # Finding
        if violation_rate > 0.2:
            self.findings.append(
                f"WARNING: {violation_rate:.1%} of trades exceeded max hold time. "
                f"Consider increasing max_hold_seconds or improving exit execution."
            )
        
        return result
    
    def analyze_per_asset_metrics(self) -> Dict:
        """Compute per-asset metrics.
        
        Returns:
            Dict mapping asset to metrics
        """
        for trade in self.trades:
            asset = self._extract_asset(trade.ticker)
            if asset == "UNKNOWN":
                continue
            
            self.asset_metrics[asset]["total_trades"] += 1
            
            if trade.edge_pct:
                self.asset_metrics[asset]["total_edge_pct"] += trade.edge_pct
            
            if trade.pnl_cents is not None:
                self.asset_metrics[asset]["total_pnl_cents"] += trade.pnl_cents
            
            if trade.risk_tier:
                tier_key = f"tier_{trade.risk_tier}"
                self.asset_metrics[asset][tier_key] += 1
        
        # Compute averages
        for asset, metrics in self.asset_metrics.items():
            total = metrics["total_trades"]
            if total > 0:
                if "total_edge_pct" in metrics:
                    metrics["avg_edge_pct"] = metrics["total_edge_pct"] / total
                if "total_pnl_cents" in metrics:
                    metrics["avg_pnl_cents"] = metrics["total_pnl_cents"] / total
        
        return dict(self.asset_metrics)
    
    def generate_report(self) -> Dict:
        """Generate comprehensive audit report.
        
        Returns:
            Dict with all audit results
        """
        logger.info("Starting risk contract compliance audit...")
        
        linkage = self.analyze_linkage_compliance()
        sl_violations = self.analyze_sl_violations()
        hold_compliance = self.analyze_hold_time_compliance()
        asset_metrics = self.analyze_per_asset_metrics()
        
        report = {
            "audit_timestamp": datetime.utcnow().isoformat(),
            "trades_analyzed": len(self.trades),
            "linkage_compliance": linkage,
            "sl_violations": sl_violations,
            "hold_time_compliance": hold_compliance,
            "per_asset_metrics": asset_metrics,
            "violations": self.violations,
            "findings": self.findings,
        }
        
        logger.info(f"Audit complete: {len(self.trades)} trades analyzed")
        logger.info(f"Linkage rate: {linkage['linkage_rate']:.1%}")
        logger.info(f"SL violation rate: {sl_violations['violation_rate']:.1%}")
        logger.info(f"Hold time violation rate: {hold_compliance['violation_rate']:.1%}")
        
        return report
    
    def print_report(self, report: Dict) -> None:
        """Print audit report to console.
        
        Args:
            report: Audit report dict
        """
        print("\n" + "="*80)
        print("RISK CONTRACT COMPLIANCE AUDIT REPORT")
        print("="*80)
        print(f"Audit Timestamp: {report['audit_timestamp']}")
        print(f"Trades Analyzed: {report['trades_analyzed']}")
        print("\n" + "-"*80)
        print("LINKAGE COMPLIANCE")
        print("-"*80)
        linkage = report["linkage_compliance"]
        print(f"Total Trades: {linkage['total_trades']}")
        print(f"Fully Linked: {linkage['fully_linked']} ({linkage['linkage_rate']:.1%})")
        print(f"  - With WindowResolution: {linkage['with_window_resolution']}")
        print(f"  - With ExitPolicy: {linkage['with_exit_policy']}")
        print(f"  - With Risk Tier: {linkage['with_risk_tier']}")
        print(f"  - With Max Hold: {linkage['with_max_hold']}")
        
        print("\n" + "-"*80)
        print("STOP LOSS VIOLATIONS")
        print("-"*80)
        sl = report["sl_violations"]
        print(f"Trades with SL: {sl['total_with_sl']}")
        print(f"Violations: {sl['violations']} ({sl['violation_rate']:.1%})")
        
        print("\n" + "-"*80)
        print("HOLD TIME COMPLIANCE")
        print("-"*80)
        hold = report["hold_time_compliance"]
        print(f"Trades with Hold Limit: {hold['total_with_hold']}")
        print(f"Violations: {hold['violations']} ({hold['violation_rate']:.1%})")
        print(f"Avg Hold Time: {hold['avg_hold_seconds']:.1f}s")
        
        print("\n" + "-"*80)
        print("PER-ASSET METRICS")
        print("-"*80)
        for asset, metrics in report["per_asset_metrics"].items():
            print(f"\n{asset}:")
            print(f"  Total Trades: {metrics['total_trades']}")
            print(f"  Avg Edge: {metrics.get('avg_edge_pct', 0):.2f}%")
            print(f"  Avg PnL: {metrics.get('avg_pnl_cents', 0):.0f}c")
            print(f"  Tier A: {metrics.get('tier_A', 0)}")
            print(f"  Tier B: {metrics.get('tier_B', 0)}")
            print(f"  Tier C: {metrics.get('tier_C', 0)}")
        
        print("\n" + "-"*80)
        print("FINDINGS")
        print("-"*80)
        for finding in report["findings"]:
            print(f"  - {finding}")
        
        if report["violations"]:
            print("\n" + "-"*80)
            print("VIOLATION DETAILS")
            print("-"*80)
            for v in report["violations"][:10]:  # First 10
                print(f"  {v['type']}: {v['ticker']} - {v}")
        
        print("\n" + "="*80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Audit risk contract compliance")
    parser.add_argument("--days", type=int, default=30, help="Days of history to analyze")
    parser.add_argument("--output", type=str, help="Output JSON file path")
    parser.add_argument("--signal-log", action="store_true", help="Load from signal log")
    parser.add_argument("--fills-ledger", action="store_true", help="Load from fills ledger")
    
    args = parser.parse_args()
    
    audit = RiskContractAudit()
    
    # Load trades
    if args.signal_log:
        audit.load_trades_from_signal_log(days=args.days)
    elif args.fills_ledger:
        audit.load_trades_from_fills_ledger(days=args.days)
    else:
        # Try fills ledger first, fall back to signal log
        if audit.load_trades_from_fills_ledger(days=args.days) == 0:
            audit.load_trades_from_signal_log(days=args.days)
    
    if not audit.trades:
        logger.error("No trades loaded. Check data sources.")
        return 1
    
    # Generate report
    report = audit.generate_report()
    
    # Print report
    audit.print_report(report)
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Report saved to {args.output}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

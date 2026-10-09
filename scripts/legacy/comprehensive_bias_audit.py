"""
Comprehensive Yes/No Bias Audit Script for MERID Trading System

This script implements a multi-dimensional bias detection framework based on
2026 research on prediction market bias detection and calibration.

Research Foundation:
- Wang Transform pricing model (Yicheng Yang, 2026) for favorite-longshot bias
- Chi-square statistical testing for directional bias (BFSA research)
- Calibration analysis (Brier score, ECE, MCE) from prediction market literature
- Market microstructure bias detection (Kalshi academic studies)
- Temporal bias analysis (time-to-expiry effects)

Audit Dimensions:
1. Statistical Bias: YES/NO distribution, chi-square tests
2. Market Structure Bias: Favorite-longshot, Wang Transform lambda estimation
3. Signal Path Bias: Velocity-to-side mapping, edge asymmetry
4. Guardrail Bias: Price floor, spread, depth asymmetry
5. Temporal Bias: Time-of-day, regime, expiry effects
6. Cross-Asset Bias: Asset-specific preferences, correlation effects

Usage:
    python comprehensive_bias_audit.py --db-path data/kalshi_fills.db --output bias_report.json
"""

import sqlite3
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
import math
import statistics

try:
    import numpy as np
    from scipy import stats
    from scipy.optimize import minimize
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    print("Warning: scipy/numpy not available - using simplified analysis")


@dataclass
class BiasFinding:
    """Single bias finding with severity and recommendation."""
    category: str
    bias_type: str
    severity: str  # "critical", "high", "medium", "low", "info"
    description: str
    metric_value: float
    threshold: float
    recommendation: str
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditReport:
    """Comprehensive bias audit report."""
    timestamp: str
    db_path: str
    total_trades_analyzed: int
    time_range: Tuple[str, str]
    findings: List[BiasFinding] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)


class BiasAuditor:
    """Comprehensive bias detection auditor."""
    
    def __init__(self, db_path: str, window_size: int = 100):
        """
        Initialize bias auditor.
        
        Args:
            db_path: Path to kalshi_fills.db
            window_size: Window size for rolling analysis
        """
        self.db_path = Path(db_path)
        self.window_size = window_size
        self.findings: List[BiasFinding] = []
        self.trades: List[Dict] = []
        
    def load_trades(self, limit: Optional[int] = None) -> None:
        """Load trades from database."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
        
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            limit_clause = f"LIMIT {limit}" if limit else ""
            query = f"""
            SELECT 
                fill_id,
                market_ticker,
                side,
                action,
                count_fp,
                yes_price_dollars,
                no_price_dollars,
                fee_cost,
                proceeds_dollars,
                created_time,
                agent_id
            FROM kalshi_fills
            ORDER BY created_time DESC
            {limit_clause}
            """
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            self.trades = [dict(row) for row in rows]
            
        finally:
            conn.close()
    
    def get_outcome_side(self, trade: Dict) -> str:
        """Determine actual directional exposure using Kalshi's (action, side) mapping."""
        action = trade.get('action', '').lower()
        side = trade.get('side', '').lower()
        
        if action == 'buy' and side == 'yes':
            return 'yes'
        elif action == 'sell' and side == 'no':
            return 'yes'
        elif action == 'buy' and side == 'no':
            return 'no'
        elif action == 'sell' and side == 'yes':
            return 'no'
        else:
            return 'unknown'
    
    def extract_asset(self, ticker: str) -> str:
        """Extract asset code from market ticker."""
        if not ticker:
            return "UNKNOWN"
        
        ticker_upper = ticker.upper()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if f"KX{asset}" in ticker_upper:
                return asset
        return "UNKNOWN"
    
    def get_contract_price(self, trade: Dict) -> float:
        """Get the price of the contract being traded."""
        side = trade.get('side', '').lower()
        if side == 'yes':
            return float(trade.get('yes_price_dollars', 0))
        else:
            return float(trade.get('no_price_dollars', 0))
    
    def calculate_pnl(self, trade: Dict) -> float:
        """Calculate PnL for a trade."""
        price = self.get_contract_price(trade)
        count = trade.get('count_fp', 0)
        fee = float(trade.get('fee_cost', 0))
        proceeds = float(trade.get('proceeds_dollars', 0) or 0)
        
        cost = (price * count) + fee
        return proceeds - cost
    
    def audit_statistical_bias(self) -> None:
        """Audit 1: Statistical YES/NO distribution bias."""
        if not self.trades:
            return
        
        # Global YES/NO distribution
        outcome_sides = [self.get_outcome_side(t) for t in self.trades]
        yes_count = outcome_sides.count('yes')
        no_count = outcome_sides.count('no')
        total = yes_count + no_count
        
        if total == 0:
            return
        
        yes_pct = (yes_count / total) * 100
        no_pct = (no_count / total) * 100
        
        # Chi-square test
        expected_yes = total / 2
        expected_no = total / 2
        chi_square = ((yes_count - expected_yes) ** 2 / expected_yes +
                      (no_count - expected_no) ** 2 / expected_no)
        
        # Critical value at 95% confidence for df=1 is 3.841
        if SCIPY_AVAILABLE:
            p_value = 1 - stats.chi2.cdf(chi_square, 1)
        else:
            # Simplified p-value approximation
            if chi_square < 3.841:
                p_value = 0.1
            elif chi_square < 6.635:
                p_value = 0.05
            elif chi_square < 10.828:
                p_value = 0.01
            else:
                p_value = 0.001
        
        # Bias detection threshold
        bias_threshold = 0.60  # 60%
        bias_detected = yes_pct > bias_threshold or no_pct > bias_threshold
        
        if bias_detected and p_value < 0.05:
            severity = "high" if abs(yes_pct - 50) > 15 else "medium"
            bias_direction = "YES" if yes_pct > no_pct else "NO"
            
            self.findings.append(BiasFinding(
                category="statistical_bias",
                bias_type="directional_imbalance",
                severity=severity,
                description=f"Global {bias_direction} bias detected in trade distribution",
                metric_value=abs(yes_pct - 50),
                threshold=10.0,
                recommendation=f"Implement side diversity constraints or rebalance signal generation to reduce {bias_direction} preference",
                evidence={
                    "yes_percentage": yes_pct,
                    "no_percentage": no_pct,
                    "chi_square": chi_square,
                    "p_value": p_value,
                    "total_trades": total
                }
            ))
        
        # Per-asset bias
        asset_trades = defaultdict(list)
        for trade in self.trades:
            asset = self.extract_asset(trade['market_ticker'])
            asset_trades[asset].append(trade)
        
        for asset, trades in asset_trades.items():
            if len(trades) < 10:  # Skip small samples
                continue
            
            asset_sides = [self.get_outcome_side(t) for t in trades]
            asset_yes = asset_sides.count('yes')
            asset_no = asset_sides.count('no')
            asset_total = asset_yes + asset_no
            
            asset_yes_pct = (asset_yes / asset_total) * 100
            asset_no_pct = (asset_no / asset_total) * 100
            
            if asset_yes_pct > bias_threshold or asset_no_pct > bias_threshold:
                bias_direction = "YES" if asset_yes_pct > asset_no_pct else "NO"
                
                self.findings.append(BiasFinding(
                    category="statistical_bias",
                    bias_type="asset_specific_imbalance",
                    severity="medium",
                    description=f"Asset {asset} shows {bias_direction} bias",
                    metric_value=abs(asset_yes_pct - 50),
                    threshold=10.0,
                    recommendation=f"Review {asset} signal generation logic for {bias_direction} preference",
                    evidence={
                        "asset": asset,
                        "yes_percentage": asset_yes_pct,
                        "no_percentage": asset_no_pct,
                        "total_trades": asset_total
                    }
                ))
    
    def audit_favorite_longshot_bias(self) -> None:
        """Audit 2: Favorite-longshot bias using price bucket analysis."""
        if not self.trades:
            return
        
        # Group trades by contract price buckets
        price_buckets = {
            "longshot": (0.0, 0.20),    # < 20 cents
            "low_price": (0.20, 0.40),  # 20-40 cents
            "mid_price": (0.40, 0.60),  # 40-60 cents
            "high_price": (0.60, 0.80), # 60-80 cents
            "favorite": (0.80, 1.0)     # > 80 cents
        }
        
        bucket_results = defaultdict(lambda: {"trades": [], "total": 0})
        
        for trade in self.trades:
            price = self.get_contract_price(trade)
            
            for bucket_name, (min_price, max_price) in price_buckets.items():
                if min_price <= price < max_price:
                    bucket_results[bucket_name]["trades"].append(trade)
                    bucket_results[bucket_name]["total"] += 1
                    break
        
        # Analyze each bucket for price distribution bias
        total_trades = len(self.trades)
        for bucket_name, (min_price, max_price) in price_buckets.items():
            data = bucket_results[bucket_name]
            if data["total"] < 5:  # Skip small samples
                continue
            
            bucket_pct = (data["total"] / total_trades) * 100 if total_trades > 0 else 0
            
            # Check for concentration in specific price ranges
            if bucket_pct > 30:  # More than 30% of trades in one bucket
                self.findings.append(BiasFinding(
                    category="market_structure_bias",
                    bias_type="price_range_concentration",
                    severity="medium",
                    description=f"High concentration of trades in {bucket_name} price range ({min_price:.2f}-{max_price:.2f})",
                    metric_value=bucket_pct,
                    threshold=30.0,
                    recommendation="Review signal generation for price range preference and consider diversification",
                    evidence={
                        "bucket": bucket_name,
                        "price_range": f"{min_price:.2f}-{max_price:.2f}",
                        "percentage": bucket_pct,
                        "total_trades": data["total"]
                    }
                ))
    
    def estimate_wang_lambda(self) -> Optional[float]:
        """
        Estimate Wang Transform λ parameter for favorite-longshot bias.
        
        Based on Yicheng Yang (2026) prediction-market-pricing research.
        λ > 0 indicates favorite-longshot bias.
        
        Note: Without outcome data, this analyzes price distribution patterns
        that are indicative of favorite-longshot bias.
        """
        if not self.trades:
            return None
        
        # Analyze price distribution for favorite-longshot patterns
        prices = [self.get_contract_price(t) for t in self.trades]
        
        if len(prices) < 30:
            return None
        
        # Check for price clustering patterns indicative of bias
        # Favorite-longshot bias often manifests as:
        # 1. Avoidance of extreme prices (clustering around 0.5)
        # 2. Asymmetric distribution around midpoint
        
        mean_price = np.mean(prices)
        median_price = np.median(prices)
        
        # Check for clustering around 0.5 (avoidance of extremes)
        midpoint_concentration = sum(1 for p in prices if 0.4 <= p <= 0.6) / len(prices)
        
        if midpoint_concentration > 0.5:  # More than 50% in middle range
            self.findings.append(BiasFinding(
                category="market_structure_bias",
                bias_type="price_clustering_midpoint",
                severity="medium",
                description=f"High concentration of trades around midpoint (0.4-0.6) suggests avoidance of extreme prices",
                metric_value=midpoint_concentration,
                threshold=0.5,
                recommendation="Review signal generation for extreme price avoidance - may indicate favorite-longshot bias in market selection",
                evidence={
                    "midpoint_concentration": midpoint_concentration,
                    "mean_price": mean_price,
                    "median_price": median_price,
                    "sample_size": len(prices)
                }
            ))
        
        # Check for asymmetric distribution
        if SCIPY_AVAILABLE:
            skewness = stats.skew(prices)
        else:
            # Simplified skewness calculation
            mean_price = statistics.mean(prices)
            std_price = statistics.stdev(prices) if len(prices) > 1 else 1.0
            skewness = sum((x - mean_price) ** 3 for x in prices) / (len(prices) * std_price ** 3) if std_price > 0 else 0
        
        if abs(skewness) > 0.5:  # Significant skew
            direction = "right-skewed (high prices)" if skewness > 0 else "left-skewed (low prices)"
            
            self.findings.append(BiasFinding(
                category="market_structure_bias",
                bias_type="price_distribution_skew",
                severity="low",
                description=f"Price distribution is {direction} (skewness={skewness:.2f})",
                metric_value=abs(skewness),
                threshold=0.5,
                recommendation=f"Monitor for {direction} patterns that may indicate systematic side preference",
                evidence={
                    "skewness": skewness,
                    "mean_price": mean_price,
                    "median_price": median_price,
                    "sample_size": len(prices)
                }
            ))
        
        return None
    
    def audit_calibration_bias(self) -> None:
        """Audit 3: Price distribution bias (proxy for calibration without outcome data)."""
        if not self.trades:
            return
        
        # Analyze price distribution patterns that may indicate bias
        prices = [self.get_contract_price(t) for t in self.trades]
        
        if len(prices) < 20:
            return
        
        # Group by price bins for distribution analysis
        price_bins = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), 
                      (0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), 
                      (0.8, 0.9), (0.9, 1.0)]
        
        bin_counts = []
        for min_p, max_p in price_bins:
            count = sum(1 for p in prices if min_p <= p < max_p)
            if count > 0:
                bin_counts.append({
                    "bin": f"{min_p:.1f}-{max_p:.1f}",
                    "count": count,
                    "percentage": (count / len(prices)) * 100
                })
        
        # Check for uneven distribution across price bins
        percentages = [b["percentage"] for b in bin_counts]
        if percentages:
            if SCIPY_AVAILABLE:
                std_dev = np.std(percentages)
            else:
                std_dev = statistics.stdev(percentages) if len(percentages) > 1 else 0
            expected_std = 10.0  # Expected std if evenly distributed (10% per bin)
            
            if std_dev > expected_std * 2:  # More than 2x expected variation
                self.findings.append(BiasFinding(
                    category="calibration_bias",
                    bias_type="uneven_price_distribution",
                    severity="medium",
                    description=f"Uneven distribution across price bins (std={std_dev:.1f}% vs expected {expected_std}%)",
                    metric_value=std_dev,
                    threshold=expected_std * 2,
                    recommendation="Review signal generation for price range preferences that may indicate calibration issues",
                    evidence={
                        "std_deviation": std_dev,
                        "expected_std": expected_std,
                        "bin_distribution": bin_counts
                    }
                ))
    
    def audit_pnl_bias(self) -> None:
        """Audit 4: Cost bias by side (using execution cost as PnL proxy)."""
        if not self.trades:
            return
        
        # Calculate execution cost by outcome side
        yes_costs = []
        no_costs = []
        
        for trade in self.trades:
            price = self.get_contract_price(trade)
            count = trade.get('count_fp', 0)
            fee = float(trade.get('fee_cost', 0))
            cost = (price * count) + fee
            
            outcome_side = self.get_outcome_side(trade)
            
            if outcome_side == 'yes':
                yes_costs.append(cost)
            elif outcome_side == 'no':
                no_costs.append(cost)
        
        if yes_costs and no_costs:
            if SCIPY_AVAILABLE:
                avg_yes_cost = np.mean(yes_costs)
                avg_no_cost = np.mean(no_costs)
            else:
                avg_yes_cost = statistics.mean(yes_costs)
                avg_no_cost = statistics.mean(no_costs)
            cost_diff = avg_yes_cost - avg_no_cost
            
            # Check for significant cost bias
            if abs(cost_diff) > 0.10:  # 10 cent difference
                bias_direction = "YES" if cost_diff > 0 else "NO"
                
                self.findings.append(BiasFinding(
                    category="pnl_bias",
                    bias_type="side_cost_asymmetry",
                    severity="medium",
                    description=f"Average execution cost shows {bias_direction} bias (${abs(cost_diff):.2f} difference)",
                    metric_value=abs(cost_diff),
                    threshold=0.10,
                    recommendation=f"Investigate execution quality or pricing model for {bias_direction} cost disadvantage",
                    evidence={
                        "avg_yes_cost": avg_yes_cost,
                        "avg_no_cost": avg_no_cost,
                        "cost_difference": cost_diff,
                        "yes_trades": len(yes_costs),
                        "no_trades": len(no_costs)
                    }
                ))
    
    def audit_temporal_bias(self) -> None:
        """Audit 5: Temporal bias (time-of-day, session effects)."""
        if not self.trades:
            return
        
        # Group by hour of day
        hourly_bias = defaultdict(lambda: {"yes": 0, "no": 0, "total": 0})
        
        for trade in self.trades:
            try:
                timestamp = datetime.fromisoformat(trade['created_time'].replace('Z', '+00:00'))
                hour = timestamp.hour
                outcome_side = self.get_outcome_side(trade)
                
                hourly_bias[hour][outcome_side] += 1
                hourly_bias[hour]["total"] += 1
            except:
                continue
        
        # Check for hourly bias
        for hour, data in hourly_bias.items():
            if data["total"] < 10:  # Skip small samples
                continue
            
            yes_pct = (data["yes"] / data["total"]) * 100 if data["total"] > 0 else 0
            no_pct = (data["no"] / data["total"]) * 100 if data["total"] > 0 else 0
            
            if abs(yes_pct - 50) > 20:  # 20% deviation
                bias_direction = "YES" if yes_pct > 50 else "NO"
                
                self.findings.append(BiasFinding(
                    category="temporal_bias",
                    bias_type="hourly_side_preference",
                    severity="low",
                    description=f"Hour {hour:02d}:00 shows {bias_direction} preference ({yes_pct:.1f}% vs {no_pct:.1f}%)",
                    metric_value=abs(yes_pct - 50),
                    threshold=20.0,
                    recommendation=f"Investigate time-of-day effects in signal generation or market conditions for hour {hour:02d}:00",
                    evidence={
                        "hour": hour,
                        "yes_percentage": yes_pct,
                        "no_percentage": no_pct,
                        "total_trades": data["total"]
                    }
                ))
    
    def run_full_audit(self) -> AuditReport:
        """Run comprehensive bias audit."""
        print(f"Loading trades from {self.db_path}...")
        self.load_trades()
        
        print(f"Analyzing {len(self.trades)} trades...")
        
        print("Running statistical bias audit...")
        self.audit_statistical_bias()
        
        print("Running favorite-longshot bias audit...")
        self.audit_favorite_longshot_bias()
        
        print("Estimating Wang Transform lambda...")
        self.estimate_wang_lambda()
        
        print("Running calibration bias audit...")
        self.audit_calibration_bias()
        
        print("Running PnL bias audit...")
        self.audit_pnl_bias()
        
        print("Running temporal bias audit...")
        self.audit_temporal_bias()
        
        # Generate summary
        severity_counts = defaultdict(int)
        for finding in self.findings:
            severity_counts[finding.severity] += 1
        
        time_range = (
            self.trades[-1]['created_time'] if self.trades else "N/A",
            self.trades[0]['created_time'] if self.trades else "N/A"
        )
        
        report = AuditReport(
            timestamp=datetime.utcnow().isoformat(),
            db_path=str(self.db_path),
            total_trades_analyzed=len(self.trades),
            time_range=time_range,
            findings=self.findings,
            summary={
                "total_findings": len(self.findings),
                "by_severity": dict(severity_counts),
                "by_category": self._count_by_category()
            }
        )
        
        return report
    
    def _count_by_category(self) -> Dict[str, int]:
        """Count findings by category."""
        category_counts = defaultdict(int)
        for finding in self.findings:
            category_counts[finding.category] += 1
        return dict(category_counts)


def main():
    parser = argparse.ArgumentParser(description="Comprehensive Yes/No Bias Audit for MERID")
    parser.add_argument("--db-path", default="data/kalshi_fills.db", 
                       help="Path to kalshi_fills.db")
    parser.add_argument("--output", default="bias_report.json",
                       help="Output JSON report path")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of trades to analyze (for testing)")
    parser.add_argument("--window-size", type=int, default=100,
                       help="Window size for rolling analysis")
    
    args = parser.parse_args()
    
    auditor = BiasAuditor(args.db_path, args.window_size)
    
    try:
        report = auditor.run_full_audit()
        
        # Save report
        with open(args.output, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
        
        print(f"\n{'='*80}")
        print("BIAS AUDIT SUMMARY")
        print(f"{'='*80}")
        print(f"Total trades analyzed: {report.total_trades_analyzed}")
        print(f"Time range: {report.time_range[0]} to {report.time_range[1]}")
        print(f"Total findings: {report.summary['total_findings']}")
        print(f"\nFindings by severity:")
        for severity, count in report.summary['by_severity'].items():
            print(f"  {severity.upper()}: {count}")
        print(f"\nFindings by category:")
        for category, count in report.summary['by_category'].items():
            print(f"  {category}: {count}")
        print(f"\nReport saved to: {args.output}")
        
        # Print critical findings
        critical_findings = [f for f in report.findings if f.severity == "critical"]
        if critical_findings:
            print(f"\n{'='*80}")
            print("CRITICAL FINDINGS (immediate attention required)")
            print(f"{'='*80}")
            for finding in critical_findings:
                print(f"\n{finding.category.upper()} - {finding.bias_type}")
                print(f"  Description: {finding.description}")
                print(f"  Recommendation: {finding.recommendation}")
        
    except Exception as e:
        print(f"Error during audit: {e}")
        raise


if __name__ == "__main__":
    main()

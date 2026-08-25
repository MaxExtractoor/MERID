"""
Simplified Bias Audit Framework for MERID Trading System

This is a simplified version that can work with synthetic data or CSV exports
when database access is problematic.

Usage:
    python bias_audit_framework.py --input trades.csv --output bias_report.json
"""

import json
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
import statistics


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
    data_source: str
    total_trades_analyzed: int
    findings: List[BiasFinding] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return asdict(self)


class SimpleBiasAuditor:
    """Simplified bias detection auditor for CSV/JSON data."""
    
    def __init__(self, data_source: str):
        """
        Initialize bias auditor.
        
        Args:
            data_source: Path to CSV/JSON file with trade data
        """
        self.data_source = Path(data_source)
        self.findings: List[BiasFinding] = []
        self.trades: List[Dict] = []
        
    def load_trades_from_csv(self) -> None:
        """Load trades from CSV file."""
        import csv
        
        if not self.data_source.exists():
            raise FileNotFoundError(f"Data file not found: {self.data_source}")
        
        with open(self.data_source, 'r') as f:
            reader = csv.DictReader(f)
            self.trades = [dict(row) for row in reader]
    
    def load_trades_from_json(self) -> None:
        """Load trades from JSON file."""
        if not self.data_source.exists():
            raise FileNotFoundError(f"Data file not found: {self.data_source}")
        
        with open(self.data_source, 'r') as f:
            data = json.load(f)
            if isinstance(data, list):
                self.trades = data
            elif isinstance(data, dict) and 'trades' in data:
                self.trades = data['trades']
            else:
                raise ValueError("Invalid JSON format")
    
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
        
        # Simple bias detection (without chi-square for simplicity)
        bias_threshold = 0.60  # 60%
        bias_detected = yes_pct > bias_threshold or no_pct > bias_threshold
        
        if bias_detected:
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
                    "total_trades": total
                }
            ))
        
        # Per-asset bias
        asset_trades = defaultdict(list)
        for trade in self.trades:
            asset = self.extract_asset(trade.get('market_ticker', ''))
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
    
    def audit_price_distribution_bias(self) -> None:
        """Audit 2: Price distribution bias."""
        if not self.trades:
            return
        
        prices = [self.get_contract_price(t) for t in self.trades]
        
        if len(prices) < 20:
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
            
            bucket_pct = (data["total"] / total_trades) * 100
            
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
    
    def audit_temporal_bias(self) -> None:
        """Audit 3: Temporal bias (time-of-day effects)."""
        if not self.trades:
            return
        
        # Group by hour of day
        hourly_bias = defaultdict(lambda: {"yes": 0, "no": 0, "total": 0})
        
        for trade in self.trades:
            try:
                timestamp_str = trade.get('created_time', '')
                if not timestamp_str:
                    continue
                    
                # Handle various timestamp formats
                if 'T' in timestamp_str:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else:
                    # Try parsing as Unix timestamp
                    timestamp = datetime.fromtimestamp(float(timestamp_str))
                
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
        print(f"Loading trades from {self.data_source}...")
        
        # Try to determine file type and load accordingly
        if self.data_source.suffix == '.csv':
            self.load_trades_from_csv()
        elif self.data_source.suffix == '.json':
            self.load_trades_from_json()
        else:
            raise ValueError(f"Unsupported file type: {self.data_source.suffix}")
        
        print(f"Analyzing {len(self.trades)} trades...")
        
        print("Running statistical bias audit...")
        self.audit_statistical_bias()
        
        print("Running price distribution bias audit...")
        self.audit_price_distribution_bias()
        
        print("Running temporal bias audit...")
        self.audit_temporal_bias()
        
        # Generate summary
        severity_counts = defaultdict(int)
        for finding in self.findings:
            severity_counts[finding.severity] += 1
        
        report = AuditReport(
            timestamp=datetime.utcnow().isoformat(),
            data_source=str(self.data_source),
            total_trades_analyzed=len(self.trades),
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


def generate_sample_data(output_path: str = "sample_trades.json") -> None:
    """Generate sample trade data for testing."""
    import random
    
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    actions = ["buy", "sell"]
    sides = ["yes", "no"]
    
    trades = []
    for i in range(100):
        trade = {
            "fill_id": f"fill_{i}",
            "market_ticker": f"KX{random.choice(assets)}15M-26AUG08{i%2:02d}000-15",
            "action": random.choice(actions),
            "side": random.choice(sides),
            "count_fp": random.randint(1, 5),
            "yes_price_dollars": round(random.uniform(0.1, 0.9), 2),
            "no_price_dollars": round(random.uniform(0.1, 0.9), 2),
            "fee_cost": round(random.uniform(0.01, 0.05), 2),
            "proceeds_dollars": round(random.uniform(0.0, 1.0), 2),
            "created_time": datetime.utcnow().isoformat(),
            "agent_id": "test_agent"
        }
        trades.append(trade)
    
    with open(output_path, 'w') as f:
        json.dump({"trades": trades}, f, indent=2)
    
    print(f"Generated {len(trades)} sample trades to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Simplified Bias Audit for MERID")
    parser.add_argument("--input",
                       help="Path to CSV/JSON file with trade data")
    parser.add_argument("--output", default="bias_report.json",
                       help="Output JSON report path")
    parser.add_argument("--generate-sample", action="store_true",
                       help="Generate sample trade data for testing")
    
    args = parser.parse_args()
    
    if args.generate_sample:
        generate_sample_data("sample_trades.json")
        return
    
    if not args.input:
        parser.error("--input is required unless --generate-sample is specified")
    
    auditor = SimpleBiasAuditor(args.input)
    
    try:
        report = auditor.run_full_audit()
        
        # Save report
        with open(args.output, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
        
        print(f"\n{'='*80}")
        print("BIAS AUDIT SUMMARY")
        print(f"{'='*80}")
        print(f"Total trades analyzed: {report.total_trades_analyzed}")
        print(f"Total findings: {report.summary['total_findings']}")
        print(f"\nFindings by severity:")
        for severity, count in report.summary['by_severity'].items():
            print(f"  {severity.upper()}: {count}")
        print(f"\nFindings by category:")
        for category, count in report.summary['by_category'].items():
            print(f"  {category}: {count}")
        print(f"\nReport saved to: {args.output}")
        
        # Print high severity findings
        high_findings = [f for f in report.findings if f.severity in ["critical", "high"]]
        if high_findings:
            print(f"\n{'='*80}")
            print("HIGH SEVERITY FINDINGS")
            print(f"{'='*80}")
            for finding in high_findings:
                print(f"\n{finding.category.upper()} - {finding.bias_type}")
                print(f"  Description: {finding.description}")
                print(f"  Recommendation: {finding.recommendation}")
        
    except Exception as e:
        print(f"Error during audit: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

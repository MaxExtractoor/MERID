"""Side Accuracy Analyzer - Detect flaws in agent yes/no decision making.

This script analyzes historical trade data to determine if agents are choosing
the correct side (YES/NO) based on velocity direction and actual outcomes.

Key analyses:
1. Side accuracy per agent and asset
2. Velocity-to-side mapping validation
3. Regime-specific side accuracy
4. Edge vs side correlation
5. Systematic bias detection (e.g., always choosing YES)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from merid.prediction.agent_performance_tracker import (
    AgentPerformanceTracker,
    TradeRecord,
    get_agent_performance_tracker,
)
from utils.logger import get_logger

logger = get_logger("merid.prediction.analyze_side_accuracy")


@dataclass
class SideAccuracyMetrics:
    """Side accuracy metrics for a grouping (agent, asset, regime, etc.)."""
    group_name: str
    total_trades: int = 0
    yes_trades: int = 0
    no_trades: int = 0
    yes_wins: int = 0
    no_wins: int = 0
    yes_losses: int = 0
    no_losses: int = 0
    
    # Velocity correlation
    positive_velocity_yes: int = 0  # Positive velocity -> YES (correct)
    positive_velocity_no: int = 0   # Positive velocity -> NO (incorrect)
    negative_velocity_yes: int = 0   # Negative velocity -> YES (incorrect)
    negative_velocity_no: int = 0    # Negative velocity -> NO (correct)
    
    # Edge metrics
    avg_edge_when_yes: float = 0.0
    avg_edge_when_no: float = 0.0
    avg_realized_edge_yes: float = 0.0
    avg_realized_edge_no: float = 0.0
    
    @property
    def yes_win_rate(self) -> float:
        """Win rate for YES trades."""
        if self.yes_trades == 0:
            return 0.0
        return self.yes_wins / self.yes_trades
    
    @property
    def no_win_rate(self) -> float:
        """Win rate for NO trades."""
        if self.no_trades == 0:
            return 0.0
        return self.no_wins / self.no_trades
    
    @property
    def overall_win_rate(self) -> float:
        """Overall win rate."""
        if self.total_trades == 0:
            return 0.0
        return (self.yes_wins + self.no_wins) / self.total_trades
    
    @property
    def velocity_side_accuracy(self) -> float:
        """Accuracy of velocity-to-side mapping."""
        correct = self.positive_velocity_yes + self.negative_velocity_no
        total = self.positive_velocity_yes + self.positive_velocity_no + self.negative_velocity_yes + self.negative_velocity_no
        if total == 0:
            return 0.0
        return correct / total
    
    @property
    def yes_bias(self) -> float:
        """Fraction of trades that are YES (detect systematic bias)."""
        if self.total_trades == 0:
            return 0.0
        return self.yes_trades / self.total_trades
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_name": self.group_name,
            "total_trades": self.total_trades,
            "yes_trades": self.yes_trades,
            "no_trades": self.no_trades,
            "yes_wins": self.yes_wins,
            "no_wins": self.no_wins,
            "yes_losses": self.yes_losses,
            "no_losses": self.no_losses,
            "yes_win_rate": round(self.yes_win_rate, 3),
            "no_win_rate": round(self.no_win_rate, 3),
            "overall_win_rate": round(self.overall_win_rate, 3),
            "velocity_side_accuracy": round(self.velocity_side_accuracy, 3),
            "yes_bias": round(self.yes_bias, 3),
            "avg_edge_when_yes": round(self.avg_edge_when_yes, 4),
            "avg_edge_when_no": round(self.avg_edge_when_no, 4),
            "avg_realized_edge_yes": round(self.avg_realized_edge_yes, 4),
            "avg_realized_edge_no": round(self.avg_realized_edge_no, 4),
        }


@dataclass
class SideAnomaly:
    """Detected anomaly in side decision making."""
    anomaly_type: str
    severity: str  # "critical", "warning", "info"
    description: str
    affected_group: str
    metric_value: float
    expected_value: float
    recommendation: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "description": self.description,
            "affected_group": self.affected_group,
            "metric_value": self.metric_value,
            "expected_value": self.expected_value,
            "recommendation": self.recommendation,
        }


class SideAccuracyAnalyzer:
    """Analyzes agent side decision accuracy from historical trade data."""
    
    def __init__(self, tracker: Optional[AgentPerformanceTracker] = None):
        self.tracker = tracker or get_agent_performance_tracker()
        self.anomalies: List[SideAnomaly] = []
        
    def analyze_all(self) -> Dict[str, Any]:
        """Run comprehensive side accuracy analysis."""
        logger.info("Starting comprehensive side accuracy analysis...")
        
        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "by_agent": self._analyze_by_agent(),
            "by_asset": self._analyze_by_asset(),
            "system_wide": self._analyze_system_wide(),
            "anomalies": [a.to_dict() for a in self.anomalies],
        }
        
        logger.info(f"Analysis complete. Found {len(self.anomalies)} anomalies.")
        return results
    
    def _analyze_by_agent(self) -> Dict[str, SideAccuracyMetrics]:
        """Analyze side accuracy per agent."""
        metrics_by_agent: Dict[str, SideAccuracyMetrics] = {}
        
        for trade in self.tracker._closed_trades:
            agent_id = trade.agent_id
            if agent_id not in metrics_by_agent:
                metrics_by_agent[agent_id] = SideAccuracyMetrics(group_name=agent_id)
            
            self._update_metrics(metrics_by_agent[agent_id], trade)
        
        # Post-calculate averages
        for metrics in metrics_by_agent.values():
            self._calculate_averages(metrics, [t for t in self.tracker._closed_trades if t.agent_id == metrics.group_name])
        
        # Detect anomalies
        for agent_id, metrics in metrics_by_agent.items():
            self._detect_agent_anomalies(agent_id, metrics)
        
        return {k: v.to_dict() for k, v in metrics_by_agent.items()}
    
    def _analyze_by_asset(self) -> Dict[str, SideAccuracyMetrics]:
        """Analyze side accuracy per asset (BTC, ETH, SOL, XRP, DOGE)."""
        metrics_by_asset: Dict[str, SideAccuracyMetrics] = {
            "BTC": SideAccuracyMetrics(group_name="BTC"),
            "ETH": SideAccuracyMetrics(group_name="ETH"),
            "SOL": SideAccuracyMetrics(group_name="SOL"),
            "XRP": SideAccuracyMetrics(group_name="XRP"),
            "DOGE": SideAccuracyMetrics(group_name="DOGE"),
        }
        
        for trade in self.tracker._closed_trades:
            # Extract asset from market_id (e.g., KXBTC15M-... -> BTC)
            asset = self._extract_asset_from_market_id(trade.market_id)
            if asset and asset in metrics_by_asset:
                self._update_metrics(metrics_by_asset[asset], trade)
        
        # Post-calculate averages
        for asset, metrics in metrics_by_asset.items():
            asset_trades = [t for t in self.tracker._closed_trades 
                          if self._extract_asset_from_market_id(t.market_id) == asset]
            self._calculate_averages(metrics, asset_trades)
        
        # Detect anomalies
        for asset, metrics in metrics_by_asset.items():
            if metrics.total_trades > 0:
                self._detect_asset_anomalies(asset, metrics)
        
        return {k: v.to_dict() for k, v in metrics_by_asset.items()}
    
    def _analyze_system_wide(self) -> SideAccuracyMetrics:
        """Analyze system-wide side accuracy."""
        system_metrics = SideAccuracyMetrics(group_name="SYSTEM_WIDE")
        
        for trade in self.tracker._closed_trades:
            self._update_metrics(system_metrics, trade)
        
        self._calculate_averages(system_metrics, self.tracker._closed_trades)
        self._detect_system_anomalies(system_metrics)
        
        return system_metrics.to_dict()
    
    def _update_metrics(self, metrics: SideAccuracyMetrics, trade: TradeRecord) -> None:
        """Update metrics with a single trade record."""
        metrics.total_trades += 1
        
        if trade.side == "yes":
            metrics.yes_trades += 1
            if trade.outcome == "win":
                metrics.yes_wins += 1
            elif trade.outcome == "loss":
                metrics.yes_losses += 1
        else:  # side == "no"
            metrics.no_trades += 1
            if trade.outcome == "win":
                metrics.no_wins += 1
            elif trade.outcome == "loss":
                metrics.no_losses += 1
        
        # Velocity correlation (using actual velocity field from TradeRecord)
        # Positive velocity (>0) -> should be YES
        # Negative velocity (<0) -> should be NO
        if trade.velocity is not None:
            if trade.velocity > 0:
                # Positive velocity -> should be YES
                if trade.side == "yes":
                    metrics.positive_velocity_yes += 1
                else:
                    metrics.positive_velocity_no += 1
            elif trade.velocity < 0:
                # Negative velocity -> should be NO
                if trade.side == "no":
                    metrics.negative_velocity_no += 1
                else:
                    metrics.negative_velocity_yes += 1
            # velocity == 0 is ignored (no conviction)
    
    def _calculate_averages(self, metrics: SideAccuracyMetrics, trades: List[TradeRecord]) -> None:
        """Calculate average edge metrics."""
        yes_trades = [t for t in trades if t.side == "yes"]
        no_trades = [t for t in trades if t.side == "no"]
        
        if yes_trades:
            metrics.avg_edge_when_yes = sum(t.predicted_edge for t in yes_trades) / len(yes_trades)
            realized_yes = [t.realized_edge for t in yes_trades if t.realized_edge is not None]
            if realized_yes:
                metrics.avg_realized_edge_yes = sum(realized_yes) / len(realized_yes)
        
        if no_trades:
            metrics.avg_edge_when_no = sum(t.predicted_edge for t in no_trades) / len(no_trades)
            realized_no = [t.realized_edge for t in no_trades if t.realized_edge is not None]
            if realized_no:
                metrics.avg_realized_edge_no = sum(realized_no) / len(realized_no)
    
    def _detect_agent_anomalies(self, agent_id: str, metrics: SideAccuracyMetrics) -> None:
        """Detect anomalies in agent side decision making."""
        # Check for systematic YES bias
        if metrics.yes_bias > 0.8 and metrics.total_trades > 10:
            self.anomalies.append(SideAnomaly(
                anomaly_type="systematic_yes_bias",
                severity="warning",
                description=f"Agent {agent_id} has extreme YES bias ({metrics.yes_bias:.1%} of trades are YES)",
                affected_group=agent_id,
                metric_value=metrics.yes_bias,
                expected_value=0.5,
                recommendation="Review velocity threshold settings - agent may be rejecting valid NO signals"
            ))
        
        # Check for systematic NO bias
        if metrics.yes_bias < 0.2 and metrics.total_trades > 10:
            self.anomalies.append(SideAnomaly(
                anomaly_type="systematic_no_bias",
                severity="warning",
                description=f"Agent {agent_id} has extreme NO bias ({(1-metrics.yes_bias):.1%} of trades are NO)",
                affected_group=agent_id,
                metric_value=1-metrics.yes_bias,
                expected_value=0.5,
                recommendation="Review velocity threshold settings - agent may be rejecting valid YES signals"
            ))
        
        # Check for poor velocity-to-side mapping
        if metrics.velocity_side_accuracy < 0.7 and metrics.total_trades > 10:
            self.anomalies.append(SideAnomaly(
                anomaly_type="poor_velocity_mapping",
                severity="critical",
                description=f"Agent {agent_id} has poor velocity-to-side mapping accuracy ({metrics.velocity_side_accuracy:.1%})",
                affected_group=agent_id,
                metric_value=metrics.velocity_side_accuracy,
                expected_value=0.9,
                recommendation="Edge sign doesn't match side selection - signal generation may be broken"
            ))
        
        # Check for YES underperformance
        if metrics.yes_win_rate < 0.4 and metrics.yes_trades > 10:
            self.anomalies.append(SideAnomaly(
                anomaly_type="yes_underperformance",
                severity="warning",
                description=f"Agent {agent_id} YES trades underperforming ({metrics.yes_win_rate:.1%} win rate)",
                affected_group=agent_id,
                metric_value=metrics.yes_win_rate,
                expected_value=0.5,
                recommendation="Review YES signal quality - may be entering YES contracts at unfavorable prices"
            ))
        
        # Check for NO underperformance
        if metrics.no_win_rate < 0.4 and metrics.no_trades > 10:
            self.anomalies.append(SideAnomaly(
                anomaly_type="no_underperformance",
                severity="warning",
                description=f"Agent {agent_id} NO trades underperforming ({metrics.no_win_rate:.1%} win rate)",
                affected_group=agent_id,
                metric_value=metrics.no_win_rate,
                expected_value=0.5,
                recommendation="Review NO signal quality - may be entering NO contracts at unfavorable prices"
            ))
    
    def _detect_asset_anomalies(self, asset: str, metrics: SideAccuracyMetrics) -> None:
        """Detect anomalies in asset-specific side decision making."""
        # Check for asset-specific YES bias
        if metrics.yes_bias > 0.8 and metrics.total_trades > 10:
            self.anomalies.append(SideAnomaly(
                anomaly_type="asset_yes_bias",
                severity="warning",
                description=f"Asset {asset} has extreme YES bias ({metrics.yes_bias:.1%} of trades are YES)",
                affected_group=asset,
                metric_value=metrics.yes_bias,
                expected_value=0.5,
                recommendation="Review velocity threshold for {asset} - may need asset-specific adjustment"
            ))
        
        # Check for asset-specific NO bias
        if metrics.yes_bias < 0.2 and metrics.total_trades > 10:
            self.anomalies.append(SideAnomaly(
                anomaly_type="asset_no_bias",
                severity="warning",
                description=f"Asset {asset} has extreme NO bias ({(1-metrics.yes_bias):.1%} of trades are NO)",
                affected_group=asset,
                metric_value=1-metrics.yes_bias,
                expected_value=0.5,
                recommendation="Review velocity threshold for {asset} - may need asset-specific adjustment"
            ))
    
    def _detect_system_anomalies(self, metrics: SideAccuracyMetrics) -> None:
        """Detect system-wide anomalies."""
        # Check for system-wide YES bias
        if metrics.yes_bias > 0.7 and metrics.total_trades > 20:
            self.anomalies.append(SideAnomaly(
                anomaly_type="system_yes_bias",
                severity="critical",
                description=f"System-wide YES bias detected ({metrics.yes_bias:.1%} of all trades are YES)",
                affected_group="SYSTEM",
                metric_value=metrics.yes_bias,
                expected_value=0.5,
                recommendation="Review velocity threshold configuration - may be too strict for NO signals"
            ))
        
        # Check for system-wide NO bias
        if metrics.yes_bias < 0.3 and metrics.total_trades > 20:
            self.anomalies.append(SideAnomaly(
                anomaly_type="system_no_bias",
                severity="critical",
                description=f"System-wide NO bias detected ({(1-metrics.yes_bias):.1%} of all trades are NO)",
                affected_group="SYSTEM",
                metric_value=1-metrics.yes_bias,
                expected_value=0.5,
                recommendation="Review velocity threshold configuration - may be too strict for YES signals"
            ))
        
        # Check for poor overall velocity mapping
        if metrics.velocity_side_accuracy < 0.8 and metrics.total_trades > 20:
            self.anomalies.append(SideAnomaly(
                anomaly_type="system_velocity_mapping",
                severity="critical",
                description=f"System-wide velocity-to-side mapping accuracy is poor ({metrics.velocity_side_accuracy:.1%})",
                affected_group="SYSTEM",
                metric_value=metrics.velocity_side_accuracy,
                expected_value=0.9,
                recommendation="Edge sign doesn't correlate with side selection - signal generation bug suspected"
            ))
    
    def _extract_asset_from_market_id(self, market_id: str) -> Optional[str]:
        """Extract asset code from Kalshi market ID."""
        market_id_upper = market_id.upper()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            if f"KX{asset}" in market_id_upper:
                return asset
        return None


def print_report(results: Dict[str, Any]) -> None:
    """Print a formatted analysis report."""
    print("\n" + "="*80)
    print("SIDE ACCURACY ANALYSIS REPORT")
    print("="*80)
    print(f"Generated: {results['timestamp']}")
    print("="*80 + "\n")
    
    # System-wide summary
    print("SYSTEM-WIDE SUMMARY")
    print("-" * 80)
    sys_metrics = results['system_wide']
    print(f"Total Trades: {sys_metrics['total_trades']}")
    print(f"YES Trades: {sys_metrics['yes_trades']} ({sys_metrics['yes_bias']:.1%})")
    print(f"NO Trades: {sys_metrics['no_trades']} ({1-sys_metrics['yes_bias']:.1%})")
    print(f"YES Win Rate: {sys_metrics['yes_win_rate']:.1%}")
    print(f"NO Win Rate: {sys_metrics['no_win_rate']:.1%}")
    print(f"Overall Win Rate: {sys_metrics['overall_win_rate']:.1%}")
    print(f"Velocity-to-Side Accuracy: {sys_metrics['velocity_side_accuracy']:.1%}")
    print(f"Avg Edge (YES): {sys_metrics['avg_edge_when_yes']:.4f}")
    print(f"Avg Edge (NO): {sys_metrics['avg_edge_when_no']:.4f}")
    print()
    
    # Per-asset breakdown
    print("PER-ASSET BREAKDOWN")
    print("-" * 80)
    for asset, metrics in results['by_asset'].items():
        if metrics['total_trades'] > 0:
            print(f"\n{asset}:")
            print(f"  Trades: {metrics['total_trades']} (YES: {metrics['yes_trades']}, NO: {metrics['no_trades']})")
            print(f"  YES Bias: {metrics['yes_bias']:.1%}")
            print(f"  YES Win Rate: {metrics['yes_win_rate']:.1%}")
            print(f"  NO Win Rate: {metrics['no_win_rate']:.1%}")
            print(f"  Velocity Accuracy: {metrics['velocity_side_accuracy']:.1%}")
    
    print()
    
    # Per-agent breakdown (top 10 by trade count)
    print("PER-AGENT BREAKDOWN (Top 10 by Trade Count)")
    print("-" * 80)
    sorted_agents = sorted(
        results['by_agent'].items(),
        key=lambda x: x[1]['total_trades'],
        reverse=True
    )[:10]
    
    for agent_id, metrics in sorted_agents:
        print(f"\n{agent_id}:")
        print(f"  Trades: {metrics['total_trades']} (YES: {metrics['yes_trades']}, NO: {metrics['no_trades']})")
        print(f"  YES Bias: {metrics['yes_bias']:.1%}")
        print(f"  YES Win Rate: {metrics['yes_win_rate']:.1%}")
        print(f"  NO Win Rate: {metrics['no_win_rate']:.1%}")
        print(f"  Velocity Accuracy: {metrics['velocity_side_accuracy']:.1%}")
    
    print()
    
    # Anomalies
    print("DETECTED ANOMALIES")
    print("-" * 80)
    if results['anomalies']:
        for anomaly in results['anomalies']:
            severity_icon = "🔴" if anomaly['severity'] == 'critical' else "⚠️" if anomaly['severity'] == 'warning' else "ℹ️"
            print(f"\n{severity_icon} {anomaly['anomaly_type'].upper()} [{anomaly['severity']}]")
            print(f"   Affected: {anomaly['affected_group']}")
            print(f"   Description: {anomaly['description']}")
            print(f"   Value: {anomaly['metric_value']:.3f} (expected: {anomaly['expected_value']:.3f})")
            print(f"   Recommendation: {anomaly['recommendation']}")
    else:
        print("No anomalies detected.")
    
    print("\n" + "="*80 + "\n")


def generate_mock_trades(num_trades: int = 100) -> List[TradeRecord]:
    """Generate mock trade data for testing the analyzer."""
    import random
    import time
    
    assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    agents = ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]
    
    trades = []
    now = time.time()
    
    for i in range(num_trades):
        asset = random.choice(assets)
        agent = f"{asset}_15M"
        
        # Simulate velocity-based side selection
        # Positive velocity -> YES, negative velocity -> NO
        velocity = random.uniform(-0.001, 0.001)
        side = "yes" if velocity > 0 else "no"
        
        # Edge correlates with velocity magnitude
        edge = abs(velocity) * 100 + random.uniform(-0.01, 0.02)
        edge = max(0.01, min(0.15, edge))
        
        # Outcome: side is correct 60% of the time
        is_correct = random.random() < 0.6
        if side == "yes":
            outcome = "win" if is_correct else "loss"
        else:
            outcome = "win" if is_correct else "loss"
        
        # Realized edge
        realized_edge = edge if outcome == "win" else -edge
        
        trade = TradeRecord(
            agent_id=agent,
            market_id=f"KX{asset}15M-{i}",
            side=side,
            entry_price_cents=random.randint(10, 75),
            contracts=random.randint(1, 5),
            entry_ts=now - random.uniform(0, 86400),
            predicted_edge=edge,
            confidence=random.uniform(0.5, 0.9),
            velocity=velocity,
            exit_price_cents=random.randint(10, 99),
            exit_ts=now - random.uniform(0, 86400) + random.uniform(60, 900),
            profit_usd=Decimal(str(random.uniform(-5, 10) if outcome == "win" else random.uniform(-10, -1))),
            realized_edge=realized_edge,
            outcome=outcome,
        )
        trades.append(trade)
    
    return trades


def main():
    parser = argparse.ArgumentParser(description="Analyze agent yes/no decision accuracy")
    parser.add_argument(
        "--output",
        type=str,
        default="side_accuracy_report.json",
        help="Output file for JSON report"
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print formatted report to console"
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=5,
        help="Minimum trades required for analysis"
    )
    parser.add_argument(
        "--mock-data",
        type=int,
        default=0,
        help="Generate N mock trades for testing (0 = use real data)"
    )
    parser.add_argument(
        "--load-from-db",
        action="store_true",
        help="Load trades from kalshi_fills.db database"
    )
    
    args = parser.parse_args()
    
    # Run analysis
    analyzer = SideAccuracyAnalyzer()
    
    # Load from database if requested
    if args.load_from_db:
        logger.info("Loading trades from kalshi_fills.db...")
        from merid.prediction.extract_trade_data import extract_trades_last_48h
        db_trades = extract_trades_last_48h()
        analyzer.tracker._closed_trades = db_trades
        logger.info(f"Loaded {len(db_trades)} trades from database")
    # Inject mock data if requested
    elif args.mock_data > 0:
        logger.info(f"Generating {args.mock_data} mock trades for testing...")
        mock_trades = generate_mock_trades(args.mock_data)
        analyzer.tracker._closed_trades = mock_trades
        logger.info(f"Mock data injected: {len(mock_trades)} trades")
    
    results = analyzer.analyze_all()
    
    # Save JSON report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Report saved to {output_path}")
    
    # Print report if requested
    if args.print:
        print_report(results)


if __name__ == "__main__":
    main()

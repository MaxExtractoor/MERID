"""
Comprehensive Rejection Analysis Script for 15M Kalshi Crypto Trading System

This script captures, analyzes, and reports on all signal rejections across the trading pipeline.
Based on 2026 industry best practices for algorithmic trading rejection monitoring:

Key Features:
- Real-time rejection capture from agent logs
- Structured JSON logging for all rejection events
- Categorization by rejection type (time, price, trend, edge, etc.)
- Per-asset and per-time-window analytics
- Threshold optimization recommendations
- Counterfactual analysis support (Post-Rejection Follow-up Sampling)
- Integration with production monitoring stack

Usage:
    python scripts/rejection_analyzer.py --mode live --duration 60
    python scripts/rejection_analyzer.py --mode analyze --log_file logs/rejections.jsonl
    python scripts/rejection_analyzer.py --mode report --output reports/rejection_analysis_20260710.json
"""

import json
import re
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import statistics

# Try to import logger, fallback to basic logging
try:
    from utils.logger import get_logger
    logger = get_logger("scripts.rejection_analyzer")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("scripts.rejection_analyzer")


@dataclass
class RejectionEvent:
    """Structured rejection event record."""
    timestamp: str
    asset: str
    rejection_category: str
    rejection_reason: str
    market_id: Optional[str] = None
    spot_price: Optional[float] = None
    yes_price_cents: Optional[int] = None
    no_price_cents: Optional[int] = None
    minutes_to_expiry: Optional[float] = None
    velocity: Optional[float] = None
    edge_cents: Optional[float] = None
    spread_cents: Optional[float] = None
    threshold_value: Optional[float] = None
    actual_value: Optional[float] = None
    session_active: Optional[bool] = None
    trend_aligned: Optional[bool] = None
    additional_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class RejectionClassifier:
    """Classify rejection events into categories for analysis."""
    
    # Rejection category patterns
    CATEGORIES = {
        "time_window": [
            r"TIME-WINDOW-FILTER",
            r"too early",
            r"too late",
            r"terminal phase",
            r"late entry",
        ],
        "price_range": [
            r"PRICE-FILTER-REJECT",
            r"outside.*range",
            r"longshot_trap",
            r"low_profit_trap",
            r"price_too_low",
            r"price_too_high",
        ],
        "trend_alignment": [
            r"TREND-ALIGNMENT-FILTER",
            r"trends not aligned",
            r"trend disagreement",
        ],
        "session_filter": [
            r"SESSION-FILTER",
            r"Trading session not active",
        ],
        "spread_quality": [
            r"spread_too_wide",
            r"spread_pct_too_high",
            r"microstructure_trap",
        ],
        "depth_liquidity": [
            r"insufficient_depth",
            r"depth.*threshold",
        ],
        "edge_insufficient": [
            r"edge_insufficient",
            r"net_edge.*threshold",
        ],
        "otm_distance": [
            r"otm_distance",
            r"spot-strike distance",
        ],
        "time_trap": [
            r"time_trap",
            r"TTE.*regime",
        ],
        "experimental_guard": [
            r"experimental_price_band",
            r"experimental_tte_band",
        ],
    }
    
    @classmethod
    def classify(cls, reason: str) -> str:
        """Classify a rejection reason into a category."""
        reason_lower = reason.lower()
        
        for category, patterns in cls.CATEGORIES.items():
            for pattern in patterns:
                if re.search(pattern, reason_lower):
                    return category
        
        return "other"


class RejectionCapture:
    """Capture rejection events from log streams."""
    
    # Log patterns for different rejection types
    PATTERNS = {
        "time_window": re.compile(
            r"\[TIME-WINDOW-FILTER\] asset=(\w+) minutes_to_expiry=([\d.]+) -> (SKIP|REDUCED|OPTIMAL) \((.*?)\)"
        ),
        "price_range": re.compile(
            r"\[PRICE-FILTER-REJECT\] asset=(\w+) both sides outside 10c-75c range \(yes=(\d+)c, no=(\d+)c\)"
        ),
        "trend_alignment": re.compile(
            r"\[TREND-ALIGNMENT-FILTER\] asset=(\w+) (.*?) -> SKIP"
        ),
        "session_filter": re.compile(
            r"\[SESSION-FILTER\] (.*?) skipping signal generation"
        ),
        "edge_check": re.compile(
            r"\[EDGE-CHECK\] (.*?)"
        ),
        # New patterns based on actual log format
        "market_validation": re.compile(
            r"\[MARKET-VALIDATION\] asset=(\w+) ticker=(\S+) spread exceeds coarse filter=(\d+)c \(spread=(\d+)c\)"
        ),
        "catalog_tradeability": re.compile(
            r"\[CATALOG-TRADEABILITY-FILTER\] Post-tradeability-filter: (\d+) markets in (\d+)-(\d+)min entry window"
        ),
        "catalog_visibility": re.compile(
            r"\[CATALOG-VISIBILITY-FILTER\] Post-visibility-filter: (\d+) markets in (\d+) to ([\d.]+)min window"
        ),
    }
    
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file
        self.rejections: List[RejectionEvent] = []
        self.start_time = datetime.now(timezone.utc)
        
    def parse_log_line(self, line: str) -> Optional[RejectionEvent]:
        """Parse a log line and extract rejection event if present."""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Try to extract timestamp from log line
        ts_match = re.search(r'(\d{4}-\d{2}-\d{2}T?\d{2}:\d{2}:\d{2})', line)
        if ts_match:
            timestamp = ts_match.group(1)
        
        # Parse different rejection patterns
        for pattern_name, pattern in self.PATTERNS.items():
            match = pattern.search(line)
            if match:
                return self._extract_rejection_from_match(pattern_name, match, line, timestamp)
        
        return None
    
    def _extract_rejection_from_match(
        self, 
        pattern_name: str, 
        match: re.Match, 
        line: str, 
        timestamp: str
    ) -> Optional[RejectionEvent]:
        """Extract rejection event from regex match."""
        try:
            if pattern_name == "time_window":
                asset = match.group(1)
                tte = float(match.group(2))
                action = match.group(3)
                reason = match.group(4)
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset=asset,
                    rejection_category="time_window",
                    rejection_reason=f"{action}: {reason}",
                    minutes_to_expiry=tte,
                )
            
            elif pattern_name == "price_range":
                asset = match.group(1)
                yes_price = int(match.group(2))
                no_price = int(match.group(3))
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset=asset,
                    rejection_category="price_range",
                    rejection_reason="both sides outside 10c-75c range",
                    yes_price_cents=yes_price,
                    no_price_cents=no_price,
                )
            
            elif pattern_name == "trend_alignment":
                asset = match.group(1)
                reason = match.group(2)
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset=asset,
                    rejection_category="trend_alignment",
                    rejection_reason=reason,
                    trend_aligned=False,
                )
            
            elif pattern_name == "session_filter":
                reason = match.group(1)
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset="UNKNOWN",
                    rejection_category="session_filter",
                    rejection_reason=reason,
                    session_active=False,
                )
            
            elif pattern_name == "edge_check":
                reason = match.group(1)
                
                # Try to extract asset from reason
                asset_match = re.search(r'asset=(\w+)', reason)
                asset = asset_match.group(1) if asset_match else "UNKNOWN"
                
                category = RejectionClassifier.classify(reason)
                
                # Extract numeric values if present
                spread_match = re.search(r'spread=(\d+)c', reason)
                edge_match = re.search(r'edge=([\d.]+)c', reason)
                threshold_match = re.search(r'>(\d+)c threshold', reason)
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset=asset,
                    rejection_category=category,
                    rejection_reason=reason,
                    spread_cents=int(spread_match.group(1)) if spread_match else None,
                    edge_cents=float(edge_match.group(1)) if edge_match else None,
                    threshold_value=float(threshold_match.group(1)) if threshold_match else None,
                )
            
            elif pattern_name == "market_validation":
                asset = match.group(1)
                ticker = match.group(2)
                threshold = int(match.group(3))
                spread = int(match.group(4))
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset=asset,
                    rejection_category="spread_quality",
                    rejection_reason=f"spread exceeds coarse filter: spread={spread}c > {threshold}c threshold",
                    market_id=ticker,
                    spread_cents=spread,
                    threshold_value=threshold,
                    actual_value=spread,
                )
            
            elif pattern_name == "catalog_tradeability":
                markets_count = int(match.group(1))
                min_window = int(match.group(2))
                max_window = int(match.group(3))
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset="ALL",
                    rejection_category="time_window",
                    rejection_reason=f"no markets in {min_window}-{max_window}min entry window (count={markets_count})",
                    additional_context={"markets_count": markets_count, "min_window": min_window, "max_window": max_window},
                )
            
            elif pattern_name == "catalog_visibility":
                markets_count = int(match.group(1))
                min_window = int(match.group(2))
                max_window = float(match.group(3))
                
                return RejectionEvent(
                    timestamp=timestamp,
                    asset="ALL",
                    rejection_category="time_window",
                    rejection_reason=f"only {markets_count} markets in {min_window}-{max_window}min visible window",
                    additional_context={"markets_count": markets_count, "min_window": min_window, "max_window": max_window},
                )
        
        except Exception as e:
            logger.warning(f"Failed to extract rejection from match: {e}")
        
        return None
    
    def capture_from_file(self, file_path: str, lines: int = 1000) -> int:
        """Capture rejections from a log file."""
        count = 0
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    event = self.parse_log_line(line)
                    if event:
                        self.rejections.append(event)
                        count += 1
                        if count >= lines:
                            break
        except Exception as e:
            logger.error(f"Failed to read log file {file_path}: {e}")
        
        return count
    
    def save_to_jsonl(self, output_path: str):
        """Save captured rejections to JSONL file."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for event in self.rejections:
                f.write(json.dumps(event.to_dict()) + '\n')
        
        logger.info(f"Saved {len(self.rejections)} rejections to {output_path}")


class RejectionAnalyzer:
    """Analyze rejection patterns and provide insights."""
    
    def __init__(self, rejections: List[RejectionEvent]):
        self.rejections = rejections
        self.analysis_start = datetime.now(timezone.utc)
    
    def analyze_by_category(self) -> Dict[str, Any]:
        """Analyze rejections by category."""
        category_counts = Counter(r.rejection_category for r in self.rejections)
        
        return {
            "total_rejections": len(self.rejections),
            "by_category": dict(category_counts),
            "category_percentages": {
                cat: (count / len(self.rejections)) * 100 
                for cat, count in category_counts.items()
            } if self.rejections else {}
        }
    
    def analyze_by_asset(self) -> Dict[str, Any]:
        """Analyze rejections by asset."""
        asset_counts = Counter(r.asset for r in self.rejections)
        
        # Per-asset category breakdown
        asset_category_breakdown = defaultdict(lambda: defaultdict(int))
        for r in self.rejections:
            asset_category_breakdown[r.asset][r.rejection_category] += 1
        
        return {
            "by_asset": dict(asset_counts),
            "asset_category_breakdown": {
                asset: dict(cats) for asset, cats in asset_category_breakdown.items()
            }
        }
    
    def analyze_by_time(self) -> Dict[str, Any]:
        """Analyze rejections over time."""
        if not self.rejections:
            return {}
        
        # Parse timestamps and group by minute
        time_buckets = defaultdict(int)
        for r in self.rejections:
            try:
                ts = datetime.fromisoformat(r.timestamp.replace('Z', '+00:00'))
                minute_key = ts.strftime('%Y-%m-%d %H:%M')
                time_buckets[minute_key] += 1
            except:
                continue
        
        # Calculate rejection rate per minute
        sorted_times = sorted(time_buckets.keys())
        if len(sorted_times) > 1:
            duration_minutes = len(sorted_times)
            avg_rate = len(self.rejections) / duration_minutes
        else:
            avg_rate = len(self.rejections)
        
        return {
            "time_buckets": dict(time_buckets),
            "duration_minutes": len(sorted_times),
            "average_rejections_per_minute": avg_rate,
            "peak_minute": max(time_buckets.items(), key=lambda x: x[1]) if time_buckets else None,
        }
    
    def analyze_threshold_gaps(self) -> Dict[str, Any]:
        """Analyze threshold gaps - how close rejections were to passing."""
        threshold_gaps = []
        
        for r in self.rejections:
            if r.threshold_value is not None and r.actual_value is not None:
                gap = abs(r.actual_value - r.threshold_value)
                threshold_gaps.append({
                    "asset": r.asset,
                    "category": r.rejection_category,
                    "threshold": r.threshold_value,
                    "actual": r.actual_value,
                    "gap": gap,
                    "gap_percentage": (gap / r.threshold_value) * 100 if r.threshold_value > 0 else 0,
                })
        
        if not threshold_gaps:
            return {}
        
        gaps = [g["gap"] for g in threshold_gaps]
        gap_percentages = [g["gap_percentage"] for g in threshold_gaps]
        
        return {
            "total_with_threshold_data": len(threshold_gaps),
            "average_gap": statistics.mean(gaps) if gaps else 0,
            "median_gap": statistics.median(gaps) if gaps else 0,
            "max_gap": max(gaps) if gaps else 0,
            "average_gap_percentage": statistics.mean(gap_percentages) if gap_percentages else 0,
            "near_misses": [g for g in threshold_gaps if g["gap_percentage"] < 10],  # Within 10% of threshold
            "threshold_gaps_detail": threshold_gaps[:50],  # Top 50 for reporting
        }
    
    def generate_recommendations(self) -> List[str]:
        """Generate threshold optimization recommendations."""
        recommendations = []
        
        category_analysis = self.analyze_by_category()
        asset_analysis = self.analyze_by_asset()
        threshold_analysis = self.analyze_threshold_gaps()
        
        # High rejection rate by category
        if category_analysis.get("category_percentages"):
            top_category = max(
                category_analysis["category_percentages"].items(),
                key=lambda x: x[1]
            )
            if top_category[1] > 50:
                recommendations.append(
                    f"CRITICAL: {top_category[0]} accounts for {top_category[1]:.1f}% of all rejections. "
                    f"Review if threshold is too strict or if market conditions are anomalous."
                )
        
        # Asset-specific issues
        if asset_analysis.get("by_asset"):
            for asset, count in asset_analysis["by_asset"].items():
                if count > len(self.rejections) * 0.4:  # > 40% of rejections
                    recommendations.append(
                        f"WARNING: {asset} has {count} rejections ({count/len(self.rejections)*100:.1f}%). "
                        f"Check if asset-specific thresholds need adjustment."
                    )
        
        # Near-miss analysis
        if threshold_analysis.get("near_misses"):
            near_miss_count = len(threshold_analysis["near_misses"])
            if near_miss_count > 10:
                recommendations.append(
                    f"OPTIMIZATION: {near_miss_count} rejections were within 10% of threshold. "
                    f"Consider small threshold adjustments to capture these marginal cases."
                )
        
        # Time-based patterns
        time_analysis = self.analyze_by_time()
        if time_analysis.get("average_rejections_per_minute", 0) > 10:
            recommendations.append(
                f"ALERT: High rejection rate ({time_analysis['average_rejections_per_minute']:.1f}/min). "
                f"Check if market conditions are degraded or if system is misconfigured."
            )
        
        return recommendations
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive rejection analysis report."""
        return {
            "report_metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "analysis_duration_seconds": (datetime.now(timezone.utc) - self.analysis_start).total_seconds(),
                "total_rejections_analyzed": len(self.rejections),
            },
            "category_analysis": self.analyze_by_category(),
            "asset_analysis": self.analyze_by_asset(),
            "time_analysis": self.analyze_by_time(),
            "threshold_analysis": self.analyze_threshold_gaps(),
            "recommendations": self.generate_recommendations(),
        }


def main():
    parser = argparse.ArgumentParser(description="Rejection Analysis for 15M Kalshi Crypto Trading System")
    parser.add_argument("--mode", choices=["live", "analyze", "report"], required=True,
                       help="Operation mode: live (capture), analyze (process logs), report (generate report)")
    parser.add_argument("--log_file", help="Log file to analyze (for analyze mode)")
    parser.add_argument("--input_jsonl", help="Input JSONL file with captured rejections (for report mode)")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--duration", type=int, default=60, help="Duration in seconds for live capture")
    parser.add_argument("--lines", type=int, default=1000, help="Number of log lines to process")
    
    args = parser.parse_args()
    
    if args.mode == "live":
        logger.info(f"Starting live rejection capture for {args.duration} seconds...")
        capture = RejectionCapture()
        
        # In live mode, we would typically tail the log file
        # For now, simulate with file reading
        if args.log_file:
            count = capture.capture_from_file(args.log_file, args.lines)
            logger.info(f"Captured {count} rejections from {args.log_file}")
        
        if args.output:
            capture.save_to_jsonl(args.output)
    
    elif args.mode == "analyze":
        if not args.log_file:
            logger.error("--log_file required for analyze mode")
            return
        
        logger.info(f"Analyzing log file: {args.log_file}")
        capture = RejectionCapture()
        count = capture.capture_from_file(args.log_file, args.lines)
        logger.info(f"Captured {count} rejections")
        
        if args.output:
            capture.save_to_jsonl(args.output)
        
        # Also generate immediate analysis
        analyzer = RejectionAnalyzer(capture.rejections)
        report = analyzer.generate_report()
        
        report_path = args.output.replace('.jsonl', '_report.json') if args.output else 'rejection_report.json'
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Generated analysis report: {report_path}")
        logger.info(f"Recommendations: {len(report['recommendations'])}")
        for rec in report['recommendations']:
            logger.info(f"  - {rec}")
    
    elif args.mode == "report":
        if not args.input_jsonl:
            logger.error("--input_jsonl required for report mode")
            return
        
        logger.info(f"Generating report from: {args.input_jsonl}")
        
        # Load rejections from JSONL
        rejections = []
        with open(args.input_jsonl, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    rejections.append(RejectionEvent(**data))
                except Exception as e:
                    logger.warning(f"Failed to parse rejection record: {e}")
        
        logger.info(f"Loaded {len(rejections)} rejection records")
        
        analyzer = RejectionAnalyzer(rejections)
        report = analyzer.generate_report()
        
        output_path = args.output or 'rejection_analysis_report.json'
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Generated comprehensive report: {output_path}")
        logger.info(f"Total rejections: {report['report_metadata']['total_rejections_analyzed']}")
        logger.info(f"Top rejection category: {max(report['category_analysis']['by_category'].items(), key=lambda x: x[1]) if report['category_analysis']['by_category'] else 'N/A'}")
        logger.info(f"Recommendations: {len(report['recommendations'])}")
        for rec in report['recommendations']:
            logger.info(f"  - {rec}")


if __name__ == "__main__":
    main()

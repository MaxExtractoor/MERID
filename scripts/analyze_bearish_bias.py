#!/usr/bin/env python3
"""
Comprehensive diagnostic script to identify bearish bias in trading stack.

Analyzes recent trades to determine where bias is being introduced:
- Signal generation (agent grid, indicators, gates)
- Risk gating
- Order routing
- Downstream filters
"""

import json
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Any
import sqlite3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BiasAnalyzer:
    """Analyze trading data for systematic bias."""
    
    def __init__(self):
        self.trades = []
        self.signals = []
        self.candidates = []
        self.bias_metrics = {}
        
    def load_recent_trades(self, limit=100):
        """Load recent trades from database or logs."""
        # Try to load from SQLite database first
        db_path = "data/trades.db"
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Get recent trades
                cursor.execute("""
                    SELECT * FROM trades 
                    ORDER BY timestamp DESC 
                    LIMIT ?
                """, (limit,))
                
                columns = [desc[0] for desc in cursor.description]
                for row in cursor.fetchall():
                    trade = dict(zip(columns, row))
                    self.trades.append(trade)
                
                conn.close()
                print(f"Loaded {len(self.trades)} trades from database")
                return True
            except Exception as e:
                print(f"Error loading from database: {e}")
        
        # Fallback: try to load from log files
        log_files = [
            "server_output.log",
            "data/trade_log.json",
            "output/trade_history.json",
        ]
        
        for log_file in log_files:
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r') as f:
                        content = f.read()
                        # Parse JSON if applicable
                        if log_file.endswith('.json'):
                            data = json.loads(content)
                            if isinstance(data, list):
                                self.trades = data[:limit]
                            elif isinstance(data, dict):
                                self.trades = list(data.values())[:limit]
                            print(f"Loaded {len(self.trades)} trades from {log_file}")
                            return True
                except Exception as e:
                    print(f"Error loading from {log_file}: {e}")
        
        print("Warning: Could not load trade data")
        return False
    
    def analyze_side_distribution(self):
        """Analyze distribution of YES/NO sides."""
        if not self.trades:
            print("No trades to analyze")
            return
        
        side_counts = Counter()
        for trade in self.trades:
            side = trade.get('side', trade.get('action', 'UNKNOWN'))
            side_counts[side] += 1
        
        print("\n=== SIDE DISTRIBUTION ===")
        for side, count in side_counts.most_common():
            pct = (count / len(self.trades)) * 100
            print(f"{side}: {count} ({pct:.1f}%)")
        
        self.bias_metrics['side_distribution'] = dict(side_counts)
        
        # Check for extreme bias
        if len(side_counts) == 1:
            print(f"⚠️  EXTREME BIAS: 100% of trades are {list(side_counts.keys())[0]}")
        elif max(side_counts.values()) / len(self.trades) > 0.9:
            print(f"⚠️  HEAVY BIAS: {max(side_counts.values()) / len(self.trades) * 100:.1f}% of trades are {side_counts.most_common(1)[0][0]}")
    
    def analyze_signal_vs_execution(self):
        """Analyze if signals are being filtered or transformed."""
        print("\n=== SIGNAL vs EXECUTION ANALYSIS ===")
        
        # For each trade, try to find the original signal
        for trade in self.trades[:10]:  # Sample first 10
            print(f"\nTrade: {trade.get('timestamp', 'N/A')}")
            print(f"  Executed side: {trade.get('side', 'N/A')}")
            print(f"  Signal side: {trade.get('signal_side', 'N/A')}")
            print(f"  Candidate side: {trade.get('candidate_side', 'N/A')}")
            
            # Check if side was inverted
            if 'signal_side' in trade and 'side' in trade:
                if trade['signal_side'] != trade['side']:
                    print(f"  ⚠️  SIDE INVERSION DETECTED: {trade['signal_side']} -> {trade['side']}")
    
    def analyze_price_distribution(self):
        """Analyze price distribution of executed trades."""
        print("\n=== PRICE DISTRIBUTION ===")
        
        prices = []
        for trade in self.trades:
            price = trade.get('price', trade.get('execution_price', 0))
            if price:
                prices.append(price)
        
        if prices:
            print(f"Min price: ${min(prices):.2f}")
            print(f"Max price: ${max(prices):.2f}")
            print(f"Avg price: ${sum(prices)/len(prices):.2f}")
            
            # Check if all trades are in high price range (could indicate bias)
            high_price_count = sum(1 for p in prices if p > 0.75)
            if high_price_count / len(prices) > 0.8:
                print(f"⚠️  HIGH PRICE BIAS: {high_price_count/len(prices)*100:.1f}% of trades > $0.75")
    
    def analyze_asset_distribution(self):
        """Analyze distribution across assets."""
        print("\n=== ASSET DISTRIBUTION ===")
        
        asset_counts = Counter()
        for trade in self.trades:
            asset = trade.get('asset', trade.get('ticker', 'UNKNOWN'))
            asset_counts[asset] += 1
        
        for asset, count in asset_counts.most_common():
            pct = (count / len(self.trades)) * 100
            print(f"{asset}: {count} ({pct:.1f}%)")
    
    def analyze_velocity_at_execution(self):
        """Analyze velocity values at time of execution."""
        print("\n=== VELOCITY AT EXECUTION ===")
        
        velocities = []
        for trade in self.trades:
            velocity = trade.get('velocity', trade.get('signal_velocity', None))
            if velocity is not None:
                velocities.append(velocity)
        
        if velocities:
            print(f"Min velocity: {min(velocities):.6f}")
            print(f"Max velocity: {max(velocities):.6f}")
            print(f"Avg velocity: {sum(velocities)/len(velocities):.6f}")
            
            positive_count = sum(1 for v in velocities if v > 0)
            negative_count = sum(1 for v in velocities if v < 0)
            
            print(f"Positive velocities: {positive_count} ({positive_count/len(velocities)*100:.1f}%)")
            print(f"Negative velocities: {negative_count} ({negative_count/len(velocities)*100:.1f}%)")
            
            if negative_count / len(velocities) > 0.8:
                print(f"⚠️  NEGATIVE VELOCITY BIAS: {negative_count/len(velocities)*100:.1f}% of executions had negative velocity")
    
    def analyze_indicator_values(self):
        """Analyze indicator values at execution."""
        print("\n=== INDICATOR VALUES ===")
        
        indicators = ['macd_histogram', 'rsi', 'obi', 'fvg_direction', 'fvg_confidence']
        
        for indicator in indicators:
            values = []
            for trade in self.trades:
                val = trade.get(indicator, None)
                if val is not None:
                    values.append(val)
            
            if values:
                print(f"\n{indicator}:")
                print(f"  Count: {len(values)}")
                if isinstance(values[0], (int, float)):
                    print(f"  Min: {min(values):.4f}")
                    print(f"  Max: {max(values):.4f}")
                    print(f"  Avg: {sum(values)/len(values):.4f}")
                else:
                    counter = Counter(values)
                    for val, count in counter.most_common():
                        print(f"  {val}: {count}")
    
    def generate_report(self):
        """Generate comprehensive bias report."""
        print("\n" + "="*60)
        print("BEARISH BIAS ANALYSIS REPORT")
        print("="*60)
        
        self.analyze_side_distribution()
        self.analyze_signal_vs_execution()
        self.analyze_price_distribution()
        self.analyze_asset_distribution()
        self.analyze_velocity_at_execution()
        self.analyze_indicator_values()
        
        print("\n" + "="*60)
        print("RECOMMENDATIONS")
        print("="*60)
        
        # Generate recommendations based on findings
        if 'side_distribution' in self.bias_metrics:
            sides = list(self.bias_metrics['side_distribution'].keys())
            if 'sell' in [s.lower() for s in sides]:
                print("1. Investigate signal generation logic - why only SELL signals?")
                print("2. Check velocity calculation - verify epsilon fix is applied")
                print("3. Review risk gating - check if BUY YES is being rejected")
                print("4. Examine order routing - check for side inversion bugs")
                print("5. Analyze downstream filters - check for asymmetric filtering")
        
        print("\nNext steps:")
        print("- Review agent_grid_15m.py signal generation")
        print("- Review quantitative_gates.py filtering logic")
        print("- Review order_router.py side handling")
        print("- Review risk_parameters.py thresholds")


def main():
    """Main analysis function."""
    analyzer = BiasAnalyzer()
    
    print("Loading recent trades...")
    analyzer.load_recent_trades(limit=100)
    
    if analyzer.trades:
        analyzer.generate_report()
        
        # Save report to file
        report_file = f"bias_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_file, 'w') as f:
            # Redirect print to file
            import io
            from contextlib import redirect_stdout
            
            f_capture = io.StringIO()
            with redirect_stdout(f_capture):
                analyzer.generate_report()
            f.write(f_capture.getvalue())
        
        print(f"\nReport saved to: {report_file}")
    else:
        print("No trade data available for analysis")
        print("\nManual investigation required:")
        print("1. Check server_output.log for recent trades")
        print("2. Check database for trade records")
        print("3. Review agent grid logs for signal generation")


if __name__ == "__main__":
    main()

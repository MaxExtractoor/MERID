#!/usr/bin/env python3
"""
Deep audit script to trace trade lifecycle from signal generation to exit.
Audits signal layer, exit policy, risk management, and high leverage bugs.
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

def analyze_trade_lifecycle():
    """Analyze the specific trades from 2026-07-09 15:11:23 and 15:13:38."""
    db_path = Path('data/kalshi_fills.db')
    
    if not db_path.exists():
        print("ERROR: Fills database not found")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get fills around the target time
    target_time = "2026-07-09T15:11:23"
    cursor.execute("""
        SELECT * FROM kalshi_fills 
        WHERE created_time >= '2026-07-09T15:00:00' 
        AND created_time <= '2026-07-09T16:00:00'
        ORDER BY created_time ASC
    """)
    
    cursor.execute("PRAGMA table_info(kalshi_fills);")
    columns = [col[1] for col in cursor.fetchall()]
    
    fills = cursor.fetchall()
    
    print("=" * 80)
    print("TRADE LIFECYCLE AUDIT - 2026-07-09 15:00-16:00")
    print("=" * 80)
    print()
    
    if not fills:
        print("No fills found in target time window")
        conn.close()
        return
    
    print(f"Found {len(fills)} fills in target window")
    print()
    
    # Analyze each fill
    for i, fill in enumerate(fills, 1):
        fill_dict = dict(zip(columns, fill))
        print(f"Fill {i}:")
        print(f"  Time: {fill_dict.get('created_time')}")
        print(f"  Ticker: {fill_dict.get('market_ticker')}")
        print(f"  Side: {fill_dict.get('side')}")
        print(f"  Action: {fill_dict.get('action')}")
        print(f"  Count: {fill_dict.get('count_fp')}")
        print(f"  YES Price: ${fill_dict.get('yes_price_dollars')}")
        print(f"  NO Price: ${fill_dict.get('no_price_dollars')}")
        print(f"  Proceeds: ${fill_dict.get('proceeds_dollars')}")
        print(f"  Order ID: {fill_dict.get('order_id')}")
        print(f"  Agent ID: {fill_dict.get('agent_id')}")
        print(f"  Intent ID: {fill_dict.get('intent_id')}")
        print()
    
    conn.close()

def audit_signal_generation():
    """Audit signal generation layer for premature exit triggers."""
    print("=" * 80)
    print("SIGNAL GENERATION LAYER AUDIT")
    print("=" * 80)
    print()
    
    # Check signal generation code
    signal_files = [
        'merid/prediction/agent_grid_15m.py',
        'merid/prediction/fvg_integration.py',
        'merid/prediction/momentum_fvg.py',
    ]
    
    for file_path in signal_files:
        path = Path(file_path)
        if path.exists():
            print(f"Checking {file_path}...")
            content = path.read_text(encoding='utf-8', errors='ignore')
            
            # Check for exit-related logic
            has_exit_logic = 'exit' in content.lower() or 'should_exit' in content.lower()
            has_timing_logic = 'time' in content.lower() and 'exit' in content.lower()
            has_risk_logic = 'risk' in content.lower() and 'exit' in content.lower()
            
            print(f"  Has exit logic: {has_exit_logic}")
            print(f"  Has timing-based exit: {has_timing_logic}")
            print(f"  Has risk-based exit: {has_risk_logic}")
            print()

def audit_exit_policy():
    """Audit exit policy logic for early exit conditions."""
    print("=" * 80)
    print("EXIT POLICY LAYER AUDIT")
    print("=" * 80)
    print()
    
    exit_policy_path = Path('merid/position_management/exit_policy.py')
    if exit_policy_path.exists():
        content = exit_policy_path.read_text(encoding='utf-8', errors='ignore')
        
        # Check exit conditions
        has_time_stop = 'evaluate_time_stop' in content
        has_loss_cap = 'evaluate_loss_cap' in content
        has_candle_reversal = 'evaluate_candle_reversal' in content
        has_adaptive_timing = 'evaluate_adaptive_timing' in content
        has_edge_decay = 'evaluate_edge_decay' in content
        has_risk_kill = 'evaluate_risk' in content
        
        print("Exit conditions:")
        print(f"  Time stop: {has_time_stop}")
        print(f"  Loss cap: {has_loss_cap}")
        print(f"  Candle reversal: {has_candle_reversal}")
        print(f"  Adaptive timing: {has_adaptive_timing}")
        print(f"  Edge decay: {has_edge_decay}")
        print(f"  Risk kill switch: {has_risk_kill}")
        print()
        
        # Check exit precedence
        if 'EXIT PRECEDENCE ORDER' in content:
            print("Exit precedence order documented:")
            for line in content.split('\n'):
                if 'EXIT PRECEDENCE ORDER' in line or (line.strip().startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.'))):
                    print(f"  {line.strip()}")
        print()

def audit_risk_management():
    """Audit risk management layer for forced exit triggers."""
    print("=" * 80)
    print("RISK MANAGEMENT LAYER AUDIT")
    print("=" * 80)
    print()
    
    risk_files = [
        'merid/guards/unified_risk_manager.py',
        'merid/risk/position_sizing.py',
        'merid/risk/portfolio_optimizer.py',
    ]
    
    for file_path in risk_files:
        path = Path(file_path)
        if path.exists():
            print(f"Checking {file_path}...")
            content = path.read_text(encoding='utf-8', errors='ignore')
            
            # Check for forced exit logic
            has_forced_exit = 'force.*exit' in content.lower() or 'kill.*switch' in content.lower()
            has_position_limit = 'position.*limit' in content.lower() or 'max.*position' in content.lower()
            has_exposure_limit = 'exposure.*limit' in content.lower() or 'max.*exposure' in content.lower()
            
            print(f"  Has forced exit: {has_forced_exit}")
            print(f"  Has position limits: {has_position_limit}")
            print(f"  Has exposure limits: {has_exposure_limit}")
            print()

def audit_high_leverage_bugs():
    """Check for high leverage bugs across the stack."""
    print("=" * 80)
    print("HIGH LEVERAGE BUG AUDIT")
    print("=" * 80)
    print()
    
    # Check for common leverage bugs
    leverage_patterns = [
        ('position sizing', ['position_size', 'size', 'contracts']),
        ('leverage calculation', ['leverage', 'margin', 'notional']),
        ('risk limits', ['max_loss', 'risk_limit', 'exposure']),
        ('decimal scaling', ['cents', 'dollars', '100', '0.01']),
    ]
    
    critical_files = [
        'merid/loop_15m.py',
        'merid/prediction/agent_grid_15m.py',
        'merid/event_venues/kalshi/order_router.py',
        'merid/position_management/position_monitor.py',
    ]
    
    for file_path in critical_files:
        path = Path(file_path)
        if path.exists():
            print(f"Checking {file_path}...")
            content = path.read_text(encoding='utf-8', errors='ignore')
            
            for category, patterns in leverage_patterns:
                for pattern in patterns:
                    if pattern in content.lower():
                        print(f"  Found {category} pattern: {pattern}")
            print()

def main():
    print("=" * 80)
    print("END-TO-END TRADE LIFECYCLE AUDIT")
    print("=" * 80)
    print()
    
    # Analyze the specific trades
    analyze_trade_lifecycle()
    
    # Audit each layer
    audit_signal_generation()
    audit_exit_policy()
    audit_risk_management()
    audit_high_leverage_bugs()
    
    print("=" * 80)
    print("AUDIT COMPLETE")
    print("=" * 80)

if __name__ == '__main__':
    main()

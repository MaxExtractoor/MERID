#!/usr/bin/env python3
"""
Post-Trade Surveillance Reconciliation Job

This script performs daily reconciliation of trading system records against
Kalshi venue data to detect anomalies in fee calculation, PnL, and drawdown behavior.

This aligns with algo risk best practices for regular reconciliation between
trading system records and clearing/venue data, and scanning for anomalies
in behavior vs configured risk parameters.

Usage:
    python scripts/surveillance_reconciliation.py --date YYYY-MM-DD
    python scripts/surveillance_reconciliation.py --days 7  # Last 7 days

Output:
    JSON report with reconciliation results and surveillance warnings
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from decimal import Decimal


def load_internal_fills(date: datetime) -> List[Dict[str, Any]]:
    """
    Load fills from internal fills_ledger.py for a given date.
    
    Args:
        date: Date to load fills for
        
    Returns:
        List of fill records
    """
    # Placeholder: In production, this would query the fills_ledger
    # or database for fills on the given date
    fills = []
    
    # Example fill record structure:
    # {
    #     'id': 'fill_123',
    #     'timestamp': '2026-05-15T10:30:00Z',
    #     'agent': 'BTC_15M',
    #     'contracts': 10,
    #     'price_cents': 55,
    #     'fee_cents': 17,
    #     'pnl': -5.00,
    #     'side': 'yes'
    # }
    
    return fills


def load_venue_fees(date: datetime) -> Dict[str, float]:
    """
    Load fee data from Kalshi venue API/exports for a given date.
    
    Args:
        date: Date to load fees for
        
    Returns:
        Dict mapping agent name to total fees in USD
    """
    # Placeholder: In production, this would query Kalshi API
    # or download fee statements from Kalshi exports
    venue_fees = {}
    
    # Example:
    # venue_fees['BTC_15M'] = 12.50
    # venue_fees['ETH_15M'] = 8.75
    
    return venue_fees


def compute_expected_fees(fills: List[Dict[str, Any]]) -> float:
    """
    Compute expected fees using canonical fees.py for a list of fills.
    
    Args:
        fills: List of fill records
        
    Returns:
        Total expected fees in USD
    """
    try:
        from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
        
        total_expected_cents = 0
        for fill in fills:
            contracts = int(fill.get('contracts', 1))
            price_cents = int(fill.get('price_cents', 50))
            fee_cents = calculate_kalshi_fee_cents(contracts, price_cents)
            total_expected_cents += fee_cents
        
        return total_expected_cents / 100.0  # Convert to USD
        
    except ImportError:
        # Fallback: use recorded fees from fills
        total_recorded_cents = sum(int(f.get('fee_cents', 0)) for f in fills)
        return total_recorded_cents / 100.0


def reconcile_fees(
    internal_fills: List[Dict[str, Any]],
    venue_fees: Dict[str, float],
) -> List[Dict[str, Any]]:
    """
    Reconcile internal fee records against venue fee data.
    
    Args:
        internal_fills: Internal fill records
        venue_fees: Venue fee data by agent
        
    Returns:
        List of reconciliation results per agent
    """
    results = []
    
    # Group fills by agent
    fills_by_agent = {}
    for fill in internal_fills:
        agent = fill.get('agent', 'unknown')
        if agent not in fills_by_agent:
            fills_by_agent[agent] = []
        fills_by_agent[agent].append(fill)
    
    for agent, agent_fills in fills_by_agent.items():
        # Compute internal fees
        internal_fees = sum(f.get('fee_cents', 0) for f in agent_fills) / 100.0
        expected_fees = compute_expected_fees(agent_fills)
        venue_fee = venue_fees.get(agent, 0.0)
        
        # Compute notional for fee rate calculation
        notional = sum(
            f.get('contracts', 0) * f.get('price_cents', 0) / 100.0
            for f in agent_fills
        )
        
        internal_fee_rate = internal_fees / notional if notional > 0 else 0.0
        expected_fee_rate = expected_fees / notional if notional > 0 else 0.0
        
        result = {
            'agent': agent,
            'internal_fees_usd': internal_fees,
            'expected_fees_usd': expected_fees,
            'venue_fees_usd': venue_fee,
            'notional_usd': notional,
            'internal_fee_rate': internal_fee_rate,
            'expected_fee_rate': expected_fee_rate,
            'fee_drift_pct': abs(internal_fee_rate - expected_fee_rate) / expected_fee_rate if expected_fee_rate > 0 else 0.0,
            'venue_drift_pct': abs(internal_fees - venue_fee) / venue_fee if venue_fee > 0 else 0.0,
        }
        
        results.append(result)
    
    return results


def check_drawdown_compliance(
    fills: List[Dict[str, Any]],
    profile_limits: Dict[str, float],
) -> Dict[str, Any]:
    """
    Check if drawdown behavior complies with profile limits.
    
    Args:
        fills: Fill records for the day
        profile_limits: Profile drawdown limits
        
    Returns:
        Drawdown compliance check results
    """
    # Compute daily PnL
    daily_pnl = sum(f.get('pnl', 0) for f in fills)
    
    # Compute max intraday drawdown (simplified)
    # In production, this would track running equity throughout the day
    max_drawdown_pct = 0.0
    if daily_pnl < 0:
        # Simplified: assume starting equity of $1000
        max_drawdown_pct = abs(daily_pnl) / 1000.0
    
    # Check compliance
    daily_loss_cap = profile_limits.get('max_daily_loss_usd', 200.0)
    drawdown_halt_pct = profile_limits.get('drawdown_halt_pct', 0.10)
    drawdown_unwind_pct = profile_limits.get('drawdown_unwind_pct', 0.15)
    
    daily_loss_breached = daily_pnl <= -daily_loss_cap
    drawdown_halt_breached = max_drawdown_pct >= drawdown_halt_pct
    drawdown_unwind_breached = max_drawdown_pct >= drawdown_unwind_pct
    
    return {
        'daily_pnl_usd': daily_pnl,
        'max_drawdown_pct': max_drawdown_pct,
        'daily_loss_cap_usd': daily_loss_cap,
        'drawdown_halt_pct': drawdown_halt_pct,
        'drawdown_unwind_pct': drawdown_unwind_pct,
        'daily_loss_breached': daily_loss_breached,
        'drawdown_halt_breached': drawdown_halt_breached,
        'drawdown_unwind_breached': drawdown_unwind_breached,
        'compliance': not (daily_loss_breached or drawdown_halt_breached),
    }


def load_profile_limits() -> Dict[str, float]:
    """
    Load profile drawdown limits from active profile.
    
    Returns:
        Dict of profile limits
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        adapter = get_active_profile()
        if not adapter:
            return {}
        
        profile = adapter.profile
        guardrails = getattr(profile, 'guardrails', None)
        
        if not guardrails:
            return {}
        
        return {
            'drawdown_halt_pct': float(getattr(guardrails, 'guardrails_drawdown_halt_pct', 0.10)),
            'drawdown_unwind_pct': float(getattr(guardrails, 'guardrails_drawdown_unwind_pct', 0.15)),
            'max_daily_loss_usd': float(getattr(guardrails, 'guardrails_max_daily_loss_usd', 200.0)),
        }
        
    except Exception:
        return {}


def generate_surveillance_warnings(
    fee_reconciliation: List[Dict[str, Any]],
    drawdown_compliance: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Generate surveillance warnings based on reconciliation results.
    
    Args:
        fee_reconciliation: Fee reconciliation results
        drawdown_compliance: Drawdown compliance check results
        
    Returns:
        List of surveillance warnings
    """
    warnings = []
    
    # Fee warnings
    for result in fee_reconciliation:
        # Check for fee drift > 5%
        if result['fee_drift_pct'] > 0.05:
            warnings.append({
                'type': 'fee_drift',
                'severity': 'MEDIUM',
                'agent': result['agent'],
                'message': f"Fee drift {result['fee_drift_pct']:.2%} from expected rate",
                'internal_fee_rate': result['internal_fee_rate'],
                'expected_fee_rate': result['expected_fee_rate'],
            })
        
        # Check for venue drift > 10%
        if result['venue_drift_pct'] > 0.10:
            warnings.append({
                'type': 'venue_fee_mismatch',
                'severity': 'HIGH',
                'agent': result['agent'],
                'message': f"Internal fees {result['internal_fees_usd']:.2f} differ from venue {result['venue_fees_usd']:.2f} by {result['venue_drift_pct']:.2%}",
                'internal_fees_usd': result['internal_fees_usd'],
                'venue_fees_usd': result['venue_fees_usd'],
            })
    
    # Drawdown warnings
    if drawdown_compliance['daily_loss_breached']:
        warnings.append({
            'type': 'daily_loss_breach',
            'severity': 'HIGH',
            'message': f"Daily loss ${drawdown_compliance['daily_pnl_usd']:.2f} exceeded cap ${drawdown_compliance['daily_loss_cap_usd']:.2f}",
            'daily_pnl_usd': drawdown_compliance['daily_pnl_usd'],
            'daily_loss_cap_usd': drawdown_compliance['daily_loss_cap_usd'],
        })
    
    if drawdown_compliance['drawdown_halt_breached']:
        warnings.append({
            'type': 'drawdown_halt_breach',
            'severity': 'HIGH',
            'message': f"Drawdown {drawdown_compliance['max_drawdown_pct']:.2%} exceeded halt threshold {drawdown_compliance['drawdown_halt_pct']:.2%}",
            'max_drawdown_pct': drawdown_compliance['max_drawdown_pct'],
            'drawdown_halt_pct': drawdown_compliance['drawdown_halt_pct'],
        })
    
    return warnings


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Post-Trade Surveillance Reconciliation')
    parser.add_argument(
        '--date',
        type=str,
        default=None,
        help='Date to reconcile (YYYY-MM-DD), default: yesterday'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=1,
        help='Number of days to reconcile, default: 1'
    )
    parser.add_argument(
        '--output',
        '-o',
        type=str,
        default='surveillance_report.json',
        help='Output report file (default: surveillance_report.json)'
    )
    
    args = parser.parse_args()
    
    # Determine date range
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d')
    else:
        target_date = datetime.now() - timedelta(days=1)
    
    date_range = [target_date - timedelta(days=i) for i in range(args.days)]
    
    print(f"Running surveillance reconciliation for {len(date_range)} day(s)")
    print(f"Date range: {[d.strftime('%Y-%m-%d') for d in date_range]}")
    
    # Load profile limits
    profile_limits = load_profile_limits()
    print(f"Profile limits: {profile_limits}")
    
    # Run reconciliation for each day
    all_results = []
    all_warnings = []
    
    for date in date_range:
        print(f"\nReconciling {date.strftime('%Y-%m-%d')}...")
        
        # Load internal fills
        internal_fills = load_internal_fills(date)
        print(f"  Loaded {len(internal_fills)} fills")
        
        # Load venue fees
        venue_fees = load_venue_fees(date)
        print(f"  Loaded venue fees for {len(venue_fees)} agents")
        
        # Reconcile fees
        fee_reconciliation = reconcile_fees(internal_fills, venue_fees)
        print(f"  Fee reconciliation: {len(fee_reconciliation)} agents")
        
        # Check drawdown compliance
        drawdown_compliance = check_drawdown_compliance(internal_fills, profile_limits)
        print(f"  Daily PnL: ${drawdown_compliance['daily_pnl_usd']:.2f}")
        print(f"  Max drawdown: {drawdown_compliance['max_drawdown_pct']:.2%}")
        print(f"  Compliance: {drawdown_compliance['compliance']}")
        
        # Generate warnings
        warnings = generate_surveillance_warnings(fee_reconciliation, drawdown_compliance)
        print(f"  Warnings: {len(warnings)}")
        
        all_results.append({
            'date': date.strftime('%Y-%m-%d'),
            'fee_reconciliation': fee_reconciliation,
            'drawdown_compliance': drawdown_compliance,
        })
        all_warnings.extend(warnings)
    
    # Generate report
    report = {
        'report_date': datetime.now().isoformat() + 'Z',
        'date_range': [d.strftime('%Y-%m-%d') for d in date_range],
        'profile_limits': profile_limits,
        'results': all_results,
        'warnings': all_warnings,
        'summary': {
            'total_days': len(date_range),
            'total_warnings': len(all_warnings),
            'high_severity_warnings': len([w for w in all_warnings if w['severity'] == 'HIGH']),
            'medium_severity_warnings': len([w for w in all_warnings if w['severity'] == 'MEDIUM']),
        },
    }
    
    # Write report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\nSurveillance report generated: {output_path}")
    print(f"Total warnings: {len(all_warnings)}")
    print(f"High severity: {report['summary']['high_severity_warnings']}")
    print(f"Medium severity: {report['summary']['medium_severity_warnings']}")
    
    # Return exit code based on warnings
    if report['summary']['high_severity_warnings'] > 0:
        print("\nHIGH severity warnings detected - review required")
        return 1
    elif report['summary']['medium_severity_warnings'] > 0:
        print("\nMEDIUM severity warnings detected - review recommended")
        return 0
    else:
        print("\nNo warnings - surveillance check passed")
        return 0


if __name__ == '__main__':
    sys.exit(main())

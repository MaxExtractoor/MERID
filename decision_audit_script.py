#!/usr/bin/env python3
"""
Comprehensive Decision Audit for 15-minute Crypto Trades

This script builds a decision ledger for resolved trades to identify why
the strategy selected NO exposure on markets that resolved YES.
"""

import csv
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict

@dataclass
class DecisionRecord:
    """Complete decision record for audit analysis."""
    # Trade identifiers
    fill_id: str
    order_id: str
    market_ticker: str
    asset: str
    client_order_id: Optional[str] = None
    
    # Market information
    market_title: Optional[str] = None
    market_rules: Optional[str] = None
    series_ticker: Optional[str] = None
    
    # Timing information
    market_open_time: Optional[datetime] = None
    market_close_time: Optional[datetime] = None
    settlement_time: Optional[datetime] = None
    decision_time: Optional[datetime] = None
    
    # Contract predicate and target
    contract_predicate: Optional[str] = None  # ABOVE, BELOW, AT_OR_ABOVE, AT_OR_BELOW
    strike_price: Optional[float] = None
    target_price: Optional[float] = None
    
    # Strategy decision
    strategy_thesis: Optional[str] = None  # YES or NO
    strategy_reason: Optional[str] = None
    signal_scores: Optional[Dict[str, float]] = None
    
    # Underlying information
    underlying_source: Optional[str] = None
    underlying_symbol: Optional[str] = None
    underlying_exchange: Optional[str] = None
    spot_event_time: Optional[datetime] = None
    spot_receive_time: Optional[datetime] = None
    spot_price_used: Optional[float] = None
    spot_freshness_ms: Optional[int] = None
    
    # Market quotes at decision
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    no_bid: Optional[float] = None
    no_ask: Optional[float] = None
    
    # Execution details
    entry_side: Optional[str] = None  # yes or no
    entry_action: Optional[str] = None  # buy or sell
    entry_price: Optional[float] = None
    entry_quantity: int = 0
    entry_fee: float = 0.0
    canonical_exposure: Optional[str] = None  # +YES or +NO
    
    # Exit information
    exit_reason: Optional[str] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    
    # Settlement
    settlement_value: Optional[float] = None
    settlement_source: Optional[str] = None
    resolved_outcome: Optional[str] = None  # YES or NO
    
    # PnL
    realized_pnl: float = 0.0
    total_fees: float = 0.0
    slippage_cents: float = 0.0
    
    # Metadata
    code_commit: Optional[str] = None
    process_start_time: Optional[datetime] = None
    config_profile_hash: Optional[str] = None
    
    # Analysis fields
    decision_signed_distance: Optional[float] = None
    predicate_match: Optional[bool] = None
    failure_classification: Optional[str] = None


def parse_ticker_info(ticker: str) -> Dict[str, Any]:
    """Extract information from Kalshi ticker format.
    
    Example: KXBTC15M-26AUG081315-15
    - Asset: BTC
    - Timeframe: 15M
    - Date: 26AUG08 (August 8, 2026)
    - Time: 13:15 UTC
    - Window offset: 15 minutes
    """
    info = {
        'asset': None,
        'timeframe': None,
        'date_str': None,
        'time_str': None,
        'window_offset': None
    }
    
    # Extract asset and timeframe
    match = re.match(r'^KX([A-Z]+)(\d+[MH])', ticker)
    if match:
        info['asset'] = match.group(1)
        info['timeframe'] = match.group(2)
    
    # Extract date, time, and window offset
    parts = ticker.split('-')
    if len(parts) >= 3:
        info['date_str'] = parts[1]  # e.g., 26AUG08
        info['time_str'] = parts[2][:4] if len(parts[2]) >= 4 else None  # e.g., 1315
        info['window_offset'] = parts[2][4:] if len(parts[2]) > 4 else None  # e.g., -15
    
    return info


def load_trade_history(csv_path: str) -> List[Dict[str, Any]]:
    """Load trade history from CSV file."""
    trades = []
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
    return trades


def infer_contract_predicate(ticker: str, market_title: Optional[str] = None) -> Optional[str]:
    """Infer contract predicate from ticker or market title.
    
    This is a placeholder - in production, this would come from market metadata.
    """
    # Default assumption for crypto 15m markets
    # Most are "Price above/below target at close"
    if market_title:
        title_lower = market_title.lower()
        if 'above' in title_lower:
            return 'ABOVE'
        elif 'below' in title_lower:
            return 'BELOW'
        elif 'at or above' in title_lower:
            return 'AT_OR_ABOVE'
        elif 'at or below' in title_lower:
            return 'AT_OR_BELOW'
    
    # Fallback: assume ABOVE for crypto markets (common pattern)
    return 'ABOVE'


def calculate_signed_distance(spot_price: float, target_price: float) -> float:
    """Calculate decision-time signed distance.
    
    d = (P_spot - P_target) / P_target
    """
    if target_price == 0:
        return 0.0
    return (spot_price - target_price) / target_price


def classify_failure(record: DecisionRecord) -> str:
    """Classify the failure mode based on decision analysis.
    
    Returns one of:
    - MAPPING_BUG
    - TARGET_OR_PREDICATE_MISMATCH
    - STALE_OR_WRONG_PRICE_SOURCE
    - EXECUTION_TIMING_FAILURE
    - VALID_FORECAST_LOSS
    - INSUFFICIENT_EVIDENCE
    """
    # Check if we have sufficient evidence
    if not all([
        record.strategy_thesis,
        record.contract_predicate,
        record.spot_price_used,
        record.target_price,
        record.resolved_outcome
    ]):
        return 'INSUFFICIENT_EVIDENCE'
    
    # Calculate signed distance
    if record.spot_price_used and record.target_price:
        record.decision_signed_distance = calculate_signed_distance(
            record.spot_price_used, record.target_price
        )
    
    # Check for predicate inversion
    # If the contract is "Price above target" and spot is below target,
    # a NO thesis could be coherent, but we need to verify the strategy's logic
    if record.contract_predicate == 'ABOVE':
        if record.decision_signed_distance < -0.01:  # Spot materially below target
            if record.strategy_thesis == 'NO':
                # This could be coherent - spot below target for ABOVE contract
                # But we need to check if settlement matches
                if record.resolved_outcome == 'YES':
                    # Market resolved YES (price went above target)
                    # Strategy was wrong on direction
                    return 'VALID_FORECAST_LOSS'
                else:
                    # Market resolved NO (price stayed below target)
                    # Strategy was correct
                    return 'VALID_FORECAST_LOSS'  # Still a loss due to other factors
            else:
                # Strategy chose YES when spot was below target for ABOVE contract
                return 'MAPPING_BUG'
    
    elif record.contract_predicate == 'BELOW':
        if record.decision_signed_distance > 0.01:  # Spot materially above target
            if record.strategy_thesis == 'NO':
                # This is incoherent - spot above target for BELOW contract
                # should be YES thesis
                return 'MAPPING_BUG'
            else:
                # Strategy chose YES when spot was above target for BELOW contract
                # This is coherent
                if record.resolved_outcome == 'YES':
                    return 'VALID_FORECAST_LOSS'
                else:
                    return 'VALID_FORECAST_LOSS'
    
    # Check for stale price source
    if record.spot_freshness_ms and record.spot_freshness_ms > 5000:  # > 5 seconds old
        return 'STALE_OR_WRONG_PRICE_SOURCE'
    
    # Default to forecast loss if no clear bug found
    return 'VALID_FORECAST_LOSS'


def build_decision_ledger(trades: List[Dict[str, Any]]) -> List[DecisionRecord]:
    """Build comprehensive decision ledger from trade history."""
    ledger = []
    
    for trade in trades:
        record = DecisionRecord(
            fill_id=trade['fill_id'],
            order_id=trade['order_id'],
            market_ticker=trade['market_ticker'],
            asset=trade['asset'],
            decision_time=datetime.fromisoformat(trade['created_time'].replace('Z', '+00:00')),
            entry_side=trade['side'],
            entry_action=trade['action'],
            entry_price=float(trade['price']),
            entry_quantity=int(trade['quantity']),
            entry_fee=float(trade['fee']),
        )
        
        # Determine canonical exposure
        if record.entry_side == 'yes' and record.entry_action == 'buy':
            record.canonical_exposure = '+YES'
            record.strategy_thesis = 'YES'
        elif record.entry_side == 'no' and record.entry_action == 'buy':
            record.canonical_exposure = '+NO'
            record.strategy_thesis = 'NO'
        elif record.entry_side == 'yes' and record.entry_action == 'sell':
            record.canonical_exposure = '-YES'
            record.strategy_thesis = 'NO'  # Selling YES = NO exposure
        elif record.entry_side == 'no' and record.entry_action == 'sell':
            record.canonical_exposure = '-NO'
            record.strategy_thesis = 'YES'  # Selling NO = YES exposure
        
        # Parse ticker information
        ticker_info = parse_ticker_info(record.market_ticker)
        record.series_ticker = f"KX{ticker_info['asset']}15M"
        
        # Infer contract predicate (placeholder)
        record.contract_predicate = infer_contract_predicate(record.market_ticker)
        
        # Classify failure
        record.failure_classification = classify_failure(record)
        
        ledger.append(record)
    
    return ledger


def main():
    """Main audit function."""
    print("=" * 80)
    print("DECISION AUDIT FOR 15-MINUTE CRYPTO TRADES")
    print("=" * 80)
    
    # Load trade history
    csv_path = 'C:\\Dev\\MERID\\trade_history_7days.csv'
    trades = load_trade_history(csv_path)
    print(f"\nLoaded {len(trades)} trades from {csv_path}")
    
    # Build decision ledger
    ledger = build_decision_ledger(trades)
    print(f"Built decision ledger with {len(ledger)} records")
    
    # Analyze NO exposure trades that may have lost
    no_exposure_trades = [r for r in ledger if r.canonical_exposure == '+NO']
    print(f"\nFound {len(no_exposure_trades)} NO exposure trades")
    
    # Print summary
    print("\n" + "=" * 80)
    print("DECISION LEDGER SUMMARY")
    print("=" * 80)
    
    for record in ledger[:10]:  # Show first 10 for now
        print(f"\nFill ID: {record.fill_id[:12]}...")
        print(f"  Market: {record.market_ticker}")
        print(f"  Asset: {record.asset}")
        print(f"  Decision Time: {record.decision_time}")
        print(f"  Entry: {record.entry_action.upper()} {record.entry_side.upper()} @ {record.entry_price}")
        print(f"  Canonical Exposure: {record.canonical_exposure}")
        print(f"  Strategy Thesis: {record.strategy_thesis}")
        print(f"  Contract Predicate: {record.contract_predicate}")
        print(f"  Failure Classification: {record.failure_classification}")
    
    # Save detailed ledger to JSON
    output_path = 'C:\\Dev\\MERID\\decision_ledger_audit.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump([asdict(r) for r in ledger], f, indent=2, default=str)
    
    print(f"\nDetailed decision ledger saved to {output_path}")
    
    # Print classification summary
    print("\n" + "=" * 80)
    print("FAILURE CLASSIFICATION SUMMARY")
    print("=" * 80)
    
    classification_counts = {}
    for record in ledger:
        cls = record.failure_classification
        classification_counts[cls] = classification_counts.get(cls, 0) + 1
    
    for cls, count in sorted(classification_counts.items()):
        print(f"  {cls}: {count}")
    
    print("\n" + "=" * 80)
    print("AUDIT COMPLETE")
    print("=" * 80)
    print("\nNOTE: This is a preliminary analysis using available CSV data.")
    print("For complete analysis, the following data is needed:")
    print("  1. Market metadata (rules, predicates, strike prices)")
    print("  2. Settlement information for resolved markets")
    print("  3. Strategy decision logs (spot prices, signal scores)")
    print("  4. Underlying price source information")
    print("  5. Intent/metadata from order placement")


if __name__ == '__main__':
    main()
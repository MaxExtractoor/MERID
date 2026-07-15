"""
Test if losing DOGE/XRP trades would be rejected by current guardrails.

Based on actual losing trades from kalshi_fills.db:
- KXXRP15M-26MAY280730-30 at $0.05 (Yes buy) → -100%
- KXDOGE15M-26MAY280730-30 at $0.06 (Yes buy) → -100%
- KXDOGE15M-26MAY280730-30 at $0.08 (Yes buy) → -100%
"""

import sys
sys.path.insert(0, 'c:\\Dev\\MERID')

from merid.prediction.unified_edge import UnifiedEdgeComputer, EdgeResult, ContractState, SpotReference
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

# Simulate a losing DOGE trade at $0.08
# Typical conditions for such a trade:
# - DOGE spot around $0.10
# - Strike at $0.10 (at-the-money)
# - Yes price at $0.08 means market thinks 8% chance of YES
# - This is a deep OTM bet on extreme price movement in 15 minutes

def simulate_doge_losing_trade():
    """Simulate DOGE trade at $0.08 that lost 100%"""
    
    # Create edge result for deep OTM trade
    edge_result = EdgeResult(
        edge=0.05,  # 5% theoretical edge (why the model took it)
        edge_risk_adjusted=0.03,
        edge_slippage_adjusted=0.02,
        edge_fee_adjusted=0.02,
        model_prob=0.08,  # 8% win probability (matches $0.08 price)
        market_implied_prob=0.08,  # Market-implied prob from price
        spot_ref=SpotReference(
            asset="DOGE",
            price_usd=0.10,
            timestamp=datetime.now(timezone.utc),
            source="coinbase",
            is_rti_proxy=True
        ),
        confidence=0.70,
        metadata={
            "asset": "DOGE",
            "strike": 0.10,
            "side": "yes",
            "contract_price_cents": 8.0
        },
        raw_edge_cents=2.0,
        spread_cost_cents=42.0,
        fee_cost_cents=0.02,
        net_edge_cents=2.0,
        dist_abs_pct=0.0,  # Spot at strike (0% distance)
        dist_pct=0.0
    )
    
    # Create contract state
    contract = ContractState(
        ticker="KXDOGE15M-26MAY280730-30",
        yes_price_cents=8.0,
        no_price_cents=92.0,
        mid_cents=50.0,
        spread_cents=84.0,  # Huge spread (92-8)
        time_to_expiry=timedelta(minutes=10),
        orderbook=None  # Would have depth info
    )
    
    return edge_result, contract

def simulate_xrp_losing_trade():
    """Simulate XRP trade at $0.05 that lost 100%"""
    
    edge_result = EdgeResult(
        edge=0.06,  # 6% theoretical edge
        edge_risk_adjusted=0.04,
        edge_slippage_adjusted=0.03,
        edge_fee_adjusted=0.03,
        model_prob=0.05,  # 5% win probability (matches $0.05 price)
        market_implied_prob=0.05,  # Market-implied prob from price
        spot_ref=SpotReference(
            asset="XRP",
            price_usd=1.31,
            timestamp=datetime.now(timezone.utc),
            source="coinbase",
            is_rti_proxy=True
        ),
        confidence=0.70,
        metadata={
            "asset": "XRP",
            "strike": 1.31,
            "side": "yes",
            "contract_price_cents": 5.0
        },
        raw_edge_cents=1.0,
        spread_cost_cents=45.0,
        fee_cost_cents=0.01,
        net_edge_cents=1.0,
        dist_abs_pct=0.0,  # Spot at strike
        dist_pct=0.0
    )
    
    contract = ContractState(
        ticker="KXXRP15M-26MAY280730-30",
        yes_price_cents=5.0,
        no_price_cents=95.0,
        mid_cents=50.0,
        spread_cents=90.0,  # Massive spread
        time_to_expiry=timedelta(minutes=10),
        orderbook=None
    )
    
    return edge_result, contract

if __name__ == "__main__":
    computer = UnifiedEdgeComputer()
    
    print("=" * 80)
    print("Testing DOGE losing trade at $0.08")
    print("=" * 80)
    doge_edge, doge_contract = simulate_doge_losing_trade()
    doge_result = computer.check_edge(doge_edge, doge_contract, vol_regime="NORMAL")
    print(f"Result: {doge_result}")
    print(f"Passes: {doge_result.passes}")
    print(f"Reason: {doge_result.reason}")
    
    print("\n" + "=" * 80)
    print("Testing XRP losing trade at $0.05")
    print("=" * 80)
    xrp_edge, xrp_contract = simulate_xrp_losing_trade()
    xrp_result = computer.check_edge(xrp_edge, xrp_contract, vol_regime="NORMAL")
    print(f"Result: {xrp_result}")
    print(f"Passes: {xrp_result.passes}")
    print(f"Reason: {xrp_result.reason}")
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    if doge_result.passes or xrp_result.passes:
        print("WARNING: Losing trades would PASS current guardrails!")
        print("This confirms the guardrails need tightening.")
        print("\nCurrent guardrails_max_dist_pct_trade: 2.0%")
        print("Current max_spread_cents: 40")
        print("Missing: Minimum contract price floor (e.g., $0.20)")
    else:
        print("OK: Losing trades would be rejected by current guardrails.")

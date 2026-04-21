#!/usr/bin/env python3
"""
MERID Paper Trading Demo

A minimal, self-contained demo showing the paper trading flow.
No external API keys required - uses internal simulation engine.

Usage:
    python scripts/run_paper_demo.py
    
    # Or with make:
    make run-paper-demo
"""

import asyncio
import sys
import os
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import get_logger

logger = get_logger("paper_demo")


def run_demo():
    """Run paper trading demo with mode controller and paper engine."""
    print("\n" + "=" * 60)
    print("MERID Paper Trading Demo")
    print("=" * 60 + "\n")
    
    # 1. Initialize mode controller in PAPER mode
    print("[1/5] Initializing mode controller...")
    from trading.mode_controller import get_trading_mode_controller, TradingMode
    
    controller = get_trading_mode_controller()
    controller.set_mode("paper", changed_by="demo_script", reason="Demo initialization")
    
    print(f"  Mode: {controller.mode_name}")
    print(f"  Is Paper: {controller.is_paper}")
    print(f"  Is Live: {controller.is_live}")
    
    # 2. Initialize paper trading engine
    print("\n[2/5] Initializing paper trading engine...")
    from trading.paper_trading import get_paper_engine
    
    engine = get_paper_engine()
    print(f"  Starting balance: ${engine.starting_balance:,.2f}")
    print(f"  Active portfolios: {len(engine.portfolios)}")
    
    # 3. Simulate some prices (in real usage, these come from live feeds)
    print("\n[3/5] Setting up simulated prices...")
    simulated_prices = {
        "BTC/USD": 67500.0,
        "ETH/USD": 3450.0,
        "SOL/USD": 145.0,
        "BTC": 67500.0,
        "ETH": 3450.0,
        "SOL": 145.0,
    }
    engine.update_prices(simulated_prices)
    print(f"  Loaded {len(simulated_prices)} price points")
    
    # 4. Place demo trades
    print("\n[4/5] Placing demo trades...")
    demo_user = "demo_trader"
    
    trades = [
        {"asset": "BTC", "side": "long", "size_usd": 1000.0, "leverage": 2},
        {"asset": "ETH", "side": "long", "size_usd": 500.0, "leverage": 1},
        {"asset": "SOL", "side": "short", "size_usd": 200.0, "leverage": 3},
    ]
    
    for trade in trades:
        order = engine.place_order(
            user_id=demo_user,
            asset=trade["asset"],
            side=trade["side"],
            size_usd=trade["size_usd"],
            leverage=trade["leverage"],
        )
        print(f"  {trade['side'].upper()} {trade['asset']}: "
              f"${trade['size_usd']:.0f} @ {trade['leverage']}x -> {order.status.value}")
    
    # 5. Show portfolio stats
    print("\n[5/5] Portfolio summary...")
    stats = engine.get_portfolio_stats(demo_user)
    
    print(f"\n  {'─' * 40}")
    print(f"  User: {stats['user_id']}")
    print(f"  Starting Balance: ${stats['starting_balance']:,.2f}")
    print(f"  Current Balance:  ${stats['current_balance']:,.2f}")
    print(f"  Total Position:   ${stats['total_position_value']:,.2f}")
    print(f"  Unrealized P&L:   ${stats['total_unrealized_pnl']:,.2f}")
    print(f"  Equity:           ${stats['equity']:,.2f}")
    print(f"  ROI:              {stats['roi_pct']:.2f}%")
    print(f"  Open Positions:   {stats['open_positions']}")
    print(f"  Total Trades:     {stats['total_trades']}")
    print(f"  {'─' * 40}")
    
    # Simulate price movement
    print("\n[Bonus] Simulating 5% BTC price increase...")
    simulated_prices["BTC/USD"] = 70875.0  # +5%
    simulated_prices["BTC"] = 70875.0
    engine.update_prices(simulated_prices)
    
    updated_stats = engine.get_portfolio_stats(demo_user)
    print(f"  New Unrealized P&L: ${updated_stats['total_unrealized_pnl']:,.2f}")
    print(f"  New Equity:         ${updated_stats['equity']:,.2f}")
    print(f"  New ROI:            {updated_stats['roi_pct']:.2f}%")
    
    # Show global stats
    print("\n[Global Stats]")
    global_stats = engine.get_global_stats()
    print(f"  Active Accounts:    {global_stats['accounts']}")
    print(f"  Total Equity:       ${global_stats['equity']:,.2f}")
    print(f"  Active Positions:   {global_stats['active_positions']}")
    
    print("\n" + "=" * 60)
    print("Demo complete! Paper trading is ready for use.")
    print("=" * 60 + "\n")
    
    return True


def main():
    """Entry point."""
    try:
        success = run_demo()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nDemo interrupted.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Demo failed")
        print(f"\n❌ Demo failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

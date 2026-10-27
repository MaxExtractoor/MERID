#!/usr/bin/env python3
"""
MERID Capital Bracket Promotion Checker
Run weekly to determine if ready to scale up risk parameters.
"""

import sqlite3
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Configuration
DATA_DIR = Path(os.getenv("MERID_DATA_DIR", "data"))
TRADE_AUDIT = DATA_DIR / "trade_audit.jsonl"
FILLS_DB = DATA_DIR / "kalshi_fills.db"
REQUIRED_TRADES = 100
REQUIRED_WIN_RATE = 0.55
MAX_DRAWDOWN_PCT = 10.0
MIN_DAYS_SINCE_KILL = 30


def get_recent_fills(limit: int = 100) -> list:
    """Get last N fills from database."""
    if not FILLS_DB.exists():
        print(f"❌ Fill database not found: {FILLS_DB}")
        return []
    
    try:
        conn = sqlite3.connect(FILLS_DB)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pnl_cents, fee_cents, timestamp FROM fills ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        print(f"❌ Database error: {e}")
        return []


def calculate_metrics(fills: list) -> dict:
    """Calculate trading metrics from fills."""
    if not fills or len(fills) < REQUIRED_TRADES:
        return {"error": f"Need {REQUIRED_TRADES} trades, have {len(fills) if fills else 0}"}
    
    # Net PnL (after fees)
    net_pnls = [(pnl - fee) for pnl, fee, _ in fills]
    wins = sum(1 for pnl in net_pnls if pnl > 0)
    losses = sum(1 for pnl in net_pnls if pnl <= 0)
    
    win_rate = wins / len(fills)
    total_pnl = sum(net_pnls)
    avg_trade = total_pnl / len(fills)
    
    # Calculate drawdown
    peak = 0
    max_drawdown = 0
    running_pnl = 0
    
    for pnl in reversed(net_pnls):  # Chronological order
        running_pnl += pnl
        if running_pnl > peak:
            peak = running_pnl
        drawdown = peak - running_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown
    
    # Calculate Sharpe-ish metric (simplified)
    if len(net_pnls) > 1:
        mean = sum(net_pnls) / len(net_pnls)
        variance = sum((x - mean) ** 2 for x in net_pnls) / len(net_pnls)
        std_dev = variance ** 0.5
        sharpe = mean / std_dev if std_dev > 0 else 0
    else:
        sharpe = 0
    
    return {
        "trades": len(fills),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "total_pnl_cents": total_pnl,
        "avg_trade_cents": avg_trade,
        "max_drawdown_cents": max_drawdown,
        "sharpe": sharpe,
    }


def count_recent_kill_switches(days: int = 30) -> int:
    """Count kill switch events in last N days."""
    if not TRADE_AUDIT.exists():
        return 0
    
    cutoff = datetime.now() - timedelta(days=days)
    count = 0
    
    try:
        with open(TRADE_AUDIT, 'r') as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    if 'kill_switch' in str(event.get('event_type', '')).lower():
                        event_time = datetime.fromtimestamp(event.get('timestamp', 0))
                        if event_time > cutoff:
                            count += 1
                except (json.JSONDecodeError, ValueError):
                    continue
    except Exception as e:
        print(f"⚠️  Error reading trade audit: {e}")
    
    return count


def get_current_bankroll() -> int:
    """Get current bankroll from session state."""
    session_file = DATA_DIR / "paper_session_state.json"
    if not session_file.exists():
        return 1400  # Default starting bankroll in cents ($14.00 - calibrated)
    
    try:
        with open(session_file) as f:
            data = json.load(f)
            # Find first interval with non-zero bankroll
            for interval in data.get("intervals", {}).values():
                if interval.get("high_water_mark_cents", 0) > 0:
                    return int(interval["high_water_mark_cents"])
    except Exception:
        pass
    
    return 574


def determine_bracket(bankroll_cents: int) -> str:
    """Determine current capital bracket."""
    bankroll_dollars = bankroll_cents / 100
    
    if bankroll_dollars < 100:
        return "Sandbox ($5-$100)"
    elif bankroll_dollars < 500:
        return "Pilot ($100-$500)"
    elif bankroll_dollars < 2000:
        return "Growth ($500-$2k)"
    elif bankroll_dollars < 10000:
        return "Scale ($2k-$10k)"
    elif bankroll_dollars < 50000:
        return "Pro ($10k-$50k)"
    else:
        return "Wealth ($50k+)"


def main():
    print("=" * 60)
    print("MERID Capital Bracket Promotion Check")
    print("=" * 60)
    print()
    
    # 1. Get current bankroll
    bankroll_cents = get_current_bankroll()
    bankroll_dollars = bankroll_cents / 100
    current_bracket = determine_bracket(bankroll_cents)
    
    print(f"💰 Current Bankroll: ${bankroll_dollars:.2f}")
    print(f"📊 Current Bracket: {current_bracket}")
    print()
    
    # 2. Get fills and calculate metrics
    fills = get_recent_fills(REQUIRED_TRADES)
    metrics = calculate_metrics(fills)
    
    if "error" in metrics:
        print(f"⏳ {metrics['error']}")
        print("Keep trading. Check again when you have more data.")
        sys.exit(0)
    
    # 3. Display metrics
    print("📈 Performance Metrics (Last 100 Trades)")
    print("-" * 40)
    print(f"Win Rate:       {metrics['win_rate']:.1%} (target: {REQUIRED_WIN_RATE:.0%})")
    print(f"Total PnL:      ${metrics['total_pnl_cents']/100:.2f}")
    print(f"Avg Trade:      ${metrics['avg_trade_cents']/100:.2f}")
    print(f"Max Drawdown:   ${metrics['max_drawdown_cents']/100:.2f}")
    print(f"Sharpe Ratio:   {metrics['sharpe']:.2f}")
    print()
    
    # 4. Check kill switches
    recent_kills = count_recent_kill_switches(MIN_DAYS_SINCE_KILL)
    print(f"🚨 Kill Switches (30 days): {recent_kills} (max: 0)")
    print()
    
    # 5. Evaluate promotion criteria
    print("✅ Promotion Criteria Check")
    print("-" * 40)
    
    checks = {
        "Trades ≥ 100": metrics['trades'] >= REQUIRED_TRADES,
        f"Win Rate ≥ {REQUIRED_WIN_RATE:.0%}": metrics['win_rate'] >= REQUIRED_WIN_RATE,
        f"Drawdown ≤ {MAX_DRAWDOWN_PCT}%": (metrics['max_drawdown_cents'] / bankroll_cents * 100) <= MAX_DRAWDOWN_PCT,
        "No recent kills": recent_kills == 0,
        "Positive PnL": metrics['total_pnl_cents'] > 0,
    }
    
    all_passed = True
    for criterion, passed in checks.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {criterion}")
        if not passed:
            all_passed = False
    
    print()
    print("=" * 60)
    
    if all_passed:
        print("🎉 READY FOR PROMOTION!")
        print()
        print("Next steps:")
        print("1. Review your risk tolerance")
        print("2. Update KELLY_FRACTION in your environment")
        print("3. Gradually increase position sizes")
        print("4. Monitor closely for first 2 weeks")
        sys.exit(0)
    else:
        print("⏳ Stay in current bracket")
        print()
        print("Keep proving the edge. Check again in 1 week.")
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Live Trading Readiness Check for AgentGrid

Usage:
    python scripts/check_live_readiness.py

Checks:
1. VenueGate mode and live_enabled flag
2. AgentGrid agent modes and enabled states
3. PortfolioRiskAgent halted status
4. Current balance and max exposure
5. Min edge thresholds from strategy catalog
6. Sample sizing test (would a hypothetical trade get size > 0?)
"""

import asyncio
import sys
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, "/home/runner/work/MERID/MERID")


def check_venue_gate():
    """Check VenueGate mode and live_enabled flag."""
    print("\n" + "=" * 80)
    print("1. VenueGate Mode Check")
    print("=" * 80)

    from merid.prediction.venue_gate import get_venue_gate

    gate = get_venue_gate()
    print(f"  Mode: {gate.mode.value}")
    print(f"  Live Enabled: {gate.live_enabled}")
    print(f"  Is Live: {gate.is_live}")

    if gate.mode.value == "mock":
        print("  ⚠️  WARNING: Mode is MOCK — no orders will be submitted")
        print("     Set MERID_PM_TRADING_MODE=live or paper to enable trading")
        return False
    elif gate.mode.value == "live" and not gate.live_enabled:
        print("  ⚠️  WARNING: Mode is LIVE but live_enabled=false")
        print("     Set MERID_PM_LIVE_ENABLED=true to allow live orders")
        return False
    else:
        print(f"  ✓ VenueGate configured for trading (mode={gate.mode.value})")
        return True


def check_agent_grid():
    """Check AgentGrid agents and their states."""
    print("\n" + "=" * 80)
    print("2. AgentGrid Agent Status")
    print("=" * 80)

    from merid.prediction.agent_grid import get_agent_grid

    grid = get_agent_grid()
    agents = grid.agents

    print(f"  Total agents: {len(agents)}")

    enabled_count = sum(1 for a in agents if a.state.enabled)
    disabled_count = len(agents) - enabled_count

    print(f"  Enabled: {enabled_count}")
    print(f"  Disabled: {disabled_count}")

    if enabled_count == 0:
        print("  ⚠️  WARNING: All agents are disabled — no trading will occur")
        return False

    print(f"\n  Enabled agents by asset/timeframe:")
    for agent in agents:
        if agent.state.enabled:
            asset = agent.config.assets[0] if agent.config.assets else "?"
            tf = agent.config.timeframes[0] if agent.config.timeframes else "?"
            print(f"    - {agent.config.name}: {asset}/{tf}")

    return True


def check_portfolio_risk():
    """Check PortfolioRiskAgent status."""
    print("\n" + "=" * 80)
    print("3. Portfolio Risk Agent")
    print("=" * 80)

    from merid.prediction.agent_grid import get_agent_grid

    grid = get_agent_grid()
    portfolio_risk = grid._portfolio_risk

    print(f"  Halted: {portfolio_risk._halted}")
    if portfolio_risk._halted:
        print(f"  Halt Reason: {portfolio_risk._halt_reason}")
        print("  ⚠️  WARNING: Portfolio risk is halted — no trading will occur")
        return False
    else:
        print("  ✓ Portfolio risk is active (not halted)")
        return True


async def check_balance_and_exposure():
    """Check current balance and max exposure."""
    print("\n" + "=" * 80)
    print("4. Balance and Exposure")
    print("=" * 80)

    try:
        from merid.prediction.kalshi_tools import _kalshi_get_balance

        bal_result = await _kalshi_get_balance()
        if bal_result.success:
            available = bal_result.payload.get("available_usd", 0)
            locked = bal_result.payload.get("locked_usd", 0)
            total = Decimal(str(available)) + Decimal(str(locked))
            print(f"  Available Balance: ${available}")
            print(f"  Locked Balance: ${locked}")
            print(f"  Total Balance: ${total}")

            if total < 100:
                print("  ⚠️  WARNING: Total balance < $100 — may limit trading")
                return False
            else:
                print(f"  ✓ Sufficient balance for trading")
                return True
        else:
            print(f"  ⚠️  Could not fetch balance: {bal_result.error}")
            return False
    except Exception as exc:
        print(f"  ⚠️  Error fetching balance: {exc}")
        return False


def check_strategy_catalog():
    """Check min edge thresholds from strategy catalog."""
    print("\n" + "=" * 80)
    print("5. Strategy Catalog Min Edge Thresholds")
    print("=" * 80)

    try:
        from merid.trading.strategy_registry import load_strategy_catalog

        catalog = load_strategy_catalog()

        print("  Enabled cells with min_edge thresholds:\n")
        high_edge_cells = []

        for asset_name, asset_data in catalog.get("assets", {}).items():
            if not isinstance(asset_data, dict):
                continue
            for tf_name, tf_data in asset_data.items():
                if tf_name in ("tier", "notes"):
                    continue
                if not isinstance(tf_data, dict):
                    continue

                enabled = tf_data.get("enabled", False)
                min_edge_bps = tf_data.get("min_edge_bps", 0)

                if enabled:
                    edge_pct = min_edge_bps / 100.0
                    print(f"    {asset_name:6s} {tf_name:8s} : {min_edge_bps:4d} bps ({edge_pct:.1f}%)")

                    if min_edge_bps > 800:
                        high_edge_cells.append(f"{asset_name}/{tf_name}: {min_edge_bps}bps")

        if high_edge_cells:
            print(f"\n  ⚠️  WARNING: {len(high_edge_cells)} cells have min_edge > 8%:")
            for cell in high_edge_cells:
                print(f"      - {cell}")
            print("     Typical realistic edges are 0.5-6%. High thresholds may prevent all trades.")
            return False
        else:
            print("\n  ✓ All min_edge thresholds are realistic (<= 8%)")
            return True

    except Exception as exc:
        print(f"  ⚠️  Error loading strategy catalog: {exc}")
        return False


def test_hypothetical_sizing():
    """Test if a hypothetical trade would get size > 0."""
    print("\n" + "=" * 80)
    print("6. Hypothetical Sizing Test")
    print("=" * 80)

    try:
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig

        # Create a risk engine with default config
        risk = PredictionMarketRisk()

        # Test hypothetical order: BTC market, 10 contracts at 50c, 5% edge
        check = risk.check_order(
            market_id="TEST-BTC-MARKET",
            event_id="TEST-BTC-EVENT",
            side="yes",
            contracts=10,
            price_cents=Decimal("50"),
            edge=Decimal("0.05"),
        )

        print(f"  Test Order: 10 contracts @ 50¢, edge=5%")
        print(f"  Allowed: {check.allowed}")
        print(f"  Action: {check.action.value}")
        print(f"  Reason: {check.reason}")

        if check.allowed:
            print("  ✓ Hypothetical order would be allowed")
            return True
        else:
            print("  ⚠️  WARNING: Hypothetical order would be blocked")
            return False

    except Exception as exc:
        print(f"  ⚠️  Error testing hypothetical sizing: {exc}")
        return False


async def main():
    """Run all readiness checks."""
    print("\n" + "=" * 80)
    print("AgentGrid Live Trading Readiness Check")
    print("=" * 80)

    results = []

    # Run checks
    results.append(("VenueGate Mode", check_venue_gate()))
    results.append(("AgentGrid Agents", check_agent_grid()))
    results.append(("Portfolio Risk", check_portfolio_risk()))
    results.append(("Balance & Exposure", await check_balance_and_exposure()))
    results.append(("Strategy Catalog", check_strategy_catalog()))
    results.append(("Hypothetical Sizing", test_hypothetical_sizing()))

    # Summary
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for check_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status:10s} {check_name}")

    print(f"\nPassed: {passed}/{total}")

    if passed == total:
        print("\n✅ All checks passed — AgentGrid is ready for live trading")
        sys.exit(0)
    else:
        print("\n⚠️  Some checks failed — review issues above before expecting live trades")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

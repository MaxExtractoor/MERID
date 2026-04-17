#!/usr/bin/env python
"""Quick syntax/import test for modified files."""

try:
    from merid.event_venues.kalshi.take_profit import TakeProfitManager, TakeProfitConfig
    print("take_profit.py: OK")
except Exception as e:
    print(f"take_profit.py: FAIL - {e}")

try:
    from merid.event_venues.kalshi.maker_taker_policy import MakerTakerPolicyEngine, decide_tp_exit_role
    print("maker_taker_policy.py: OK")
except Exception as e:
    print(f"maker_taker_policy.py: FAIL - {e}")

try:
    # Can't fully import trading_agent due to many dependencies
    # Just check syntax
    import ast
    with open('merid/prediction/trading_agent.py', encoding='utf-8') as f:
        ast.parse(f.read())
    print("trading_agent.py: OK (syntax)")
except Exception as e:
    print(f"trading_agent.py: FAIL - {e}")

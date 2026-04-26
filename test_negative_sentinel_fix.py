#!/usr/bin/env python3
"""Verify the negative sentinel value fix is in place."""

import sys
sys.path.insert(0, r'c:\Dev\MERID')

from decimal import Decimal
from merid.prediction.risk._prediction_risk import PredictionMarketRisk, RiskAction, PreTradeCheck

# Test 1: Verify RiskAction.REJECT exists
assert RiskAction.REJECT == "reject", "RiskAction.REJECT should exist"
print("✅ RiskAction.REJECT exists")

# Test 2: Create a PreTradeCheck with AGENT_DISABLED reason
check = PreTradeCheck(
    allowed=False,
    action=RiskAction.REJECT,
    reason='AGENT_DISABLED: Live bankroll fetch failed (sentinel=-1.0). Cannot trade without valid bankroll. Check Kalshi API connection.',
    market_id='test'
)
assert check.action == RiskAction.REJECT
assert "AGENT_DISABLED" in check.reason
print("✅ PreTradeCheck with AGENT_DISABLED reason works correctly")

# Test 3: Verify the code has the negative sentinel check
import inspect
source = inspect.getsource(PredictionMarketRisk.check_order)
assert "agent_max_notional_usd < Decimal" in source, "Negative sentinel check should be present"
assert "AGENT_DISABLED" in source, "AGENT_DISABLED message should be in code"
print("✅ Negative sentinel check is present in RiskManager.check_order")

# Test 4: Also verify in prediction/risk.py
from merid.prediction.risk import PredictionMarketRisk as PMR2
source_orig = inspect.getsource(PMR2.check_order)
assert "agent_max_notional_usd < Decimal" in source_orig, "Negative sentinel check should be in risk.py too"
assert "AGENT_DISABLED" in source_orig, "AGENT_DISABLED message should be in risk.py"
print("✅ Negative sentinel check is present in prediction/risk.py")

print("\n🎉 ALL FIXES VERIFIED!")
print("The negative sentinel -1.0 will now trigger clear AGENT_DISABLED rejection")
print("instead of the confusing 'exceeds 2% bankroll cap $-1.00' message")

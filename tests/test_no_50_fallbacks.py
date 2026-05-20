"""
These tests enforce a strict policy: **no code path in production may assign 0.5/50 as a price or probability default**.
Any reintroduction of such fallbacks must fail CI. This is a non-optional invariant.
"""

from pathlib import Path


def test_no_50_fallback_in_removed_locations():
    """Check that the specific fallbacks we removed are not reintroduced.
    
    This test is surgical - it only checks the specific locations where we removed fallbacks:
    - trading_agent.py: price_cents = 50 fallback
    - kalshi_api.py: yes_price fallback to 0.5
    - risk.py: _effective_price_cents = Decimal("50")
    - paper_trading.py: current_price = order.price or 0.5
    - augur_trading_layer.py: yes_price if yes_price is not None else 0.5
    - prediction.py: yes_price: float = 0.5
    """
    violations = []
    
    # Check trading_agent.py for price_cents = 50 fallback
    trading_agent = Path("merid/prediction/trading_agent.py")
    if trading_agent.exists():
        source = trading_agent.read_text(encoding="utf-8")
        # Check for the actual fallback pattern we removed (assignment without error logging)
        # The old pattern was: price_cents = 50  # Fallback to 50 cents
        if "price_cents = 50  # Fallback to 50 cents" in source:
            violations.append("trading_agent.py: price_cents = 50 fallback reintroduced")
        if "price_cents = 50  # Fallback if market state not found" in source:
            violations.append("trading_agent.py: price_cents = 50 fallback reintroduced")
        if "price_cents = 50  # Fallback to 50 cents on error" in source:
            violations.append("trading_agent.py: price_cents = 50 fallback reintroduced")
    
    # Check kalshi_api.py for yes_price = 0.5 fallback
    kalshi_api = Path("web/api/kalshi_api.py")
    if kalshi_api.exists():
        source = kalshi_api.read_text(encoding="utf-8")
        # Check for the specific pattern we removed
        if 'yes_price / 100.0 if yes_price else 0.5' in source:
            violations.append("kalshi_api.py: yes_price fallback to 0.5 reintroduced")
        if '(100 - yes_price) / 100.0 if yes_price else 0.5' in source:
            violations.append("kalshi_api.py: no_price fallback to 0.5 reintroduced")
    
    # Check risk.py for _effective_price_cents = Decimal("50")
    risk_py = Path("merid/prediction/risk.py")
    if risk_py.exists():
        source = risk_py.read_text(encoding="utf-8")
        if '_effective_price_cents = price_cents if price_cents > 0 else Decimal("50")' in source:
            violations.append("risk.py: price_cents fallback to 50 reintroduced")
    
    # Check paper_trading.py for current_price = order.price or 0.5
    paper_trading = Path("trading/paper_trading.py")
    if paper_trading.exists():
        source = paper_trading.read_text(encoding="utf-8")
        if "current_price = order.price or 0.5" in source:
            violations.append("paper_trading.py: price fallback to 0.5 reintroduced")
    
    # Check augur_trading_layer.py for yes_price if yes_price is not None else 0.5
    augur = Path("trading/augur_trading_layer.py")
    if augur.exists():
        source = augur.read_text(encoding="utf-8")
        if 'yes_price if yes_price is not None else 0.5' in source:
            violations.append("augur_trading_layer.py: yes_price fallback to 0.5 reintroduced")
    
    # Check prediction.py for yes_price: float = 0.5
    prediction = Path("web/api/prediction.py")
    if prediction.exists():
        source = prediction.read_text(encoding="utf-8")
        if "yes_price: float = 0.5" in source and "REMOVED" not in source:
            violations.append("prediction.py: yes_price default = 0.5 reintroduced")
    
    assert not violations, "Found reintroduced fallbacks:\n" + "\n".join(violations)

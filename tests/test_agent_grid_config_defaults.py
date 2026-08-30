"""Test sizing/risk defaults are not stale.

per_trade_risk_pct has moved from the deprecated agent_grid_config.py loader to
merid.risk.profiles.kalshi_crypto_15m_risk_envelope.py (the canonical risk
envelope).  These tests verify the canonical default is 0.03 (3%) and that no
stale 2% default remains in either source.
"""

import pytest
import inspect
from pathlib import Path


def test_risk_envelope_per_trade_risk_default_is_3_percent():
    """Canonical risk envelope uses 0.03 default for per_trade_risk_pct."""
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope

    source = inspect.getsource(compute_kalshi_crypto_15m_risk_envelope)

    # Assert on the actual code default, not a comment.
    assert "guardrails.get('per_trade_risk_pct', 0.03)" in source or \
           "per_trade_risk_pct_raw = guardrails.get('per_trade_risk_pct', 0.03)" in source, \
        "Canonical risk envelope default for per_trade_risk_pct must be 0.03 (3%)"

    # No 2% default should remain in the canonical sizing path.
    for i, line in enumerate(source.split("\n")):
        if "per_trade_risk_pct" in line and "0.02" in line and "was 0.02" not in line:
            pytest.fail(f"Line {i + 1} has stale 0.02 default for per_trade_risk_pct: {line}")


def test_profile_per_trade_risk_pct_disabled_or_3_percent():
    """Profile does not reintroduce a stale 2% per_trade_risk_pct."""
    profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
    content = profile_path.read_text(encoding="utf-8")

    # The field is intentionally disabled/removed in favor of fixed $2 exposure.
    # If it is present, it must not be 0.02; 0.03 is the only acceptable code default.
    for i, line in enumerate(content.split("\n")):
        if "per_trade_risk_pct" in line.lower():
            if "0.02" in line and "was 0.02" not in line:
                pytest.fail(f"Line {i + 1} has stale 0.02 per_trade_risk_pct in profile: {line}")


def test_agent_grid_config_no_stale_2_percent_default():
    """Deprecated agent_grid_config.py must not contain a stale 2% per_trade_risk_pct default."""
    config_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_config.py"
    content = config_path.read_text(encoding="utf-8")

    for i, line in enumerate(content.split("\n")):
        # Skip explanatory comments
        if line.strip().startswith("#"):
            continue
        if "per_trade_risk_pct" in line.lower() and "0.02" in line and "was 0.02" not in line:
            pytest.fail(f"Line {i + 1} has stale 0.02 per_trade_risk_pct in agent_grid_config: {line}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

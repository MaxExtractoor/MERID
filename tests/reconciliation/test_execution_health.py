"""Unified execution health snapshot."""

from merid.reconciliation.execution_health import assess_execution_health


def test_assess_execution_health_returns_dataclass():
    h = assess_execution_health(kalshi_demo_mode=False)
    assert hasattr(h, "paper_reconciliation_blocks")
    assert hasattr(h, "kalshi_venue_blocks")
    assert hasattr(h, "source_divergence")
    d = h.to_dict()
    assert "paper_reconciliation_blocks" in d

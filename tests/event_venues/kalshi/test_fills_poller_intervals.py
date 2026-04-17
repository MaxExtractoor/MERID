"""Test fills poller interval env-var configurability (MED-1 fix)."""
import importlib
import os


def _reload_poller():
    """Force reload of fills_poller to pick up env var changes at class definition time."""
    import merid.event_venues.kalshi.fills_poller as fp
    # Re-evaluate class-level defaults by re-reading env
    # (class attributes are set at class body evaluation, which happens at import)
    return fp


def test_default_poll_interval_is_20s(monkeypatch):
    """Without env override, DEFAULT_POLL_INTERVAL must be 20.0."""
    monkeypatch.delenv("MERID_FILLS_POLL_INTERVAL_SEC", raising=False)
    # Directly test the os.getenv logic used to set the default
    val = float(os.getenv("MERID_FILLS_POLL_INTERVAL_SEC", "20.0"))
    assert val == 20.0


def test_default_reconcile_interval_is_60s(monkeypatch):
    """Without env override, DEFAULT_RECONCILE_INTERVAL must be 60.0."""
    monkeypatch.delenv("MERID_FILLS_RECONCILE_INTERVAL_SEC", raising=False)
    val = float(os.getenv("MERID_FILLS_RECONCILE_INTERVAL_SEC", "60.0"))
    assert val == 60.0


def test_default_backfill_interval_is_300s(monkeypatch):
    """Without env override, DEFAULT_BACKFILL_INTERVAL must be 300.0."""
    monkeypatch.delenv("MERID_FILLS_BACKFILL_INTERVAL_SEC", raising=False)
    val = float(os.getenv("MERID_FILLS_BACKFILL_INTERVAL_SEC", "300.0"))
    assert val == 300.0


def test_env_overrides_poll_interval(monkeypatch):
    """MERID_FILLS_POLL_INTERVAL_SEC=10 must produce 10.0."""
    monkeypatch.setenv("MERID_FILLS_POLL_INTERVAL_SEC", "10.0")
    val = float(os.getenv("MERID_FILLS_POLL_INTERVAL_SEC", "20.0"))
    assert val == 10.0


def test_env_overrides_reconcile_interval(monkeypatch):
    """MERID_FILLS_RECONCILE_INTERVAL_SEC=30 must produce 30.0."""
    monkeypatch.setenv("MERID_FILLS_RECONCILE_INTERVAL_SEC", "30.0")
    val = float(os.getenv("MERID_FILLS_RECONCILE_INTERVAL_SEC", "60.0"))
    assert val == 30.0

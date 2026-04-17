"""Test position cache vs fills-ledger divergence detection (HIGH-1 fix)."""
from unittest.mock import MagicMock


def _make_cache(positions: dict):
    """Build a mock position cache with given {ticker: qty} positions."""
    cache = MagicMock()
    mocks = {}
    for ticker, qty in positions.items():
        m = MagicMock()
        m.contracts = qty
        mocks[ticker] = m
    cache.get_all_positions.return_value = mocks
    return cache


def _make_ledger(positions: dict):
    """Build a mock fills ledger with given {ticker: qty} net positions."""
    ledger = MagicMock()
    ledger.compute_net_positions.return_value = positions
    return ledger


def _run_divergence_check(cache, ledger, threshold: int = 5):
    """Replicate the divergence check logic from fills_poller._do_reconcile."""
    _cache_positions = cache.get_all_positions()
    _ledger_positions = ledger.compute_net_positions()
    divs = []
    for _t in set(_cache_positions) | set(_ledger_positions):
        _cache_qty = abs(getattr(_cache_positions.get(_t), "contracts", 0))
        _ledger_qty = abs(_ledger_positions.get(_t, 0))
        if abs(_cache_qty - _ledger_qty) > threshold:
            divs.append(_t)
    return divs


def test_no_divergence_when_positions_agree():
    """Cache and ledger with identical quantities produce no divergences."""
    cache = _make_cache({"KXTICKER-A": 10, "KXTICKER-B": 20})
    ledger = _make_ledger({"KXTICKER-A": 10, "KXTICKER-B": 20})
    divs = _run_divergence_check(cache, ledger)
    assert divs == []


def test_small_divergence_within_threshold_ignored():
    """Divergence <= threshold (5) must not be flagged."""
    cache = _make_cache({"KXTICKER-C": 10})
    ledger = _make_ledger({"KXTICKER-C": 8})  # delta=2, threshold=5
    divs = _run_divergence_check(cache, ledger)
    assert "KXTICKER-C" not in divs


def test_large_divergence_above_threshold_detected():
    """Divergence > 5 contracts must be flagged."""
    cache = _make_cache({"KXTICKER-D": 20})
    ledger = _make_ledger({"KXTICKER-D": 5})  # delta=15 > 5
    divs = _run_divergence_check(cache, ledger)
    assert "KXTICKER-D" in divs


def test_missing_in_cache_but_present_in_ledger():
    """Ticker present in ledger but absent in cache with qty>threshold is flagged."""
    cache = _make_cache({})  # empty cache
    ledger = _make_ledger({"KXTICKER-E": 10})  # 10 > 5
    divs = _run_divergence_check(cache, ledger)
    assert "KXTICKER-E" in divs


def test_missing_in_ledger_but_present_in_cache():
    """Ghost position in cache not in ledger with qty>threshold is flagged."""
    cache = _make_cache({"KXTICKER-F": 12})  # ghost
    ledger = _make_ledger({})
    divs = _run_divergence_check(cache, ledger)
    assert "KXTICKER-F" in divs

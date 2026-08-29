# tests/test_balance_calibrator.py  (create new file)
import pytest
from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig, KalshiRiskManager


def _make_manager(**kwargs) -> KalshiRiskManager:
    return KalshiRiskManager(KalshiRiskConfig(**kwargs))


def test_calibrate_sets_total_notional():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)          # $5 000 balance
    # default max_total_notional_pct = 0.80 → $4 000
    assert mgr.config.max_total_notional_usd == pytest.approx(4000.0)


def test_calibrate_sets_daily_loss():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)          # $5 000
    # default max_daily_loss_pct = 0.10 → $500
    assert mgr.config.max_daily_loss_usd == pytest.approx(500.0)


def test_calibrate_sets_single_order_notional():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)
    # default max_single_order_pct = 0.05 → $250
    assert mgr.config.max_single_order_notional_usd == pytest.approx(250.0)


def test_calibrate_sets_category_limit():
    mgr = _make_manager()
    mgr.calibrate_from_balance(500_000)
    # default crypto pct = 0.30 → $1 500
    crypto_limit = mgr.config.category_limits["crypto"]
    assert crypto_limit.max_notional_usd == pytest.approx(1500.0)


def test_calibrate_zero_balance_is_noop():
    mgr = _make_manager()
    original = mgr.config.max_total_notional_usd
    mgr.calibrate_from_balance(0)
    assert mgr.config.max_total_notional_usd == original


def test_calibrate_negative_balance_is_noop():
    mgr = _make_manager()
    original = mgr.config.max_total_notional_usd
    mgr.calibrate_from_balance(-1)
    assert mgr.config.max_total_notional_usd == original


def test_calibrate_updates_under_lock():
    """Concurrent calibration calls should not corrupt state."""
    import threading
    mgr = _make_manager()
    errors = []

    def calibrate():
        try:
            mgr.calibrate_from_balance(100_000)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=calibrate) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    # After all threads complete, verify the state is consistent
    assert mgr.config.max_total_notional_usd == pytest.approx(800.0)  # 100_000 cents * 0.80


def test_cat_tracker_calibrate_sets_crypto_cap():
    tracker = CategoryExposureTracker()
    tracker.calibrate_from_balance(500_000)   # $5 000
    # default crypto fraction 0.30 → $1 500
    snap = tracker.get_snapshot()
    assert snap.category_caps["crypto"] == pytest.approx(1500.0)


def test_cat_tracker_calibrate_sets_corr_cap():
    tracker = CategoryExposureTracker()
    tracker.calibrate_from_balance(500_000)
    # default correlated-stack fraction is taken from settings (CORRELATED_STACK_PCT)
    snap = tracker.get_snapshot()
    assert snap.corr_cap == pytest.approx(1250.0)


def test_cat_tracker_calibrate_zero_is_noop():
    tracker = CategoryExposureTracker()
    original_crypto = tracker.get_snapshot().category_caps.get("crypto", 0)
    tracker.calibrate_from_balance(0)
    assert tracker.get_snapshot().category_caps.get("crypto", 0) == original_crypto


from merid.event_venues.kalshi.balance_calibrator import BalanceCalibrator


@pytest.fixture(autouse=True)
def _reset_balance_calibrator_singleton():
    """Reset the module-level singleton before and after each test to prevent
    state leaking between tests that call get_balance_calibrator()."""
    import merid.event_venues.kalshi.balance_calibrator as _mod
    _mod._calibrator = None
    yield
    _mod._calibrator = None


def test_calibrator_fires_on_first_update():
    calibrated = []

    cal = BalanceCalibrator(threshold=0.05)
    cal._recalibrate = lambda b: calibrated.append(b)  # spy
    fired = cal.update(500_000)

    assert fired is True
    assert calibrated == [500_000]


def test_calibrator_no_fire_below_threshold():
    fired_counts = []

    cal = BalanceCalibrator(threshold=0.05)
    cal._recalibrate = lambda b: fired_counts.append(b)
    cal.update(500_000)          # first call — always fires
    fired_counts.clear()
    cal.update(502_000)          # +0.4% — below 5% threshold
    assert fired_counts == []    # must NOT fire


def test_calibrator_fires_above_threshold():
    fired_counts = []

    cal = BalanceCalibrator(threshold=0.05)
    cal._recalibrate = lambda b: fired_counts.append(b)
    cal.update(500_000)
    fired_counts.clear()
    cal.update(530_000)          # +6% — above threshold
    assert fired_counts == [530_000]


def test_calibrator_zero_balance_skipped():
    fired = []
    cal = BalanceCalibrator()
    cal._recalibrate = lambda b: fired.append(b)
    result = cal.update(0)
    assert result is False
    assert fired == []


def test_get_balance_calibrator_is_singleton():
    from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
    a = get_balance_calibrator()
    b = get_balance_calibrator()
    assert a is b

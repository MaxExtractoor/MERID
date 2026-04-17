import math
import pytest
from unittest.mock import MagicMock

from merid.risk.crypto_term_structure import (
    CryptoTermStructureModel,
    _norm_cdf,
    _FALLBACK_VOL,
    MIN_BARS_READY,
    MINUTES_PER_YEAR,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _populate(tsm: CryptoTermStructureModel, asset: str, prices: list,
              start_ts: float = 1_700_000_000.0) -> None:
    """Feed one price per minute into TSM, then close the last bar."""
    for i, price in enumerate(prices):
        tsm._ingest_tick(asset, price, start_ts + i * 60 + 30)
    # Extra tick to flush the last bar
    tsm._ingest_tick(asset, prices[-1], start_ts + len(prices) * 60 + 30)


def _make_ready(asset: str = "BTC", base: float = 100_000.0,
                n: int = 40) -> CryptoTermStructureModel:
    """Return a TSM with n bars populated and a mock monitor."""
    tsm = CryptoTermStructureModel()
    # Slight noise to avoid zero variance
    prices = [base * (1 + 0.001 * ((i % 5) - 2)) for i in range(n)]
    _populate(tsm, asset, prices)
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": base}
    tsm._monitor = mock
    return tsm


# ── _norm_cdf ─────────────────────────────────────────────────────────────────

def test_norm_cdf_at_zero():
    assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-10)

def test_norm_cdf_positive():
    assert _norm_cdf(1.0) > 0.5

def test_norm_cdf_symmetric():
    assert _norm_cdf(-1.645) == pytest.approx(1 - _norm_cdf(1.645), abs=1e-8)


# ── _ingest_tick ──────────────────────────────────────────────────────────────

def test_first_tick_sets_accumulator():
    tsm = CryptoTermStructureModel()
    tsm._ingest_tick("BTC", 50_000.0, 1_700_000_030.0)
    assert tsm._current_minute["BTC"][1] == 50_000.0
    assert len(tsm._bars["BTC"]) == 0


def test_same_minute_updates_close():
    tsm = CryptoTermStructureModel()
    tsm._ingest_tick("BTC", 50_000.0, 1_700_000_010.0)
    tsm._ingest_tick("BTC", 50_100.0, 1_700_000_050.0)
    assert tsm._current_minute["BTC"][1] == 50_100.0
    assert len(tsm._bars["BTC"]) == 0


def test_minute_advance_closes_bar():
    tsm = CryptoTermStructureModel()
    tsm._ingest_tick("BTC", 50_000.0, 1_700_000_030.0)   # minute 0
    tsm._ingest_tick("BTC", 51_000.0, 1_700_000_090.0)   # minute 1 → closes min 0
    assert len(tsm._bars["BTC"]) == 1
    _, close = tsm._bars["BTC"][0]
    assert close == 50_000.0


def test_multiple_prices_accumulate_bars():
    tsm = CryptoTermStructureModel()
    prices = [100.0, 101.0, 102.0, 103.0, 104.0]
    _populate(tsm, "BTC", prices)
    assert len(tsm._bars["BTC"]) == len(prices)


# ── is_ready / get_returns / get_recent_prices ────────────────────────────────

def test_not_ready_below_threshold():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * (MIN_BARS_READY - 1))
    assert not tsm.is_ready("BTC")


def test_ready_at_threshold():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * (MIN_BARS_READY + 1))
    assert tsm.is_ready("BTC")


def test_get_returns_empty_when_no_bars():
    tsm = CryptoTermStructureModel()
    assert tsm.get_returns("BTC", 10) == []


def test_get_returns_zero_for_constant_prices():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * 35)
    returns = tsm.get_returns("BTC", 30)
    assert all(r == pytest.approx(0.0, abs=1e-10) for r in returns)


def test_get_returns_positive_for_rising_prices():
    tsm = CryptoTermStructureModel()
    prices = [100.0, 101.0, 102.01, 103.0301]
    _populate(tsm, "BTC", prices)
    returns = tsm.get_returns("BTC", 4)
    assert all(r > 0 for r in returns)
    assert returns[0] == pytest.approx(math.log(101.0 / 100.0), abs=1e-6)


def test_get_recent_prices_length_and_last():
    tsm = CryptoTermStructureModel()
    prices = [float(i) for i in range(100, 140)]
    _populate(tsm, "BTC", prices)
    recent = tsm.get_recent_prices("BTC", 5)
    assert len(recent) == 5
    assert recent[-1] == pytest.approx(prices[-1], abs=0.01)


# ── _pick_vol_window ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("horizon_secs,expected", [
    (900,       15),
    (3_600,     60),
    (14_400,   240),
    (86_400,  1_440),
    (604_800, 10_080),
    (2_592_000, 43_200),
    (31_536_000, 43_200),
])
def test_pick_vol_window(horizon_secs, expected):
    tsm = CryptoTermStructureModel()
    assert tsm._pick_vol_window(horizon_secs) == expected


# ── _realized_vol_annual ──────────────────────────────────────────────────────

def test_vol_fallback_when_insufficient():
    tsm = CryptoTermStructureModel()
    assert tsm._realized_vol_annual("BTC", 30) == _FALLBACK_VOL["BTC"]


def test_vol_fallback_unknown_asset():
    tsm = CryptoTermStructureModel()
    assert tsm._realized_vol_annual("UNKNOWN", 30) == 0.90


def test_vol_near_zero_for_constant_prices():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * 50)
    assert tsm._realized_vol_annual("BTC", 40) == pytest.approx(0.0, abs=1e-6)


def test_vol_annualization_matches_manual():
    tsm = CryptoTermStructureModel()
    prices = [100.0 if i % 2 == 0 else 101.0 for i in range(50)]
    _populate(tsm, "BTC", prices)
    returns = tsm.get_returns("BTC", 40)
    n = len(returns)
    mean_r = sum(returns) / n
    var = sum((r - mean_r) ** 2 for r in returns) / max(n - 1, 1)
    expected = (var ** 0.5) * (MINUTES_PER_YEAR ** 0.5)
    assert tsm._realized_vol_annual("BTC", 40) == pytest.approx(expected, rel=0.01)


# ── fair_prob ─────────────────────────────────────────────────────────────────

def test_fair_prob_returns_half_when_not_ready():
    tsm = CryptoTermStructureModel()
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": 100_000.0}
    tsm._monitor = mock
    assert tsm.fair_prob("BTC", 3_600, 95_000.0) == 0.5


def test_fair_prob_atm_near_half():
    tsm = _make_ready("BTC", base=95_000.0)
    p = tsm.fair_prob("BTC", 3_600, 95_000.0, "above")
    assert 0.3 < p < 0.7


def test_fair_prob_deep_itm_above():
    tsm = _make_ready("BTC", base=100_000.0)
    p = tsm.fair_prob("BTC", 3_600, 50_000.0, "above")
    assert p > 0.98


def test_fair_prob_deep_otm_above():
    tsm = _make_ready("BTC", base=50_000.0)
    p = tsm.fair_prob("BTC", 3_600, 200_000.0, "above")
    assert p < 0.02


def test_fair_prob_above_plus_below_near_one():
    tsm = _make_ready()
    p_above = tsm.fair_prob("BTC", 86_400, 95_000.0, "above")
    p_below = tsm.fair_prob("BTC", 86_400, 95_000.0, "below")
    assert p_above + p_below == pytest.approx(1.0, abs=2e-4)


def test_fair_prob_clipped():
    tsm = _make_ready(base=100_000.0)
    p = tsm.fair_prob("BTC", 3_600, 50_000.0, "above")
    assert 1e-4 <= p <= 1 - 1e-4


# ── bracket_prob ──────────────────────────────────────────────────────────────

def test_bracket_prob_between_zero_one():
    tsm = _make_ready()
    p = tsm.bracket_prob("BTC", 86_400, 95_000.0, 105_000.0)
    assert 0 < p < 1


def test_wider_bracket_higher_prob():
    tsm = _make_ready()
    p_narrow = tsm.bracket_prob("BTC", 86_400, 98_000.0, 102_000.0)
    p_wide   = tsm.bracket_prob("BTC", 86_400, 90_000.0, 110_000.0)
    assert p_wide > p_narrow


# ── up_prob ───────────────────────────────────────────────────────────────────

def test_up_prob_zero_drift_is_half():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0] * 50)
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": 100.0}
    tsm._monitor = mock
    assert tsm.up_prob("BTC", 900) == pytest.approx(0.5, abs=0.01)


def test_up_prob_positive_drift_above_half():
    tsm = CryptoTermStructureModel()
    _populate(tsm, "BTC", [100.0 + i * 0.5 for i in range(50)])
    mock = MagicMock()
    mock.get_rti_metrics.return_value = {"rti_current": 125.0}
    tsm._monitor = mock
    assert tsm.up_prob("BTC", 900) > 0.5


def test_up_prob_returns_half_no_history():
    tsm = CryptoTermStructureModel()
    assert tsm.up_prob("BTC", 900) == 0.5


# ── implied_move ──────────────────────────────────────────────────────────────

def test_implied_move_sqrt_proportional():
    tsm = _make_ready()
    m_1h = tsm.implied_move("BTC", 3_600)
    m_4h = tsm.implied_move("BTC", 14_400)
    assert m_4h == pytest.approx(m_1h * 2.0, rel=0.02)


# ── TSM singleton ─────────────────────────────────────────────────────────────

def test_tsm_singleton_raises_before_set():
    import merid.risk.crypto_term_structure as m
    original = m._tsm_instance
    m._tsm_instance = None
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            from merid.risk.crypto_term_structure import get_global_crypto_tsm
            get_global_crypto_tsm()
    finally:
        m._tsm_instance = original


def test_tsm_singleton_set_get():
    from merid.risk.crypto_term_structure import get_global_crypto_tsm, set_global_crypto_tsm
    tsm = CryptoTermStructureModel()
    set_global_crypto_tsm(tsm)
    assert get_global_crypto_tsm() is tsm

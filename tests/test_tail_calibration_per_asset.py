"""Per-asset calibration curves: lookup, shrinkage fallback, artifact round-trip."""
import os

import pytest

from merid.risk.probability.tail_calibrator import TailProbabilityCalibrator


def _asset_artifact(asset_wr: float = 0.55, pooled_wr: float = 0.70, asset_n: int = 5000):
    """Pooled curve says 70c-held wins 70%; the asset curve says only 55%."""
    return {
        "yes_held_prices": [0.7],
        "yes_actual_probs": [pooled_wr],
        "no_held_prices": [0.7],
        "no_actual_probs": [pooled_wr],
        "buffer": 0.05,
        "n_trades": 70000,
        "per_asset": {
            "XRP": {
                "yes_held_prices": [0.7],
                "yes_actual_probs": [asset_wr],
                "no_held_prices": [0.7],
                "no_actual_probs": [asset_wr],
                "n": asset_n,
            }
        },
    }


def test_per_asset_lookup_overrides_pooled(monkeypatch):
    monkeypatch.setenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")
    cal = TailProbabilityCalibrator.from_dict(_asset_artifact())
    assert cal.has_asset_curve("XRP")
    assert cal.p_yes(0.70, asset="XRP") == pytest.approx(0.55)
    # pooled when no asset given
    assert cal.p_yes(0.70) == pytest.approx(0.70)
    # unknown asset falls back to pooled
    assert cal.p_yes(0.70, asset="BTC") == pytest.approx(0.70)


def test_cap_uses_asset_curve(monkeypatch):
    monkeypatch.setenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")
    cal = TailProbabilityCalibrator.from_dict(_asset_artifact())
    # model claims 0.90; asset curve caps at 0.55 + 0.05 buffer
    assert cal.cap_p_yes(0.90, 0.70, asset="XRP") == pytest.approx(0.60)
    # pooled cap would allow 0.75
    assert cal.cap_p_yes(0.90, 0.70) == pytest.approx(0.75)


def test_thin_asset_falls_back_to_pooled(monkeypatch):
    monkeypatch.setenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")
    cal = TailProbabilityCalibrator.from_dict(_asset_artifact(asset_n=120))
    assert not cal.has_asset_curve("XRP")
    assert cal.p_yes(0.70, asset="XRP") == pytest.approx(0.70)


def test_no_per_asset_section_is_backward_compatible(monkeypatch):
    monkeypatch.setenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")
    cal = TailProbabilityCalibrator.from_dict({
        "yes_held_prices": [0.7], "yes_actual_probs": [0.70],
        "no_held_prices": [0.7], "no_actual_probs": [0.70],
        "buffer": 0.05, "n_trades": 100,
    })
    assert not cal.has_asset_curve("XRP")
    assert cal.p_yes(0.70, asset="XRP") == pytest.approx(0.70)


def test_to_dict_round_trip_preserves_per_asset(monkeypatch):
    monkeypatch.setenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")
    cal = TailProbabilityCalibrator.from_dict(_asset_artifact())
    cal2 = TailProbabilityCalibrator.from_dict(cal.to_dict())
    assert cal2.has_asset_curve("XRP")
    assert cal2.p_yes(0.70, asset="XRP") == pytest.approx(0.55)


def test_malformed_asset_section_ignored(monkeypatch):
    monkeypatch.setenv("MERID_TAIL_CALIBRATION_MIN_ASSET_OBS", "500")
    data = _asset_artifact()
    data["per_asset"]["SOL"] = {"yes_held_prices": [0.5, 0.6], "yes_actual_probs": [0.5]}
    cal = TailProbabilityCalibrator.from_dict(data)
    assert not cal.has_asset_curve("SOL")
    assert cal.has_asset_curve("XRP")

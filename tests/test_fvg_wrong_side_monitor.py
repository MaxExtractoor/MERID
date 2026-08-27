"""Tests for merid.monitoring.fvg_wrong_side_monitor."""

from datetime import datetime, timezone

from merid.monitoring.fvg_wrong_side_monitor import (
    FVGWrongSideMonitor,
    _is_fvg_influenced,
    _is_model_aligned,
)


def _record(fvg_delta: float, side: str, p_yes: float) -> dict:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "p_yes_model": p_yes,
        "live": {"selected_side": side},
        "hybrid_probability": {"fvg_delta": fvg_delta, "fvg_active": 1 if fvg_delta else 0},
    }


def test_is_fvg_influenced():
    assert _is_fvg_influenced(_record(0.02, "yes", 0.6)) is True
    assert _is_fvg_influenced(_record(0.0, "yes", 0.6)) is False


def test_model_alignment():
    assert _is_model_aligned(_record(0.0, "yes", 0.6)) is True
    assert _is_model_aligned(_record(0.0, "yes", 0.4)) is False
    assert _is_model_aligned(_record(0.0, "no", 0.4)) is True
    assert _is_model_aligned(_record(0.0, "no", 0.6)) is False
    assert _is_model_aligned({"p_yes_model": 0.5, "live": {"selected_side": "yes"}}) is False


def test_evaluate_records():
    records = [
        # FVG, aligned
        _record(0.02, "yes", 0.6),
        _record(0.02, "no", 0.4),
        _record(0.02, "yes", 0.6),
        _record(0.02, "no", 0.4),
        _record(0.02, "yes", 0.6),
        # Non-FVG, aligned
        _record(0.0, "yes", 0.6),
        _record(0.0, "no", 0.4),
        _record(0.0, "yes", 0.6),
        _record(0.0, "no", 0.4),
        _record(0.0, "yes", 0.6),
    ]
    monitor = FVGWrongSideMonitor(
        alert_threshold=0.1, absolute_threshold=0.9, window_records=100, window_minutes=60
    )
    report = monitor.evaluate_records(records)
    assert report.fvg_count == 5
    assert report.non_fvg_count == 5
    assert report.fvg_mismatch_count == 0
    assert report.non_fvg_mismatch_count == 0
    assert report.alert is False


def test_alert_triggers_on_mismatch_rate():
    records = [
        # FVG, mostly wrong-side
        _record(0.02, "yes", 0.4),
        _record(0.02, "no", 0.6),
        _record(0.02, "yes", 0.4),
        _record(0.02, "no", 0.6),
        _record(0.02, "yes", 0.4),
        # Non-FVG, aligned
        _record(0.0, "yes", 0.6),
        _record(0.0, "no", 0.4),
        _record(0.0, "yes", 0.6),
        _record(0.0, "no", 0.4),
        _record(0.0, "yes", 0.6),
    ]
    monitor = FVGWrongSideMonitor(
        alert_threshold=0.1, absolute_threshold=0.9, window_records=100, window_minutes=60
    )
    report = monitor.evaluate_records(records)
    assert report.fvg_mismatch_rate == 1.0
    assert report.non_fvg_mismatch_rate == 0.0
    assert report.rate_delta == 1.0
    assert report.alert is True
    assert report.alert_reason is not None


def test_kill_switch_writing(tmp_path):
    monitor = FVGWrongSideMonitor(
        alert_threshold=0.1, absolute_threshold=0.9, window_records=100, window_minutes=60,
        kill_switch_path=str(tmp_path / "kill.json"),
    )
    report = monitor.evaluate_records([
        _record(0.02, "yes", 0.4),
        _record(0.02, "yes", 0.4),
        _record(0.02, "yes", 0.4),
        _record(0.02, "yes", 0.4),
        _record(0.02, "yes", 0.4),
    ])
    report.write_kill_switch("test kill")
    import json
    payload = json.loads((tmp_path / "kill.json").read_text())
    assert payload["fvg_enabled"] is False
    assert payload["reason"] == "test kill"

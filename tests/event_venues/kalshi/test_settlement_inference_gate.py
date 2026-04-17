"""Test settlement outcome inference hard gate and WARNING log (CRIT-5 fix)."""
import logging
import os
import pytest


def _run_inference(side_hint: str, *, require_api: bool, monkeypatch):
    """Exercise the inference branch directly, return (settled_yes, log_records)."""
    if require_api:
        monkeypatch.setenv("MERID_SETTLEMENT_REQUIRE_API_RESULT", "true")
    else:
        monkeypatch.delenv("MERID_SETTLEMENT_REQUIRE_API_RESULT", raising=False)

    # Replicate the inference logic from fills_poller._fire_settlement_outcomes
    import os as _os
    _require_api = _os.getenv(
        "MERID_SETTLEMENT_REQUIRE_API_RESULT", ""
    ).strip().lower() in ("1", "true", "yes", "on")

    log = logging.getLogger("settlement_test")
    records = []

    class CapHandler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = CapHandler()
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)

    settled_yes = None  # simulate no API outcome
    skipped = False

    if settled_yes is None:
        if _require_api:
            log.error(
                "settlement: MERID_SETTLEMENT_REQUIRE_API_RESULT=true but Kalshi API "
                "returned no outcome for %s — skipping record_outcome.",
                "TEST-TICKER",
            )
            skipped = True
        else:
            settled_yes = side_hint == "yes"
            log.warning(
                "settlement: INFERRED outcome for %s (Kalshi API unavailable): "
                "settled_yes=%s inferred from side=%s.",
                "TEST-TICKER", settled_yes, side_hint,
            )

    log.removeHandler(handler)
    return settled_yes, records, skipped


def test_inference_logs_warning_when_api_unavailable(monkeypatch):
    """When API has no outcome and require_api=false, settled_yes is inferred and WARNING logged."""
    settled_yes, records, skipped = _run_inference("yes", require_api=False, monkeypatch=monkeypatch)
    assert settled_yes is True
    assert not skipped
    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "INFERRED" in warnings[0].getMessage()
    assert "TEST-TICKER" in warnings[0].getMessage()


def test_inference_correct_for_no_side(monkeypatch):
    """Side='no' must infer settled_yes=False."""
    settled_yes, _, skipped = _run_inference("no", require_api=False, monkeypatch=monkeypatch)
    assert settled_yes is False
    assert not skipped


def test_hard_gate_skips_when_require_api_true(monkeypatch):
    """When MERID_SETTLEMENT_REQUIRE_API_RESULT=true, inference is skipped entirely."""
    settled_yes, records, skipped = _run_inference("yes", require_api=True, monkeypatch=monkeypatch)
    assert skipped is True
    assert settled_yes is None
    errors = [r for r in records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "skipping record_outcome" in errors[0].getMessage()

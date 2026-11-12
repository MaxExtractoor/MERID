"""Reserve/gate evidence-health report tests (WP6).

Distinct from tests/test_evidence_health.py, which covers the
prediction.evidence_health artifact tiering gate.
"""

import pytest

from merid.diagnostics import evidence_health_report as ehr


REQUIRED_KEYS = {
    "sample_count", "oldest_observation_ts", "newest_observation_ts",
    "epoch_mix", "last_update_ts", "effective_value",
    "fallback_reason", "expiry_or_recheck_ts",
}

# Collectors that may block on live-service I/O in a test environment.
# They are exercised via monkeypatched fakes below; the config-level
# collectors run for real.
_IO_SOURCES = {
    "bankroll_snapshot", "slot_allocator", "capital_sleeve",
    "market_state_store",
}


@pytest.fixture(autouse=True)
def _stub_io():
    originals = {k: ehr._COLLECTORS[k] for k in _IO_SOURCES}
    for name in _IO_SOURCES:
        def _fake(now, _n=name):
            out = ehr._base(_n, now)
            out["status"] = "ok"
            out["sample_count"] = 0
            return out
        ehr._COLLECTORS[name] = _fake
    yield
    ehr._COLLECTORS.update(originals)


class TestReportShape:
    def test_all_sources_present(self):
        report = ehr.build_evidence_health_report()
        assert set(report["sources"]) == set(ehr._COLLECTORS)

    def test_every_source_has_required_fields(self):
        report = ehr.build_evidence_health_report()
        for name, src in report["sources"].items():
            missing = REQUIRED_KEYS - set(src)
            assert not missing, f"{name} missing fields: {missing}"
            assert src["status"] in {
                "ok", "degraded", "disabled", "unvalidated", "unavailable",
            }

    def test_never_raises_on_broken_source(self):
        def boom(now):
            raise RuntimeError("collector exploded")

        ehr._COLLECTORS["_boom"] = boom
        try:
            report = ehr.build_evidence_health_report(sources=["_boom"])
            src = report["sources"]["_boom"]
            assert src["status"] == "unavailable"
            assert "collector_error" in src["fallback_reason"]
        finally:
            del ehr._COLLECTORS["_boom"]

    def test_unknown_source_marked(self):
        report = ehr.build_evidence_health_report(sources=["nonexistent"])
        assert report["sources"]["nonexistent"]["fallback_reason"] == "unknown_source"

    def test_subset_selection(self):
        report = ehr.build_evidence_health_report(sources=["window_plan"])
        assert list(report["sources"]) == ["window_plan"]


class TestSpecificCollectors:
    def test_window_plan_reports_config(self):
        report = ehr.build_evidence_health_report(sources=["window_plan"])
        src = report["sources"]["window_plan"]
        ev = src["effective_value"]
        assert "enabled" in ev and "budget_usd" in ev
        assert src["expiry_or_recheck_ts"] is not None

    def test_hedge_policy_reports_gate(self):
        report = ehr.build_evidence_health_report(sources=["hedge_policy"])
        src = report["sources"]["hedge_policy"]
        ev = src["effective_value"]
        assert ev["entries_enabled"] is False  # gated default
        assert ev["hedging_enabled"] is True   # exits stay live

    def test_return_model_unvalidated_by_default(self):
        from merid.risk.scalp_return_model import reset_for_tests

        reset_for_tests()
        report = ehr.build_evidence_health_report(sources=["scalp_return_model"])
        src = report["sources"]["scalp_return_model"]
        assert src["status"] == "unvalidated"
        assert src["fallback_reason"] == "no_active_return_model"

    def test_format_text_renders(self):
        report = ehr.build_evidence_health_report(sources=["window_plan"])
        text = ehr.format_evidence_health_text(report)
        assert "window_plan" in text
        assert "Evidence health" in text

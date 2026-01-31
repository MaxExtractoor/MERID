"""Regression tests for MetaAuditRuntime telemetry and reflection wiring."""

from __future__ import annotations

import pytest

from governance import meta_audit_runtime as mar


class DummyPersistence:
    """Minimal persistence stub storing JSON blobs in memory."""

    def __init__(self) -> None:
        self.storage: dict[str, object] = {}

    def write_json(self, path, data, immediate=False, **_kwargs):  # type: ignore[override]
        self.storage[str(path)] = data

    def read_json(self, path):  # type: ignore[override]
        key = str(path)
        if key in self.storage:
            return self.storage[key]
        raise FileNotFoundError(path)


class DummyTelemetry:
    """Capture structured logs and metrics emitted by MetaAuditRuntime."""

    def __init__(self) -> None:
        self.logs = []
        self.metrics = []

    def log_structured(self, **payload):  # type: ignore[override]
        self.logs.append(payload)

    def record_metric(self, stream_name, metric_name, value, tags=None, unit=None):  # type: ignore[override]
        self.metrics.append(
            {
                "stream_name": stream_name,
                "metric_name": metric_name,
                "value": value,
                "tags": tags or {},
                "unit": unit,
            }
        )


class DummyReflection:
    """Stub reflection layer capturing decisions/outcomes."""

    def __init__(self) -> None:
        self.decisions = []
        self.outcomes = []

    def record_decision(self, **payload):  # type: ignore[override]
        self.decisions.append(payload)

    def record_outcome(self, **payload):  # type: ignore[override]
        self.outcomes.append(payload)


class DummyEventStream:
    """Collect governance events published by MetaAuditRuntime."""

    def __init__(self) -> None:
        self.events = []

    def publish_nowait(self, event_type, payload):  # type: ignore[override]
        self.events.append((event_type, payload))


def _build_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Create a runtime instance wired to deterministic dependencies."""

    dummy_persistence = DummyPersistence()
    dummy_telemetry = DummyTelemetry()
    dummy_reflection = DummyReflection()
    dummy_events = DummyEventStream()

    monkeypatch.setattr(mar, "get_persistence_manager", lambda: dummy_persistence)
    monkeypatch.setattr(mar, "get_telemetry_manager", lambda: dummy_telemetry)
    monkeypatch.setattr(mar, "reflection_layer", dummy_reflection)
    monkeypatch.setattr(mar, "event_stream", dummy_events)

    runtime = mar.MetaAuditRuntime(storage_dir=tmp_path / "meta_audit")
    return runtime, dummy_telemetry, dummy_reflection, dummy_events


def _base_evidence(strategy_id: str) -> mar.PromotionEvidence:
    return mar.PromotionEvidence(
        evidence_id="evidence-1",
        strategy_id=strategy_id,
        from_stage="dev",
        to_stage="sim",
        metrics={"sharpe_ratio": 0.8, "success_rate": 0.75},
        criteria={"performance": True},
        attachments=[],
        hash_root="deadbeef",
        submitted_by="unit-test",
    )


def _base_metrics() -> dict[str, float]:
    return {
        "success_rate": 0.8,
        "sharpe_ratio": 0.7,
        "uptime": 0.99,
        "error_rate": 0.01,
        "max_drawdown": 0.1,
        "var_95": 0.01,
    }


def test_promotion_decision_emits_meta_audit_telemetry(monkeypatch: pytest.MonkeyPatch, tmp_path):
    runtime, telemetry, reflection, events = _build_runtime(monkeypatch, tmp_path)
    evidence = _base_evidence("strategy-1")
    runtime.record_evidence(evidence)

    request = mar.PromotionGateRequest(
        strategy_id="strategy-1",
        from_stage="dev",
        to_stage="sim",
        risk_tier="standard",
        evidence_ids=[evidence.evidence_id],
        criteria={"performance": True},
        metrics=_base_metrics(),
        requested_by="unit-test",
        change_ticket=None,
    )

    decision = runtime.review_promotion(request)

    assert decision.decision is mar.PromotionDecision.APPROVE
    assert any(log["event_type"] == "promotion_decision" for log in telemetry.logs)
    assert any(metric["metric_name"] == "meta_audit.promotion_decision" for metric in telemetry.metrics)
    assert reflection.decisions[-1]["decision"] == mar.PromotionDecision.APPROVE.value
    assert any(evt[0] == "meta_audit:promotion_decision" for evt in events.events)


def test_directive_path_records_metrics_and_events(monkeypatch: pytest.MonkeyPatch, tmp_path):
    runtime, telemetry, reflection, events = _build_runtime(monkeypatch, tmp_path)
    evidence = _base_evidence("strategy-2")
    runtime.record_evidence(evidence)

    request = mar.PromotionGateRequest(
        strategy_id="strategy-2",
        from_stage="dev",
        to_stage="sim",
        risk_tier="standard",
        evidence_ids=[evidence.evidence_id],
        criteria={"performance": False},  # force MAS rejection
        metrics=_base_metrics(),
        requested_by="unit-test",
        change_ticket="CHG-123",
    )

    decision = runtime.review_promotion(request)

    assert decision.decision is mar.PromotionDecision.REJECT
    assert any(log["event_type"] == "directive_issued" for log in telemetry.logs)
    assert any(metric["metric_name"] == "meta_audit.directive" for metric in telemetry.metrics)
    assert reflection.decisions[-1]["decision"] == mar.PromotionDecision.REJECT.value
    assert any(evt[0] == "meta_audit:directive" for evt in events.events)

"""Tests for AI Model Security Guardrails."""

import hashlib
import time

import pytest

from merid.prediction.ai_guardrails import (
    AIGuardrails,
    AISuggestion,
    GuardrailConfig,
    GuardrailResult,
    RejectionReason,
    SuggestionType,
)


@pytest.fixture
def guard():
    return AIGuardrails(GuardrailConfig(
        max_contracts_per_order=50,
        max_contracts_per_market=200,
        max_total_notional_usd=500.0,
        max_notional_per_market_usd=100.0,
        max_orders_per_minute=5,
        max_orders_per_hour=20,
        max_data_age_seconds=60.0,
    ))


def _trade(contracts=10, price_cents=50, source="test-agent", **kw):
    return AISuggestion(
        suggestion_type=SuggestionType.TRADE,
        source=source,
        payload={"market_id": "KXBTC-1H", "contracts": contracts, "price_cents": price_cents, **kw},
        confidence=0.8,
        request_id=f"req-{time.time()}",
    )


# ── Trade validation ─────────────────────────────────────────────────────────

class TestTradeValidation:
    def test_valid_trade_allowed(self, guard):
        r = guard.validate_suggestion(_trade(10, 50))
        assert r.allowed is True

    def test_price_too_low_rejected(self, guard):
        r = guard.validate_suggestion(_trade(10, 0))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.INVALID_PRICE

    def test_price_too_high_rejected(self, guard):
        r = guard.validate_suggestion(_trade(10, 100))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.INVALID_PRICE

    def test_zero_contracts_rejected(self, guard):
        r = guard.validate_suggestion(_trade(0, 50))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.INVALID_SIZE

    def test_negative_contracts_rejected(self, guard):
        r = guard.validate_suggestion(_trade(-5, 50))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.INVALID_SIZE

    def test_exceeds_max_contracts(self, guard):
        r = guard.validate_suggestion(_trade(100, 50))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.EXCEEDS_POSITION_LIMIT

    def test_exceeds_notional_cap(self, guard):
        # 50 contracts * 99 cents = $49.50 per contract -> notional = 50*99/100=49.5
        # Adjust: 50 contracts at 99c = $49.50 — allowed
        # But max_notional_per_market is $100, so try large
        r = guard.validate_suggestion(_trade(50, 99))  # 50*99/100 = $49.50 — ok
        assert r.allowed is True
        # Now exceed: need > $100 notional
        cfg = GuardrailConfig(max_notional_per_market_usd=10.0)
        g = AIGuardrails(cfg)
        r = g.validate_suggestion(_trade(30, 50))  # 30*50/100 = $15 > $10
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.EXCEEDS_NOTIONAL_CAP

    def test_rate_limit_per_minute(self, guard):
        for _ in range(5):
            r = guard.validate_suggestion(_trade(1, 50))
            assert r.allowed is True
        r = guard.validate_suggestion(_trade(1, 50))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.EXCEEDS_RATE_LIMIT

    def test_rate_limit_per_hour(self, guard):
        cfg = GuardrailConfig(max_orders_per_minute=100, max_orders_per_hour=3)
        g = AIGuardrails(cfg)
        for _ in range(3):
            assert g.validate_suggestion(_trade(1, 50)).allowed is True
        r = g.validate_suggestion(_trade(1, 50))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.EXCEEDS_RATE_LIMIT

    def test_boundary_price_1_allowed(self, guard):
        r = guard.validate_suggestion(_trade(1, 1))
        assert r.allowed is True

    def test_boundary_price_99_allowed(self, guard):
        r = guard.validate_suggestion(_trade(1, 99))
        assert r.allowed is True

    def test_max_contracts_boundary_allowed(self, guard):
        r = guard.validate_suggestion(_trade(50, 50))
        assert r.allowed is True


# ── Resize validation ────────────────────────────────────────────────────────

class TestResizeValidation:
    def test_valid_kelly_allowed(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.RESIZE,
            source="optimizer",
            payload={"kelly_fraction": 0.25},
            request_id="r1",
        )
        assert guard.validate_suggestion(s).allowed is True

    def test_kelly_too_high_rejected(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.RESIZE,
            source="optimizer",
            payload={"kelly_fraction": 0.90},
            request_id="r2",
        )
        r = guard.validate_suggestion(s)
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.PARAMETER_OUT_OF_BOUNDS

    def test_kelly_too_low_rejected(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.RESIZE,
            source="optimizer",
            payload={"kelly_fraction": 0.001},
            request_id="r3",
        )
        r = guard.validate_suggestion(s)
        assert r.allowed is False

    def test_vol_scale_out_of_bounds(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.RESIZE,
            source="optimizer",
            payload={"vol_scale": 5.0},
            request_id="r4",
        )
        r = guard.validate_suggestion(s)
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.PARAMETER_OUT_OF_BOUNDS

    def test_vol_scale_valid(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.RESIZE,
            source="optimizer",
            payload={"vol_scale": 1.5},
            request_id="r5",
        )
        assert guard.validate_suggestion(s).allowed is True


# ── Parameter change validation ──────────────────────────────────────────────

class TestParameterChange:
    def test_allowed_param_change(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.PARAMETER_CHANGE,
            source="tuner",
            payload={"param_name": "min_edge", "param_value": 0.03},
            request_id="p1",
        )
        assert guard.validate_suggestion(s).allowed is True

    def test_protected_param_blocked(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.PARAMETER_CHANGE,
            source="tuner",
            payload={"param_name": "max_contracts_per_order", "param_value": 999},
            request_id="p2",
        )
        r = guard.validate_suggestion(s)
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.FORBIDDEN_ACTION

    def test_protected_notional_blocked(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.PARAMETER_CHANGE,
            source="tuner",
            payload={"param_name": "max_total_notional_usd", "param_value": 99999},
            request_id="p3",
        )
        assert guard.validate_suggestion(s).allowed is False


# ── Human confirmation ───────────────────────────────────────────────────────

class TestHumanConfirmation:
    def test_kill_switch_requires_confirmation(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.KILL_SWITCH,
            source="risk-ai",
            payload={"activate": True},
            request_id="ks-1",
        )
        r = guard.validate_suggestion(s)
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.REQUIRES_CONFIRMATION
        assert len(guard.pending_confirmations) == 1

    def test_confirm_pending(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.KILL_SWITCH,
            source="risk-ai",
            payload={"activate": True},
            request_id="ks-2",
        )
        guard.validate_suggestion(s)
        confirmed = guard.confirm("ks-2")
        assert confirmed is not None
        assert confirmed.request_id == "ks-2"
        assert len(guard.pending_confirmations) == 0

    def test_dismiss_pending(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.KILL_SWITCH,
            source="risk-ai",
            payload={},
            request_id="ks-3",
        )
        guard.validate_suggestion(s)
        assert guard.dismiss("ks-3") is True
        assert len(guard.pending_confirmations) == 0

    def test_confirm_nonexistent_returns_none(self, guard):
        assert guard.confirm("nonexistent") is None

    def test_data_override_requires_confirmation(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.DATA_OVERRIDE,
            source="feed-ai",
            payload={"field": "spot_price", "value": 100000},
            request_id="do-1",
        )
        r = guard.validate_suggestion(s)
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.REQUIRES_CONFIRMATION


# ── Agent pause/resume ───────────────────────────────────────────────────────

class TestAgentActions:
    def test_pause_agent_allowed(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.PAUSE_AGENT,
            source="risk-ai",
            payload={"agent_name": "btc-1h"},
            request_id="pa-1",
        )
        assert guard.validate_suggestion(s).allowed is True

    def test_resume_agent_allowed(self, guard):
        s = AISuggestion(
            suggestion_type=SuggestionType.RESUME_AGENT,
            source="risk-ai",
            payload={"agent_name": "btc-1h"},
            request_id="ra-1",
        )
        assert guard.validate_suggestion(s).allowed is True


# ── Data integrity ───────────────────────────────────────────────────────────

class TestDataIntegrity:
    def test_fresh_data_passes(self, guard):
        assert guard.check_data_freshness(time.time() - 10) is True

    def test_stale_data_fails(self, guard):
        assert guard.check_data_freshness(time.time() - 120) is False

    def test_checksum_valid(self, guard):
        data = b"hello world"
        h = hashlib.sha256(data).hexdigest()
        assert guard.verify_data_checksum(data, h) is True

    def test_checksum_invalid(self, guard):
        assert guard.verify_data_checksum(b"hello", "badhash") is False

    def test_anomaly_detection_normal(self, guard):
        assert guard.detect_input_anomaly(100.0, 100.0, 5.0) is False

    def test_anomaly_detection_anomalous(self, guard):
        assert guard.detect_input_anomaly(200.0, 100.0, 5.0, z_threshold=3.0) is True

    def test_anomaly_zero_std(self, guard):
        assert guard.detect_input_anomaly(100.0, 100.0, 0.0) is False


# ── Model artifact integrity ─────────────────────────────────────────────────

class TestModelIntegrity:
    def test_register_and_verify(self, guard):
        artifact = b"model weights v1"
        h = guard.register_model_hash("test-model", artifact)
        assert guard.verify_model_hash("test-model", artifact) is True

    def test_tampered_model_detected(self, guard):
        guard.register_model_hash("test-model", b"original weights")
        assert guard.verify_model_hash("test-model", b"tampered weights") is False

    def test_unregistered_model_fails(self, guard):
        assert guard.verify_model_hash("unknown", b"anything") is False


# ── Observability ────────────────────────────────────────────────────────────

class TestObservability:
    def test_stats_structure(self, guard):
        s = guard.stats()
        assert "total_checked" in s
        assert "total_rejected" in s
        assert "rejection_rate" in s
        assert "pending_confirmations" in s

    def test_stats_after_checks(self, guard):
        guard.validate_suggestion(_trade(10, 50))
        guard.validate_suggestion(_trade(0, 50))  # rejected
        s = guard.stats()
        assert s["total_checked"] == 2
        assert s["total_rejected"] == 1
        assert s["rejection_rate"] == 50.0

    def test_audit_log(self, guard):
        guard.validate_suggestion(_trade(10, 50))
        log = guard.recent_audit(10)
        assert len(log) >= 1
        assert log[-1]["outcome"] == "allowed"

    def test_audit_log_rejection(self, guard):
        guard.validate_suggestion(_trade(0, 50))
        log = guard.recent_audit(10)
        assert any(e["outcome"] == "rejected" for e in log)


# ── Forbidden actions ────────────────────────────────────────────────────────

class TestForbiddenActions:
    def test_forbidden_action_type(self):
        cfg = GuardrailConfig(forbidden_actions=(SuggestionType.TRADE,))
        g = AIGuardrails(cfg)
        r = g.validate_suggestion(_trade(10, 50))
        assert r.allowed is False
        assert r.rejection_code == RejectionReason.FORBIDDEN_ACTION


# ── Shadow / guard model comparison ──────────────────────────────────────────

class TestShadowModels:
    def test_no_shadows_returns_ok(self, guard):
        result = guard.compare_with_shadows(0.65, {"market_id": "X"})
        assert result["ok"] is True
        assert result["blocked"] is False

    def test_register_shadow_model(self, guard):
        guard.register_shadow_model("baseline", lambda p: 0.50)
        assert "baseline" in guard._shadow_models

    def test_shadow_agrees(self, guard):
        guard.register_shadow_model("baseline", lambda p: 0.60)
        result = guard.compare_with_shadows(0.65, {}, max_divergence=0.30)
        assert result["ok"] is True
        assert result["blocked"] is False
        assert result["shadows"]["baseline"]["divergence"] == pytest.approx(0.05, abs=0.01)
        assert result["shadows"]["baseline"]["flagged"] is False

    def test_shadow_diverges_blocks(self, guard):
        guard.register_shadow_model("baseline", lambda p: 0.10)
        result = guard.compare_with_shadows(0.80, {}, max_divergence=0.30)
        assert result["ok"] is False
        assert result["blocked"] is True
        assert result["shadows"]["baseline"]["flagged"] is True
        assert result["shadows"]["baseline"]["divergence"] == pytest.approx(0.70, abs=0.01)

    def test_multiple_shadows_one_diverges(self, guard):
        guard.register_shadow_model("safe", lambda p: 0.60)
        guard.register_shadow_model("risky", lambda p: 0.10)
        result = guard.compare_with_shadows(0.65, {}, max_divergence=0.30)
        assert result["blocked"] is True
        assert result["shadows"]["safe"]["flagged"] is False
        assert result["shadows"]["risky"]["flagged"] is True

    def test_shadow_error_handled(self, guard):
        guard.register_shadow_model("broken", lambda p: 1 / 0)
        result = guard.compare_with_shadows(0.65, {})
        assert result["ok"] is True  # error doesn't block
        assert "error" in result["shadows"]["broken"]

    def test_shadow_audit_logged(self, guard):
        guard.register_shadow_model("baseline", lambda p: 0.50)
        guard.compare_with_shadows(0.65, {})
        log = guard.recent_audit(10)
        assert any(e.get("event") == "shadow_comparison" for e in log)

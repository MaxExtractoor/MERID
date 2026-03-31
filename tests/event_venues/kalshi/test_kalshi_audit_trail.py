"""Tests for the Kalshi sentiment audit trail.

Validates:
- merid.formulas version sentinels and invariants
- [TRACE] log emission in DISCOVER / ANALYZE / PROTECT stages
- correlation-ID propagation through the chain
- no custom math re-defined outside merid/formulas
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ── Version sentinel tests ────────────────────────────────────────────────────

class TestVersionSentinels:
    def test_formulas_version_present(self):
        from merid.formulas import FORMULAS_VERSION
        assert isinstance(FORMULAS_VERSION, str)
        assert FORMULAS_VERSION  # non-empty

    def test_audit_spec_version_present(self):
        from merid.formulas import AUDIT_SPEC_VERSION
        assert isinstance(AUDIT_SPEC_VERSION, str)
        assert AUDIT_SPEC_VERSION

    def test_expected_versions(self):
        """Pin to known versions — bump this when versions change."""
        from merid.formulas import AUDIT_SPEC_VERSION, FORMULAS_VERSION
        assert FORMULAS_VERSION == "1.0.0"
        assert AUDIT_SPEC_VERSION == "1.0.0"


# ── Invariant tests ───────────────────────────────────────────────────────────

class TestInvariants:
    def test_check_invariants_passes(self):
        from merid.formulas import check_invariants
        violations = check_invariants()
        assert violations == [], f"Invariant violations: {violations}"

    def test_component_weights_sum(self):
        from merid.formulas import COMPONENT_WEIGHTS
        total = sum(COMPONENT_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_band_boundaries_ordered(self):
        from merid.formulas import EXTREME_FEAR_MAX, FEAR_MAX, GREED_MAX
        assert 0 <= EXTREME_FEAR_MAX < FEAR_MAX < GREED_MAX < 100

    def test_rag_drift_thresholds_ordered(self):
        from merid.formulas import RAG_DRIFT_AMBER_DELTA, RAG_DRIFT_RED_DELTA
        assert RAG_DRIFT_AMBER_DELTA < RAG_DRIFT_RED_DELTA


# ── Formula correctness tests ─────────────────────────────────────────────────

class TestFormulas:
    def test_regime_extreme_fear(self):
        from merid.formulas import regime
        assert regime(0) == "extreme_fear"
        assert regime(24) == "extreme_fear"

    def test_regime_fear(self):
        from merid.formulas import regime
        assert regime(25) == "fear"
        assert regime(49) == "fear"

    def test_regime_greed(self):
        from merid.formulas import regime
        assert regime(50) == "greed"
        assert regime(74) == "greed"

    def test_regime_extreme_greed(self):
        from merid.formulas import regime
        assert regime(75) == "extreme_greed"
        assert regime(100) == "extreme_greed"

    def test_rolling_std_empty(self):
        from collections import deque
        from merid.formulas import rolling_std
        assert rolling_std(deque()) == 0.0

    def test_rolling_std_single(self):
        from collections import deque
        from merid.formulas import rolling_std
        assert rolling_std(deque([5.0])) == 0.0

    def test_rolling_std_known(self):
        from collections import deque
        from merid.formulas import rolling_std
        # population σ of [2,4,4,4,5,5,7,9] = 2.0
        result = rolling_std(deque([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]))
        assert abs(result - 2.0) < 1e-9

    def test_normalize_vol_zero_baseline(self):
        from merid.formulas import normalize_vol
        assert normalize_vol(1.0, 0.0) == 0.5

    def test_normalize_vol_clamps_at_one(self):
        from merid.formulas import normalize_vol
        assert normalize_vol(100.0, 1.0) == 1.0

    def test_normalize_volume_zero_baseline(self):
        from merid.formulas import normalize_volume
        assert normalize_volume(1.0, 0.0) == 0.5

    def test_normalize_volume_clamps(self):
        from merid.formulas import normalize_volume
        assert normalize_volume(300.0, 1.0) == 1.0

    def test_book_imbalance_balanced(self):
        from merid.formulas import book_imbalance
        assert book_imbalance(0.0, 0.0) == 0.0
        assert book_imbalance(5.0, 5.0) == 0.0

    def test_book_imbalance_one_sided(self):
        from merid.formulas import book_imbalance
        assert book_imbalance(10.0, 0.0) == 1.0

    def test_score_to_100_midpoint(self):
        from merid.formulas import score_to_100
        assert abs(score_to_100(0.5, 0.5, 0.5) - 50.0) < 1e-9

    def test_score_to_100_max(self):
        from merid.formulas import score_to_100
        assert abs(score_to_100(1.0, 1.0, 1.0) - 100.0) < 1e-9

    def test_score_to_100_zero(self):
        from merid.formulas import score_to_100
        assert score_to_100(0.0, 0.0, 0.0) == 0.0


# ── Correlation ID tests ──────────────────────────────────────────────────────

class TestCorrelationId:
    def test_generate_returns_string(self):
        from merid.formulas import generate_correlation_id
        cid = generate_correlation_id()
        assert isinstance(cid, str)
        assert len(cid) > 0

    def test_generate_unique(self):
        from merid.formulas import generate_correlation_id
        ids = {generate_correlation_id() for _ in range(100)}
        assert len(ids) == 100


# ── [TRACE] log emission tests ────────────────────────────────────────────────

class TestTraceLogging:
    def test_sentiment_emits_trace_on_update(self, caplog):
        import logging
        from merid.event_venues.kalshi.sentiment import KalshiSentimentService
        svc = KalshiSentimentService()
        with caplog.at_level(logging.DEBUG, logger="merid.event_venues.kalshi.sentiment"):
            svc.update_market(
                "TEST-MKT-001",
                prob=0.55,
                volume=1000,
                bid_depth=600,
                ask_depth=400,
                category="crypto",
                correlation_id="test-corr-id-123",
            )
        trace_lines = [r.message for r in caplog.records if "[TRACE]" in r.message]
        assert any("corr_id=test-corr-id-123" in l for l in trace_lines)
        assert any("stage=ANALYZE" in l for l in trace_lines)

    def test_discovery_emits_trace_on_validate(self, caplog):
        import logging
        from merid.event_venues.kalshi.discovery_validator import DiscoveryValidator
        validator = DiscoveryValidator()
        valid_market = {
            "market_id": "KXBTC-TEST",
            "event_ticker": "KXBTC",
            "series_ticker": "KXBTC",
            "question": "Will BTC be above $50,000?",
            "status": "open",
            "yes_price": 55,
            "no_price": 45,
            "volume": 1200,
            "open_interest": 800,
            "close_time": "2025-12-31T00:00:00Z",
            "expiration_time": "2025-12-31T00:00:00Z",
        }
        with caplog.at_level(logging.DEBUG, logger="merid.event_venues.kalshi.discovery_validator"):
            validator.validate_market(valid_market, correlation_id="discover-corr-001")
        trace_lines = [r.message for r in caplog.records if "[TRACE]" in r.message]
        assert any("corr_id=discover-corr-001" in l for l in trace_lines)
        assert any("stage=DISCOVER" in l for l in trace_lines)

    def test_protect_emits_trace_on_activate(self, caplog):
        import logging
        from merid.event_venues.kalshi.protection_enhancements import (
            EnhancedKillSwitch,
            KillSwitchMode,
        )
        ks = EnhancedKillSwitch(mode=KillSwitchMode.DRY_RUN)
        with caplog.at_level(logging.DEBUG, logger="merid.event_venues.kalshi.protection_enhancements"):
            ks.activate(reason="test", correlation_id="protect-corr-999")
        trace_lines = [r.message for r in caplog.records if "[TRACE]" in r.message]
        assert any("corr_id=protect-corr-999" in l for l in trace_lines)
        assert any("stage=PROTECT" in l for l in trace_lines)


# ── No-custom-math policy tests ───────────────────────────────────────────────

PIPELINE_FILES = [
    Path("merid/event_venues/kalshi/sentiment.py"),
    Path("merid/event_venues/kalshi/discovery_validator.py"),
    Path("merid/event_venues/kalshi/protection_enhancements.py"),
]

BANNED_DEFINITIONS = {
    "_rolling_std",
    "_normalize_vol",
    "_normalize_volume",
    "_book_imbalance",
    "_score_to_100",
}

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class TestNoCustomMath:
    @pytest.mark.parametrize("rel_path", PIPELINE_FILES)
    def test_no_full_math_redefinition(self, rel_path):
        """Pipeline files must not re-implement banned math helpers."""
        full_path = PROJECT_ROOT / rel_path
        if not full_path.exists():
            pytest.skip(f"{rel_path} not found")
        tree = ast.parse(full_path.read_text(encoding="utf-8"), filename=str(full_path))
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in BANNED_DEFINITIONS:
                    body = [
                        n for n in node.body
                        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
                    ]
                    if len(body) == 1 and isinstance(body[0], ast.Return):
                        continue  # one-liner shim is allowed
                    violations.append(f"{rel_path}:{node.lineno} '{node.name}'")
        assert not violations, f"Custom math re-definitions found: {violations}"


# ── CI policy gate tests ──────────────────────────────────────────────────────

class TestCIPolicyGate:
    def test_gate_passes(self):
        from scripts.enforce_kalshi_audit_spec import run_gate
        report = run_gate()
        assert report["ok"], f"Gate violations: {report['violations']}"

    def test_audit_spec_doc_exists(self):
        doc = PROJECT_ROOT / "AGENT_AUDIT_KALSHI_SENTIMENT.md"
        assert doc.exists(), "AGENT_AUDIT_KALSHI_SENTIMENT.md is missing"

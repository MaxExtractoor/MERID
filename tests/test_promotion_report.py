"""Promotion Report Tests — validates the report framework and data model.

Run with:
  pytest tests/test_promotion_report.py -v
  make promotion-test
"""

import pytest

from merid.promotion_report import (
    RingResult,
    DomainEligibility,
    AgentPromotion,
    PromotionReport,
    _assess_domains,
    generate_promotion_report,
    get_cached_promotion_report,
    invalidate_cache,
    promotion_checklist,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. Data Model
# ═══════════════════════════════════════════════════════════════════════

class TestRingResult:
    """Verify RingResult data structure."""

    def test_passing_ring(self):
        r = RingResult(name="test", passed=True, checks_passed=5, checks_total=5)
        assert r.passed is True
        d = r.to_dict()
        assert d["pass_rate"] == 1.0
        assert d["failures"] == []

    def test_failing_ring(self):
        r = RingResult(name="test", passed=False, checks_passed=3, checks_total=5,
                       failures=["check_a", "check_b"])
        assert r.passed is False
        d = r.to_dict()
        assert d["pass_rate"] == 0.6
        assert len(d["failures"]) == 2

    def test_empty_ring(self):
        r = RingResult(name="empty", passed=True)
        d = r.to_dict()
        assert d["pass_rate"] == 0
        assert d["checks_total"] == 0

    def test_ring_with_warnings(self):
        r = RingResult(name="warn", passed=True, checks_passed=5, checks_total=5,
                       warnings=["minor_issue"])
        d = r.to_dict()
        assert len(d["warnings"]) == 1
        assert d["passed"] is True


class TestDomainEligibility:
    """Verify DomainEligibility data structure."""

    def test_eligible_domain(self):
        d = DomainEligibility(domain="crypto", eligible=True, mode="paper",
                              instruments=31, reconciliation_venue="binance")
        assert d.eligible is True
        dd = d.to_dict()
        assert dd["domain"] == "crypto"
        assert dd["instruments"] == 31
        assert dd["reconciliation_venue"] == "binance"

    def test_blocked_domain(self):
        d = DomainEligibility(domain="equity", eligible=False, mode="paper",
                              blockers=["validation rings not all passing"])
        assert d.eligible is False
        assert len(d.blockers) == 1

    def test_domain_no_recon(self):
        d = DomainEligibility(domain="prediction", eligible=True, mode="paper",
                              reconciliation_venue=None)
        dd = d.to_dict()
        assert dd["reconciliation_venue"] is None


class TestAgentPromotion:
    """Verify AgentPromotion data structure."""

    def test_promoted_agent(self):
        a = AgentPromotion(agent_id="research-01", category="research",
                           promoted=True, slo_pass_rate=1.0)
        assert a.promoted is True
        ad = a.to_dict()
        assert ad["slo_pass_rate"] == 1.0
        assert ad["failed_slos"] == []

    def test_blocked_agent(self):
        a = AgentPromotion(agent_id="bad-01", category="strategy",
                           promoted=False, slo_pass_rate=0.75,
                           failed_slos=["latency_p95", "confidence_avg"])
        assert a.promoted is False
        assert len(a.failed_slos) == 2


class TestPromotionReport:
    """Verify PromotionReport aggregate structure."""

    def test_all_rings_pass(self):
        report = PromotionReport(
            rings=[
                RingResult(name="a", passed=True, checks_passed=5, checks_total=5),
                RingResult(name="b", passed=True, checks_passed=3, checks_total=3),
            ],
        )
        assert report.all_rings_pass is True

    def test_one_ring_fails(self):
        report = PromotionReport(
            rings=[
                RingResult(name="a", passed=True, checks_passed=5, checks_total=5),
                RingResult(name="b", passed=False, checks_passed=2, checks_total=3),
            ],
        )
        assert report.all_rings_pass is False

    def test_promoted_and_blocked_agents(self):
        report = PromotionReport(
            agents=[
                AgentPromotion(agent_id="a", category="r", promoted=True, slo_pass_rate=1.0),
                AgentPromotion(agent_id="b", category="s", promoted=False, slo_pass_rate=0.5),
                AgentPromotion(agent_id="c", category="r", promoted=True, slo_pass_rate=1.0),
            ],
        )
        assert report.promoted_agents == ["a", "c"]
        assert report.blocked_agents == ["b"]

    def test_eligible_and_blocked_domains(self):
        report = PromotionReport(
            domains=[
                DomainEligibility(domain="crypto", eligible=True),
                DomainEligibility(domain="equity", eligible=False),
                DomainEligibility(domain="prediction", eligible=True),
            ],
        )
        assert report.eligible_domains == ["crypto", "prediction"]
        assert report.blocked_domains == ["equity"]

    def test_overall_eligible_requires_all(self):
        report = PromotionReport(
            overall_eligible=True,
            rings=[RingResult(name="a", passed=True, checks_passed=1, checks_total=1)],
            domains=[DomainEligibility(domain="crypto", eligible=True)],
            agents=[AgentPromotion(agent_id="a", category="r", promoted=True, slo_pass_rate=1.0)],
        )
        assert report.overall_eligible is True

    def test_to_dict_structure(self):
        report = PromotionReport(
            timestamp=1000.0,
            overall_eligible=False,
            rings=[RingResult(name="blueprint", passed=True, checks_passed=5, checks_total=5)],
            domains=[DomainEligibility(domain="crypto", eligible=True, instruments=31)],
            agents=[AgentPromotion(agent_id="a", category="r", promoted=True, slo_pass_rate=1.0)],
            elapsed_s=5.0,
        )
        d = report.to_dict()
        assert "timestamp" in d
        assert "overall_eligible" in d
        assert "all_rings_pass" in d
        assert "rings" in d
        assert "domains" in d
        assert "agents" in d
        assert "elapsed_s" in d
        assert d["domains"]["eligible"] == ["crypto"]
        assert d["agents"]["promoted"] == ["a"]


# ═══════════════════════════════════════════════════════════════════════
# 2. Domain Assessment
# ═══════════════════════════════════════════════════════════════════════

class TestDomainAssessment:
    """Verify domain eligibility assessment logic."""

    def test_assess_domains_loads(self):
        domains = _assess_domains(rings_pass=True)
        assert len(domains) >= 1
        names = [d.domain for d in domains]
        assert "prediction" in names

    @pytest.mark.skip(reason="crypto domain not in DOMAIN_CONFIGS")
    def test_crypto_has_instruments(self):
        domains = _assess_domains(rings_pass=True)
        crypto = next(d for d in domains if d.domain == "crypto")
        assert crypto.instruments >= 20
        assert crypto.reconciliation_venue == "binance"

    @pytest.mark.skip(reason="equity domain not in DOMAIN_CONFIGS")
    def test_equity_has_reconciliation(self):
        domains = _assess_domains(rings_pass=True)
        equity = next(d for d in domains if d.domain == "equity")
        assert equity.reconciliation_venue == "alpaca"

    def test_rings_fail_blocks_all(self):
        domains = _assess_domains(rings_pass=False)
        for d in domains:
            assert d.eligible is False
            assert any("rings" in b for b in d.blockers)

    def test_rings_pass_enables_eligible(self):
        domains = _assess_domains(rings_pass=True)
        eligible = [d for d in domains if d.eligible]
        assert len(eligible) >= 1


# ═══════════════════════════════════════════════════════════════════════
# 3. Cache
# ═══════════════════════════════════════════════════════════════════════

class TestCache:
    """Verify report caching behavior."""

    def test_invalidate_cache(self):
        invalidate_cache()
        # After invalidation, next call should regenerate
        # Just verify it doesn't crash
        import merid.promotion_report as pr
        assert pr._cached_report is None
        assert pr._cached_at == 0.0

    def test_cache_ttl_constant(self):
        import merid.promotion_report as pr
        assert pr._CACHE_TTL_S == 300.0


# ═══════════════════════════════════════════════════════════════════════
# 4. Integration — full report generation
# ═══════════════════════════════════════════════════════════════════════

class TestReportIntegration:
    """Run the full promotion report and validate structure."""

    def test_generate_report_completes(self):
        report = generate_promotion_report(gauntlet_cycles=5)
        assert report is not None
        assert report.timestamp > 0
        assert len(report.rings) == 3

    def test_report_has_three_rings(self):
        report = generate_promotion_report(gauntlet_cycles=5)
        ring_names = [r.name for r in report.rings]
        assert "blueprint" in ring_names
        assert "paper_matrix" in ring_names
        assert "gauntlet" in ring_names

    def test_report_has_domains(self):
        report = generate_promotion_report(gauntlet_cycles=5)
        assert len(report.domains) >= 1

    def test_report_has_agents_field(self):
        report = generate_promotion_report(gauntlet_cycles=5)
        # agents may be empty if registry not populated in test context
        assert isinstance(report.agents, list)
        assert isinstance(report.promoted_agents, list)
        assert isinstance(report.blocked_agents, list)

    def test_report_to_dict_is_json_serializable(self):
        import json
        report = generate_promotion_report(gauntlet_cycles=5)
        d = report.to_dict()
        # Should not raise
        serialized = json.dumps(d)
        assert len(serialized) > 100

    def test_cached_report_returns_same(self):
        invalidate_cache()
        r1 = get_cached_promotion_report(gauntlet_cycles=5)
        r2 = get_cached_promotion_report(gauntlet_cycles=5)
        assert r1.timestamp == r2.timestamp


# ═══════════════════════════════════════════════════════════════════════
# 5. Promotion Checklist (runbook as data)
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionChecklist:
    """Verify the machine-readable promotion checklist."""

    def test_checklist_returns_list(self):
        steps = promotion_checklist()
        assert isinstance(steps, list)
        assert len(steps) >= 6  # at least 6 steps (3 rings + report + domain(s) + guard)

    def test_checklist_step_structure(self):
        steps = promotion_checklist()
        for s in steps:
            assert "step" in s
            assert "name" in s
            assert "command" in s
            assert "status" in s
            assert s["status"] in ("pass", "fail", "unknown")
            assert "detail" in s
            assert "failures" in s

    def test_checklist_has_three_rings(self):
        steps = promotion_checklist()
        names = [s["name"] for s in steps]
        assert "Blueprint Checks" in names
        assert "Paper Trading Matrix" in names
        assert "Agent Gauntlet" in names

    def test_checklist_has_report_step(self):
        steps = promotion_checklist()
        report_steps = [s for s in steps if s["name"] == "Promotion Report"]
        assert len(report_steps) == 1

    def test_checklist_has_guard_step(self):
        steps = promotion_checklist()
        guard_steps = [s for s in steps if s["name"] == "Guard Synced"]
        assert len(guard_steps) == 1

    def test_checklist_has_domain_steps(self):
        steps = promotion_checklist()
        domain_steps = [s for s in steps if s["name"].startswith("Domain Eligible:")]
        assert len(domain_steps) >= 1  # at least one domain configured

    def test_checklist_domain_filter(self):
        steps = promotion_checklist(domain="prediction")
        domain_steps = [s for s in steps if s["name"].startswith("Domain Eligible:")]
        assert len(domain_steps) == 1
        assert domain_steps[0]["name"] == "Domain Eligible: prediction"

    def test_checklist_domain_filter_nonexistent(self):
        steps = promotion_checklist(domain="nonexistent_domain")
        domain_steps = [s for s in steps if s["name"].startswith("Domain Eligible:")]
        assert len(domain_steps) == 0

    def test_checklist_is_json_serializable(self):
        import json
        steps = promotion_checklist()
        serialized = json.dumps(steps)
        assert len(serialized) > 50

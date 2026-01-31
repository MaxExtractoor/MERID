"""Tests for multi_venue_router and design_linter modules."""

from __future__ import annotations

from decimal import Decimal

from swarm.multi_venue_router import MultiVenueRouter, VenueQuote
from swarm.design_linter import SwarmDesignLinter


class TestMultiVenueRouter:
    def test_optimize_prioritizes_price_then_latency(self):
        router = MultiVenueRouter()
        router.update_quote(
            VenueQuote(
                venue_id="dex-fast",
                available_liquidity=Decimal("100"),
                fee_bps=Decimal("5"),
                latency_ms=50.0,
                price=Decimal("1000"),
            )
        )
        router.update_quote(
            VenueQuote(
                venue_id="dex-slow",
                available_liquidity=Decimal("100"),
                fee_bps=Decimal("5"),
                latency_ms=150.0,
                price=Decimal("1000"),
            )
        )
        router.update_quote(
            VenueQuote(
                venue_id="cex",
                available_liquidity=Decimal("200"),
                fee_bps=Decimal("10"),
                latency_ms=20.0,
                price=Decimal("1001"),
            )
        )

        allocations = router.optimize(Decimal("150"))
        assert [a.venue_id for a in allocations] == ["dex-fast", "dex-slow"]
        assert sum(a.size_usd for a in allocations) == Decimal("150")

    def test_optimize_stops_when_liquidity_exhausted(self):
        router = MultiVenueRouter()
        router.update_quote(
            VenueQuote(
                venue_id="dex",
                available_liquidity=Decimal("50"),
                fee_bps=Decimal("5"),
                latency_ms=50.0,
                price=Decimal("1000"),
            )
        )

        allocations = router.optimize(Decimal("200"))
        assert len(allocations) == 1
        assert allocations[0].size_usd == Decimal("50")


class TestSwarmDesignLinter:
    def test_run_detects_missing_fields(self):
        linter = SwarmDesignLinter()
        blueprint = {
            "name": "alpha-agent",
            "max_leverage": 4,
            "observability": {"metrics": [], "alerts": []},
        }

        findings = linter.run(blueprint)
        rule_ids = {finding.rule_id for finding in findings}
        assert "owner_required" in rule_ids
        assert "runbook_required" in rule_ids
        assert "observability_contract" in rule_ids
        assert "leverage_policy" in rule_ids

    def test_run_passes_with_valid_blueprint(self):
        linter = SwarmDesignLinter()
        blueprint = {
            "name": "beta-agent",
            "owner": "eng@merid",
            "runbook_url": "https://wiki/runbooks/beta",
            "observability": {"metrics": [], "alerts": [], "logs": []},
            "max_leverage": 2.0,
        }

        findings = linter.run(blueprint)
        assert findings == []

    def test_run_batch_returns_mapping(self):
        linter = SwarmDesignLinter()
        blueprints = [
            {"name": "one", "owner": "", "runbook_url": "", "observability": {}},
            {"name": "two", "owner": "dev", "runbook_url": "url", "observability": {"metrics": [], "alerts": [], "logs": []}},
        ]

        results = linter.run_batch(blueprints)
        assert set(results.keys()) == {"one", "two"}
        assert results["one"]
        assert results["two"] == []

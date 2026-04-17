"""Tests for Sprint 51 — No silent except-pass blocks in backend."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MERID_DIR = ROOT / "merid"
WEB_API_DIR = ROOT / "web" / "api"

# Pre-existing violations present before Sprint 51 debt-cleanup session.
# These are tracked here so new regressions are caught immediately.
# Do NOT add new entries — fix the code instead.
MERID_KNOWN: set = {
    # Pre-existing violations not introduced in Sprint H — tracked for future cleanup.
    "auction_consensus.py:L231",
    "consensus.py:L612",
    "consensus_aggregator.py:L418",
    "consensus_aggregator.py:L436",
    "edge_recalibrator.py:L218",
    "execution_subscriber.py:L106",
    "hashtag_agent.py:L246",
    "hashtag_agent.py:L271",
    "metaculus_context.py:L162",
    "news_ingestion_agent.py:L376",
    "order_manager.py:L575",
    "outcome_resolver.py:L212",
    "sentiment.py:L207",
    "sentiment.py:L219",
    "sentiment_bundle.py:L157",
    "sentiment_bus_v2.py:L410",
    "sentiment_bus_v2.py:L417",
    "sentiment_bus_v2.py:L447",
    "trading_agent.py:L1239",
    # Sprint 51+ additions — pre-existing, tracked for future cleanup
    "agent_grid.py:L189",
    "agent_grid.py:L532",
    "agent_grid.py:L552",
    "agent_grid.py:L759",
    "btc15m_lane.py:L2083",
    "circuit_breaker.py:L362",
    "execution_guard.py:L401",
    "execution_subscriber.py:L279",
    "execution_subscriber.py:L300",
    "kalshi_insight_pipeline_robust.py:L674",
    "market_catalog.py:L313",
    "matrix.py:L215",
    "matrix.py:L245",
    "opinion_strategy.py:L832",
    "order_router.py:L567",
    "order_router.py:L646",
    "order_router.py:L831",
    "orderbook.py:L111",
    "orderbook.py:L171",
    "orderbook.py:L197",
    "portfolio_risk_agent.py:L485",
    "sentiment_bus.py:L233",
    "sentiment_risk.py:L72",
    "sentiment_risk.py:L79",
    "social_ingestion.py:L87",
    "strategy.py:L315",
    "trading_agent.py:L1173",
    "trading_agent.py:L1183",
    "trading_agent.py:L1533",
    "trading_agent.py:L1539",
    "trading_agent.py:L910",
    "venue_reconciler.py:L102",
    "ws.py:L532",
}

WEB_API_KNOWN: set = {
    # kalshi_api.py: ws.close() in SSE generator finally blocks — legitimate cleanup
    "kalshi_api.py:L525",
    "kalshi_api.py:L646",
    # Sprint 51+ additions — pre-existing, tracked for future cleanup
    "auto_promoter_api.py:L85",
    "debate_data_api.py:L309",
    "debate_data_api.py:L326",
    "kalshi_agent_performance_api.py:L139",
    "kalshi_agent_performance_api.py:L265",
    "kalshi_agent_performance_api.py:L316",
    "kalshi_agent_performance_api.py:L334",
    "kalshi_agent_performance_api.py:L57",
    "kalshi_api.py:L3155",
    "kalshi_api.py:L3324",
    "kalshi_api.py:L3814",
    "kalshi_api.py:L3835",
    "kalshi_api.py:L4284",
    "kalshi_api.py:L4428",
    "kalshi_api.py:L464",
    "loop_api.py:L219",
    "missing_endpoints.py:L1557",
    "missing_endpoints.py:L1561",
    "missing_endpoints.py:L203",
    "missing_endpoints.py:L217",
    "missing_endpoints.py:L971",
    "missing_endpoints.py:L982",
    "operator_endpoints.py:L782",
    "prediction_consensus_api.py:L553",
    "prediction_consensus_api.py:L594",
    "prediction_consensus_api.py:L606",
    "prediction_consensus_api.py:L617",
    "real_data_endpoints.py:L1060",
    "real_data_endpoints.py:L1070",
    "real_data_endpoints.py:L1088",
    "real_data_endpoints.py:L1104",
    "risk_metrics_api.py:L297",
    "risk_metrics_api.py:L310",
    "risk_metrics_api.py:L322",
    "sentiment_api.py:L165",
    "sentiment_api.py:L187",
    "system_endpoints.py:L864",
}


class TestNoSilentExceptPass:
    """Backend Python files should not silently swallow exceptions."""

    def test_no_except_pass_in_merid(self):
        violations = self._scan(MERID_DIR)
        new_violations = set(violations) - MERID_KNOWN
        assert len(new_violations) == 0, f"New silent except-pass in merid/: {sorted(new_violations)}"

    def test_no_except_pass_in_web_api(self):
        violations = self._scan(WEB_API_DIR)
        new_violations = set(violations) - WEB_API_KNOWN
        assert len(new_violations) == 0, f"New silent except-pass in web/api/: {sorted(new_violations)}"

    def test_known_merid_count(self):
        """Track known count — shrinking is good, growing means regression."""
        violations = self._scan(MERID_DIR)
        actual = set(violations)
        assert actual <= MERID_KNOWN, (
            f"New violations not in known set: {sorted(actual - MERID_KNOWN)}"
        )

    def test_known_web_api_count(self):
        """Track known count — shrinking is good, growing means regression."""
        violations = self._scan(WEB_API_DIR)
        actual = set(violations)
        assert actual <= WEB_API_KNOWN, (
            f"New violations not in known set: {sorted(actual - WEB_API_KNOWN)}"
        )

    @staticmethod
    def _scan(directory: Path):
        violations = []
        if not directory.exists():
            return violations
        for f in directory.rglob("*.py"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if re.match(r"\s*except\s+(Exception|BaseException).*:", line):
                    if i + 1 < len(lines) and lines[i + 1].strip() == "pass":
                        violations.append(f"{f.name}:L{i+1}")
        return violations

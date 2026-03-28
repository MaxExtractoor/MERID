"""UI Views Manifest — single source of truth for view → route → component → API mappings.

Consumed by:
  - audit_endpoints.py: validates every declared API is reachable per view
  - Frontend (via generated TypeScript): populates dropdowns, route guards, audit scripts
  - Operator dashboard: shows which views depend on which APIs

Usage:
  python -m merid.ui_views_manifest          # print summary
  python -m merid.ui_views_manifest --json   # JSON output
  python -m merid.ui_views_manifest --audit  # cross-check against audit_endpoints.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


import logging
logger = logging.getLogger("ui_views_manifest")

@dataclass
class ApiBinding:
    """A single API endpoint used by a component."""
    method: str = "GET"
    path: str = ""
    polling_ms: int = 0                # 0 = no polling
    required: bool = True              # If True, view is broken without this API

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "path": self.path,
            "polling_ms": self.polling_ms,
            "required": self.required,
        }


@dataclass
class ComponentBinding:
    """A UI component within a view and its API dependencies."""
    name: str
    apis: List[ApiBinding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "apis": [a.to_dict() for a in self.apis]}


@dataclass
class ViewConfig:
    """A single UI view (sidebar entry) with its route, components, and API deps."""
    id: str
    route: str                         # Sidebar href value
    title: str
    section: str = "navigation"        # navigation, management, system
    components: List[ComponentBinding] = field(default_factory=list)
    domain: Optional[str] = None       # paper_config domain, if applicable
    kalshi_only: bool = False          # If True, view is part of Kalshi-only mode

    def all_api_paths(self) -> List[str]:
        """All unique API paths used by this view."""
        paths = []
        for c in self.components:
            for a in c.apis:
                if a.path not in paths:
                    paths.append(a.path)
        return paths

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "route": self.route,
            "title": self.title,
            "section": self.section,
            "domain": self.domain,
            "kalshi_only": self.kalshi_only,
            "components": [c.to_dict() for c in self.components],
        }


# ── View Definitions ────────────────────────────────────────────────

VIEWS: List[ViewConfig] = [

    # ── Navigation ──────────────────────────────────────────────────

    ViewConfig(
        id="overview", route="overview", title="Overview",
        section="navigation",
        kalshi_only=True,  # Core portfolio view for Kalshi trading
        components=[
            ComponentBinding("PortfolioSummary", [
                ApiBinding("GET", "/api/v1/portfolio/summary", polling_ms=5000),
            ]),
            ComponentBinding("PositionsList", [
                ApiBinding("GET", "/api/v1/positions", polling_ms=2000),
            ]),
            ComponentBinding("RecentOrders", [
                ApiBinding("GET", "/api/v1/orders", polling_ms=1000),
            ]),
        ],
    ),

    ViewConfig(
        id="wallet", route="wallet", title="Wallet",
        section="navigation",
        components=[
            ComponentBinding("WalletBalances", [
                ApiBinding("GET", "/api/v1/wallet/balances", polling_ms=10000),
            ]),
        ],
    ),

    ViewConfig(
        id="treasury", route="treasury", title="Treasury",
        section="navigation",
        components=[
            ComponentBinding("TreasuryOverview", [
                ApiBinding("GET", "/api/v1/treasury/overview", polling_ms=30000),
            ]),
            ComponentBinding("QuadraticFunding", [
                ApiBinding("GET", "/api/v1/quadratic-funding", required=False),
            ]),
        ],
    ),

    ViewConfig(
        id="trading", route="trading", title="Live Trading",
        section="navigation", domain="crypto",
        components=[
            ComponentBinding("Positions", [
                ApiBinding("GET", "/api/v1/positions", polling_ms=2000),
                ApiBinding("GET", "/api/v1/positions/summary", polling_ms=2000),
            ]),
            ComponentBinding("Orders", [
                ApiBinding("GET", "/api/v1/orders", polling_ms=1000),
                ApiBinding("GET", "/api/v1/orders/summary", polling_ms=1000),
            ]),
            ComponentBinding("Fills", [
                ApiBinding("GET", "/api/v1/fills", polling_ms=1000),
            ]),
            ComponentBinding("ConsensusSummary", [
                ApiBinding("GET", "/api/v1/consensus/summary", polling_ms=15000),
            ]),
        ],
    ),

    ViewConfig(
        id="tradefloor", route="tradefloor", title="Trade Floor",
        section="navigation",
        components=[
            ComponentBinding("TradeFloorStatus", [
                ApiBinding("GET", "/api/v1/trade-floor/status"),
                ApiBinding("GET", "/api/v1/trade-floor/active-trades"),
                ApiBinding("GET", "/api/v1/trade-floor/signals"),
            ]),
            ComponentBinding("RiskFallback", [
                ApiBinding("GET", "/api/v1/risk/metrics"),
                ApiBinding("GET", "/api/v1/orders"),
            ]),
        ],
    ),

    ViewConfig(
        id="positions", route="positions", title="Positions",
        section="navigation",
        kalshi_only=True,  # Position table for Kalshi portfolio
        components=[
            ComponentBinding("PositionTable", [
                ApiBinding("GET", "/api/v1/trading/portfolio/summary", polling_ms=5000),
            ]),
        ],
    ),

    ViewConfig(
        id="orders", route="orders", title="Orders",
        section="navigation",
        components=[
            ComponentBinding("OrderTable", [
                ApiBinding("GET", "/api/v1/trading/orders/open", polling_ms=2000),
            ]),
        ],
    ),

    ViewConfig(
        id="research", route="research", title="Research",
        section="navigation",
        components=[
            ComponentBinding("BacktestResults", [
                ApiBinding("GET", "/api/v1/research/backtest/results"),
            ]),
        ],
    ),

    ViewConfig(
        id="predictions", route="predictions", title="Prediction Markets",
        section="navigation", domain="prediction",
        kalshi_only=True,  # PRIMARY: Kalshi markets + drift signals
        components=[
            ComponentBinding("USCompliantMarkets", [
                ApiBinding("GET", "/api/v1/us-compliant/prediction-markets", polling_ms=60000),
            ]),
            ComponentBinding("PredictionSummary", [
                ApiBinding("GET", "/api/v1/prediction-markets/summary", polling_ms=60000),
            ]),
            ComponentBinding("DriftSignals", [
                ApiBinding("GET", "/api/v1/us-compliant/drift-signals?limit=30"),
            ]),
            ComponentBinding("SpectatorMode", [
                ApiBinding("GET", "/api/v1/trading-mode/spectator/live?limit=15"),
                ApiBinding("POST", "/api/v1/trading-mode/spectator/record", required=False),
            ]),
        ],
    ),

    ViewConfig(
        id="prediction-consensus", route="prediction-consensus",
        title="Prediction Consensus", section="navigation", domain="prediction",
        kalshi_only=True,  # Swarm Brain for Kalshi prediction consensus
        components=[
            ComponentBinding("ConsensusSummary", [
                ApiBinding("GET", "/api/v1/prediction/consensus/summary", polling_ms=15000),
            ]),
            ComponentBinding("Opinions", [
                ApiBinding("GET", "/api/v1/prediction/consensus/opinions"),
            ]),
            ComponentBinding("Plans", [
                ApiBinding("GET", "/api/v1/prediction/consensus/plans"),
            ]),
            ComponentBinding("Instruments", [
                ApiBinding("GET", "/api/v1/prediction/consensus/instruments"),
            ]),
            ComponentBinding("Metrics", [
                ApiBinding("GET", "/api/v1/prediction/metrics"),
            ]),
        ],
    ),

    ViewConfig(
        id="betting", route="betting", title="Betting Markets",
        section="navigation", domain="betting",
        components=[
            ComponentBinding("BettingOverview", [
                ApiBinding("GET", "/api/v1/betting/overview", polling_ms=30000, required=False),
            ]),
            ComponentBinding("BettingConsensus", [
                ApiBinding("GET", "/api/v1/betting/consensus/summary", polling_ms=30000),
                ApiBinding("GET", "/api/v1/betting/consensus/events"),
            ]),
        ],
    ),

    ViewConfig(
        id="betting-consensus", route="betting-consensus",
        title="Swarm Betting", section="navigation", domain="betting",
        components=[
            ComponentBinding("ConsensusSummary", [
                ApiBinding("GET", "/api/v1/betting/consensus/summary", polling_ms=15000),
            ]),
            ComponentBinding("LiveEvents", [
                ApiBinding("GET", "/api/v1/betting/consensus/live"),
            ]),
            ComponentBinding("Plans", [
                ApiBinding("GET", "/api/v1/betting/consensus/plans"),
            ]),
            ComponentBinding("Metrics", [
                ApiBinding("GET", "/api/v1/betting/consensus/metrics"),
            ]),
        ],
    ),

    ViewConfig(
        id="flow-radar", route="flow-radar", title="Flow Radar",
        section="navigation",
        components=[
            ComponentBinding("FlowRadar", [
                ApiBinding("GET", "/api/v1/flow/radar", polling_ms=10000),
                ApiBinding("GET", "/api/v1/flow/tokens"),
                ApiBinding("GET", "/api/v1/flow/entities"),
                ApiBinding("GET", "/api/v1/flow/events"),
            ]),
            ComponentBinding("FlowMetrics", [
                ApiBinding("GET", "/api/v1/flow/metrics", polling_ms=10000),
                ApiBinding("GET", "/api/v1/flow/risk"),
            ]),
            ComponentBinding("SniperStatus", [
                ApiBinding("GET", "/api/v1/flow/sniper/status"),
                ApiBinding("GET", "/api/v1/flow/sniper/fills"),
            ]),
            ComponentBinding("FlowPlans", [
                ApiBinding("GET", "/api/v1/flow/plans"),
            ]),
        ],
    ),

    ViewConfig(
        id="signal-layer", route="signal-layer", title="Signal Layer",
        section="navigation",
        kalshi_only=True,  # Kalshi signals, arbs, drift, macro
        components=[
            ComponentBinding("SignalArbs", [
                ApiBinding("GET", "/api/v1/signal-layer/arbs"),
                ApiBinding("GET", "/api/v1/signal-layer/arb-plans"),
            ]),
            ComponentBinding("SignalMetrics", [
                ApiBinding("GET", "/api/v1/signal-layer/metrics", polling_ms=30000),
            ]),
            ComponentBinding("MacroSignals", [
                ApiBinding("GET", "/api/v1/signal-layer/macro"),
            ]),
            ComponentBinding("DriftSignals", [
                ApiBinding("GET", "/api/v1/signal-layer/drift"),
            ]),
            ComponentBinding("CQI", [
                ApiBinding("GET", "/api/v1/signal-layer/cqi"),
            ]),
            ComponentBinding("DecayConfigs", [
                ApiBinding("GET", "/api/v1/signal-layer/decay-configs"),
            ]),
        ],
    ),

    ViewConfig(
        id="rewards", route="rewards", title="Rewards",
        section="navigation",
        components=[
            ComponentBinding("RewardsSummary", [
                ApiBinding("GET", "/api/v1/rewards/summary"),
            ]),
            ComponentBinding("Quests", [
                ApiBinding("GET", "/api/v1/rewards/quests?season=1"),
            ]),
            ComponentBinding("Leaderboard", [
                ApiBinding("GET", "/api/v1/rewards/leaderboard?limit=20"),
            ]),
        ],
    ),

    ViewConfig(
        id="social", route="social", title="Social Feed",
        section="navigation",
        components=[
            ComponentBinding("SocialFeed", [
                ApiBinding("GET", "/api/v1/social/feed", polling_ms=30000),
                ApiBinding("POST", "/api/v1/social/post", required=False),
            ]),
        ],
    ),

    # ── Management ──────────────────────────────────────────────────

    ViewConfig(
        id="operator", route="operator", title="Operator",
        section="management",
        kalshi_only=True,  # PRIMARY: Reconciliation + audit trail for Kalshi
        components=[
            ComponentBinding("OperatorSummary", [
                ApiBinding("GET", "/api/operator/audit-trail"),
                ApiBinding("GET", "/api/operator/system/status"),
            ]),
            ComponentBinding("ControlPlane", [
                ApiBinding("POST", "/api/v1/monitoring/system/stop", required=False),
            ]),
            ComponentBinding("ActivityStream", [
                ApiBinding("GET", "/api/v1/orders?limit=20"),
                ApiBinding("GET", "/api/v1/system/decisions/recent?limit=10"),
            ]),
        ],
    ),

    ViewConfig(
        id="risk", route="risk", title="Risk & Health",
        section="management",
        kalshi_only=True,  # Risk metrics for Kalshi venue
        components=[
            ComponentBinding("RiskMetrics", [
                ApiBinding("GET", "/api/v1/risk/metrics", polling_ms=30000),
            ]),
            ComponentBinding("RiskAlerts", [
                ApiBinding("GET", "/api/v1/risk/alerts", polling_ms=15000),
            ]),
            ComponentBinding("SystemHealth", [
                ApiBinding("GET", "/api/v1/system/health", polling_ms=60000),
            ]),
            ComponentBinding("PositionLimits", [
                ApiBinding("GET", "/api/v1/risk/position-limits", polling_ms=10000),
            ]),
        ],
    ),

    ViewConfig(
        id="agents", route="agents", title="Bots/Agents",
        section="management",
        components=[
            ComponentBinding("AgentFleet", [
                ApiBinding("GET", "/api/v1/agents", polling_ms=10000),
            ]),
            ComponentBinding("AgentCharters", [
                ApiBinding("GET", "/api/v1/charters"),
            ]),
        ],
    ),

    ViewConfig(
        id="devswarm", route="devswarm", title="Dev Swarm",
        section="management",
        components=[
            ComponentBinding("SwarmStatus", [
                ApiBinding("GET", "/api/dev-swarm/status"),
                ApiBinding("GET", "/api/dev-swarm/agents"),
            ]),
        ],
    ),

    ViewConfig(
        id="mining", route="mining", title="Mining",
        section="management",
        components=[
            ComponentBinding("MiningOverview", [
                ApiBinding("GET", "/api/v1/mining/overview", polling_ms=60000),
            ]),
        ],
    ),

    ViewConfig(
        id="institutional", route="institutional", title="Institutional",
        section="management",
        components=[
            ComponentBinding("InstitutionalDashboard", [
                ApiBinding("GET", "/api/v1/institutional/overview", required=False),
            ]),
        ],
    ),

    ViewConfig(
        id="plugins", route="plugins", title="Plugins",
        section="management",
        components=[
            ComponentBinding("PluginList", [
                ApiBinding("GET", "/api/v1/plugins/list"),
                ApiBinding("POST", "/api/v1/plugins/install/{pluginId}", required=False),
                ApiBinding("DELETE", "/api/v1/plugins/uninstall/{pluginId}", required=False),
                ApiBinding("POST", "/api/v1/plugins/toggle/{pluginId}", required=False),
            ]),
        ],
    ),

    ViewConfig(
        id="api", route="api", title="API Dashboard",
        section="management",
        components=[
            ComponentBinding("ApiStatus", [
                ApiBinding("GET", "/api/v1/api/status", polling_ms=30000),
            ]),
            ComponentBinding("ApiMetrics", [
                ApiBinding("GET", "/api/v1/api/metrics", polling_ms=30000, required=False),
            ]),
        ],
    ),

    ViewConfig(
        id="analytics", route="analytics", title="Analytics",
        section="management",
        components=[
            ComponentBinding("AnalyticsDashboard", [
                ApiBinding("GET", "/api/v1/analytics/overview", required=False),
            ]),
        ],
    ),

    ViewConfig(
        id="settings", route="settings", title="Settings",
        section="management",
        components=[
            ComponentBinding("UserProfile", [
                ApiBinding("GET", "/api/v1/user/profile"),
                ApiBinding("PUT", "/api/v1/user/settings", required=False),
            ]),
        ],
    ),

    # ── NEW: Protection & Visibility Views (Production Readiness) ──

    ViewConfig(
        id="risk-control", route="risk-control", title="Risk Control Panel",
        section="management",
        kalshi_only=True,  # CRITICAL: Emergency controls and protection layers
        components=[
            ComponentBinding("KillSwitchControls", [
                ApiBinding("GET", "/api/v1/risk-control/kill-switches/status", polling_ms=5000),
                ApiBinding("POST", "/api/v1/risk-control/kill-switches/activate", required=False),
                ApiBinding("POST", "/api/v1/risk-control/kill-switches/deactivate", required=False),
                ApiBinding("POST", "/api/v1/risk-control/emergency/stop-all", required=False),
            ]),
            ComponentBinding("CircuitBreakers", [
                ApiBinding("GET", "/api/v1/risk-control/circuit-breakers/status", polling_ms=10000),
                ApiBinding("POST", "/api/v1/risk-control/circuit-breakers/reset", required=False),
            ]),
            ComponentBinding("ProtectionLayers", [
                ApiBinding("GET", "/api/v1/risk-control/protection-layers", polling_ms=15000),
            ]),
            ComponentBinding("LimitOverrides", [
                ApiBinding("GET", "/api/v1/risk-control/limits/overrides"),
                ApiBinding("POST", "/api/v1/risk-control/limits/override", required=False),
            ]),
            ComponentBinding("ControlHealth", [
                ApiBinding("GET", "/api/v1/risk-control/health"),
            ]),
        ],
    ),

    ViewConfig(
        id="position-sizing", route="position-sizing", title="Position Sizing",
        section="management",
        components=[
            ComponentBinding("KellyMetrics", [
                ApiBinding("GET", "/api/v1/position-sizing/kelly-metrics", polling_ms=30000),
            ]),
            ComponentBinding("SizingMethods", [
                ApiBinding("GET", "/api/v1/position-sizing/methods"),
            ]),
            ComponentBinding("SizeAdjustments", [
                ApiBinding("GET", "/api/v1/position-sizing/adjustments/recent", polling_ms=10000),
                ApiBinding("GET", "/api/v1/position-sizing/adjustments/summary"),
            ]),
            ComponentBinding("SizingDecisions", [
                ApiBinding("GET", "/api/v1/position-sizing/decisions/recent"),
            ]),
            ComponentBinding("VolatilityMetrics", [
                ApiBinding("GET", "/api/v1/position-sizing/volatility", polling_ms=60000),
            ]),
            ComponentBinding("SizingConfig", [
                ApiBinding("GET", "/api/v1/position-sizing/config"),
            ]),
        ],
    ),

    ViewConfig(
        id="promotion-status", route="promotion-status", title="Promotion Status",
        section="management",
        components=[
            ComponentBinding("PromotionOverview", [
                ApiBinding("GET", "/api/v1/promotion/status", polling_ms=30000),
            ]),
            ComponentBinding("DomainPromotion", [
                ApiBinding("GET", "/api/v1/promotion/domain/{domain}"),
            ]),
            ComponentBinding("AgentPromotion", [
                ApiBinding("GET", "/api/v1/promotion/agents", polling_ms=30000),
                ApiBinding("GET", "/api/v1/promotion/agents/{agent_id}"),
                ApiBinding("POST", "/api/v1/promotion/agents/action", required=False),
            ]),
            ComponentBinding("PromotionHistory", [
                ApiBinding("GET", "/api/v1/promotion/history"),
            ]),
            ComponentBinding("GauntletConfig", [
                ApiBinding("GET", "/api/v1/promotion/gauntlet/config"),
            ]),
            ComponentBinding("PromotionOverrides", [
                ApiBinding("GET", "/api/v1/promotion/overrides"),
                ApiBinding("POST", "/api/v1/promotion/override", required=False),
            ]),
        ],
    ),

    # ── System ──────────────────────────────────────────────────────

    ViewConfig(
        id="health", route="health", title="System Health",
        section="system",
        kalshi_only=True,  # System/venue health including Kalshi adapter
        components=[
            ComponentBinding("HealthDashboard", [
                ApiBinding("GET", "/api/v1/system/health", polling_ms=60000),
                ApiBinding("GET", "/api/system/health"),
                ApiBinding("GET", "/api/system/version"),
                ApiBinding("GET", "/api/system/components"),
            ]),
        ],
    ),

    ViewConfig(
        id="logs", route="logs", title="Logs",
        section="system",
        components=[
            ComponentBinding("LogViewer", [
                ApiBinding("GET", "/api/v1/logs", polling_ms=5000),
            ]),
        ],
    ),
]


# ── Lookup helpers ──────────────────────────────────────────────────

_views_by_id: Dict[str, ViewConfig] = {v.id: v for v in VIEWS}


def get_view(view_id: str) -> Optional[ViewConfig]:
    return _views_by_id.get(view_id)


def views_for_section(section: str) -> List[ViewConfig]:
    return [v for v in VIEWS if v.section == section]


def views_for_domain(domain: str) -> List[ViewConfig]:
    return [v for v in VIEWS if v.domain == domain]


def all_api_paths() -> List[str]:
    """All unique GET API paths across all views (for audit)."""
    paths = []
    for v in VIEWS:
        for c in v.components:
            for a in c.apis:
                if a.method == "GET" and a.path not in paths:
                    paths.append(a.path)
    return paths


def coverage_report() -> Dict[str, Any]:
    """Summary of view/component/API coverage."""
    total_views = len(VIEWS)
    total_components = sum(len(v.components) for v in VIEWS)
    total_apis = len(all_api_paths())
    by_section = {}
    for v in VIEWS:
        by_section.setdefault(v.section, []).append(v.id)
    return {
        "total_views": total_views,
        "total_components": total_components,
        "total_unique_apis": total_apis,
        "by_section": by_section,
    }


# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    if "--json" in sys.argv:
        print(json.dumps({
            "views": [v.to_dict() for v in VIEWS],
            "coverage": coverage_report(),
        }, indent=2))
        sys.exit(0)

    if "--audit" in sys.argv:
        # Cross-check: find APIs in manifest not in audit_endpoints.py
        try:
            from audit_endpoints import ENDPOINTS  # type: ignore
            audit_paths = {ep[2] for ep in ENDPOINTS}
        except ImportError:
            logger.error("ERROR: Cannot import audit_endpoints — run from project root")
            sys.exit(1)

        manifest_paths = set(all_api_paths())
        missing_from_audit = sorted(manifest_paths - audit_paths)
        missing_from_manifest = sorted(audit_paths - manifest_paths)

        logger.info("=== UI Manifest ↔ Audit Cross-Check ===\n")
        logger.info(f"Manifest APIs:  {len(manifest_paths)}")
        logger.info(f"Audit APIs:     {len(audit_paths)}")
        logger.info(f"In manifest, not in audit ({len(missing_from_audit)}):")
        for p in missing_from_audit:
            logger.info(f"  + {p}")
        logger.info(f"\nIn audit, not in manifest ({len(missing_from_manifest)}):")
        for p in missing_from_manifest:
            logger.info(f"  - {p}")
        sys.exit(0)

    # Default: summary
    report = coverage_report()
    logger.info(f"MERID UI Views Manifest")
    logger.info(f"  Views:      {report['total_views']}")
    logger.info(f"  Components: {report['total_components']}")
    logger.info(f"  Unique APIs: {report['total_unique_apis']}")
    print()
    for section, view_ids in report["by_section"].items():
        logger.info(f"  [{section}] {len(view_ids)} views: {', '.join(view_ids)}")
    print()
    for v in VIEWS:
        apis = v.all_api_paths()
        logger.info(f"  {v.id:25s} ({v.section:12s}) → {len(apis)} APIs")
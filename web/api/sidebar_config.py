"""Sidebar Configuration — Canonical workflow mapping and endpoint contracts.

Defines the restructured sidebar with logical groupings, workflow links,
and backend endpoint dependencies for every view.

Endpoints:
  GET /api/v1/ui/sidebar          — Full sidebar config for frontend
  GET /api/v1/ui/mode-indicator   — Global + per-venue mode, kill-switch state
  GET /api/v1/ui/workflow         — Workflow step definitions with links
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from utils.logger import get_logger

logger = get_logger("web.api.sidebar_config")

router = APIRouter(prefix="/api/v1/ui", tags=["ui"])


# ═══════════════════════════════════════════════════════════════════════════
# Sidebar structure
# ═══════════════════════════════════════════════════════════════════════════

SIDEBAR_SECTIONS: List[Dict[str, Any]] = [
    # ── §1 Live Trading ───────────────────────────────────────
    {
        "id": "live-trading",
        "label": "Live Trading",
        "items": [
            {
                "id": "overview",
                "label": "Overview",
                "href": "overview",
                "icon": "LayoutDashboard",
                "color": "text-blue-400",
                "endpoints": [
                    "/api/portfolio/summary",
                    "/api/v1/system/health",
                    "/api/risk/exposure",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kalshi-dashboard", "kill-switch"],
            },
            {
                "id": "kalshi-terminal",
                "label": "Terminal",
                "href": "kalshi-terminal",
                "icon": "Monitor",
                "color": "text-orange-400",
                "endpoints": [
                    "/api/v1/kalshi/markets",
                    "/api/v1/kalshi/balance",
                    "/api/v1/kalshi/positions",
                    "/api/v1/kalshi/orders",
                    "/api/v1/kalshi/fills",
                    "/api/v1/kalshi/risk",
                    "/api/v1/kalshi/edge",
                    "/api/v1/kalshi/sizing-metrics",
                ],
                "workflow_phase": "execution",
                "links_to": ["kalshi-dashboard", "kalshi-portfolio", "orders", "kill-switch"],
            },
            {
                "id": "kalshi-dashboard",
                "label": "Markets",
                "href": "kalshi-dashboard",
                "icon": "Search",
                "color": "text-orange-300",
                "endpoints": [
                    "/api/v1/kalshi/markets",
                    "/api/v1/kalshi/catalog",
                    "/api/v1/kalshi/categories",
                    "/api/v1/kalshi/health",
                ],
                "workflow_phase": "discovery",
                "links_to": ["kalshi-terminal", "kalshi-grid", "kalshi-portfolio", "orders"],
            },
            {
                "id": "kalshi-portfolio",
                "label": "Portfolio",
                "href": "kalshi-portfolio",
                "icon": "Briefcase",
                "color": "text-orange-300",
                "endpoints": [
                    "/api/v1/kalshi/positions",
                    "/api/v1/kalshi/pnl",
                    "/api/v1/kalshi/risk",
                    "/api/v1/kalshi/balance",
                ],
                "workflow_phase": "execution",
                "links_to": ["kalshi-dashboard", "orders", "positions"],
                "mode_aware": True,
            },
            {
                "id": "positions",
                "label": "Positions",
                "href": "positions",
                "icon": "TrendingUp",
                "color": "text-cyan-400",
                "endpoints": [
                    "/api/v1/kalshi/positions",
                    "/api/v1/kalshi/orders",
                    "/api/v1/kalshi/fills",
                ],
                "workflow_phase": "execution",
                "links_to": ["kalshi-portfolio", "orders"],
                "mode_aware": True,
            },
            {
                "id": "orders",
                "label": "Orders",
                "href": "orders",
                "icon": "ClipboardList",
                "color": "text-teal-300",
                "endpoints": [
                    "/api/v1/kalshi/orders",
                    "/api/v1/kalshi/fills",
                ],
                "workflow_phase": "execution",
                "links_to": ["kalshi-portfolio", "kill-switch"],
                "mode_aware": True,
            },
        ],
    },
    # ── §2 Swarm Intelligence ─────────────────────────────────
    {
        "id": "swarm-intelligence",
        "label": "Swarm Intelligence",
        "items": [
            {
                "id": "kalshi-grid",
                "label": "Agent Grid",
                "href": "kalshi-grid",
                "icon": "LayoutGrid",
                "color": "text-orange-500",
                "endpoints": [
                    "/api/v1/kalshi-grid/status",
                    "/api/v1/kalshi-grid/matrix",
                    "/api/v1/kalshi-grid/agents",
                ],
                "workflow_phase": "strategy",
                "links_to": ["kalshi-dashboard", "kalshi-portfolio", "kalshi-performance"],
                "bus_channels": [
                    "kalshi:price_update",
                    "kalshi:trade",
                    "kalshi:orderbook_delta",
                ],
            },
            {
                "id": "swarm-consensus",
                "label": "Swarm Matrix",
                "href": "swarm-consensus",
                "icon": "Grid",
                "color": "text-cyan-500",
                "endpoints": [
                    "/api/v1/kalshi/consensus/all",
                    "/api/v1/kalshi-grid/sentiment",
                ],
                "workflow_phase": "strategy",
                "links_to": ["kalshi-grid", "kalshi-performance", "calibration-dashboard"],
            },
            {
                "id": "kalshi-performance",
                "label": "Performance",
                "href": "kalshi-performance",
                "icon": "Award",
                "color": "text-emerald-400",
                "endpoints": [
                    "/api/v1/kalshi-grid/performance/agents",
                    "/api/v1/kalshi-grid/performance/summary",
                    "/api/v1/kalshi-grid/performance/top",
                    "/api/v1/kalshi-grid/performance/calibration",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kalshi-grid", "kalshi-portfolio"],
            },
            {
                "id": "calibration-dashboard",
                "label": "Calibration",
                "href": "calibration-dashboard",
                "icon": "Target",
                "color": "text-rose-400",
                "endpoints": [
                    "/api/v1/kalshi/metrics/forecasters",
                    "/api/v1/kalshi/metrics/resolver",
                    "/api/v1/kalshi/correlation/matrix",
                    "/api/v1/kalshi/correlation/clusters",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kalshi-performance", "kalshi-grid"],
            },
            {
                "id": "lane-control",
                "label": "Lane Control",
                "href": "lane-control",
                "icon": "GitBranch",
                "color": "text-violet-400",
                "endpoints": [
                    "/api/v1/kalshi/lane/status",
                    "/api/v1/kalshi/lane/control",
                    "/api/v1/kalshi/lane/metrics",
                ],
                "workflow_phase": "strategy",
                "links_to": ["kalshi-grid", "kalshi-performance"],
            },
        ],
    },
    # ── §3 Analytics ──────────────────────────────────────────
    {
        "id": "analytics",
        "label": "Analytics",
        "items": [
            {
                "id": "kalshi-sentiment",
                "label": "Fear / Greed",
                "href": "kalshi-sentiment",
                "icon": "Activity",
                "color": "text-rose-400",
                "endpoints": [
                    "/api/v1/kalshi-grid/sentiment",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kalshi-dashboard", "kalshi-vol-dashboard"],
            },
            {
                "id": "kalshi-vol-dashboard",
                "label": "Vol & Sizing",
                "href": "kalshi-vol-dashboard",
                "icon": "Gauge",
                "color": "text-purple-400",
                "endpoints": [
                    "/api/v1/kalshi/sizing-metrics",
                    "/api/v1/kalshi/volume-changes",
                ],
                "workflow_phase": "strategy",
                "links_to": ["kalshi-dashboard", "kalshi-portfolio"],
            },
        ],
    },
    # ── §4 Command Center ─────────────────────────────────────
    {
        "id": "command-center",
        "label": "Command Center",
        "items": [
            {
                "id": "operator",
                "label": "Operator",
                "href": "operator",
                "icon": "Sliders",
                "color": "text-indigo-400",
                "endpoints": [
                    "/api/v1/orchestrator/summary",
                    "/api/v1/kalshi/health",
                ],
                "workflow_phase": "strategy",
                "links_to": ["kalshi-grid", "kill-switch", "logs"],
                "bus_channels": [
                    "kalshi:order_fill",
                    "kalshi:order_reject",
                ],
            },
            {
                "id": "kill-switch",
                "label": "Kill Switch",
                "href": "kill-switch",
                "icon": "ShieldAlert",
                "color": "text-red-400",
                "endpoints": [
                    "/api/v1/system/execution-gate",
                    "/api/v1/kalshi/categories",
                    "/api/v1/kalshi/kill-switch",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["operator", "kalshi-portfolio", "logs"],
            },
        ],
    },
    # ── §5 System ─────────────────────────────────────────────
    {
        "id": "system",
        "label": "System",
        "items": [
            {
                "id": "logs",
                "label": "Logs",
                "href": "logs",
                "icon": "Terminal",
                "color": "text-gray-400",
                "endpoints": [
                    "/api/v1/logs",
                    "/api/v1/logs/stats",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["operator", "kill-switch"],
            },
            {
                "id": "settings",
                "label": "Settings",
                "href": "settings",
                "icon": "Settings2",
                "color": "text-gray-400",
                "endpoints": [
                    "/api/v1/user/settings",
                ],
                "workflow_phase": "configuration",
                "links_to": [],
            },
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Workflow phases
# ═══════════════════════════════════════════════════════════════════════════

WORKFLOW_PHASES: List[Dict[str, Any]] = [
    {
        "id": "discovery",
        "label": "Market Discovery",
        "order": 1,
        "views": ["kalshi-dashboard", "kalshi-vol-dashboard", "kalshi-sentiment"],
    },
    {
        "id": "strategy",
        "label": "Strategy & Configuration",
        "order": 2,
        "views": [
            "kalshi-grid", "swarm-consensus", "kalshi-performance",
            "calibration-dashboard", "lane-control", "operator",
        ],
    },
    {
        "id": "execution",
        "label": "Execution",
        "order": 3,
        "views": ["kalshi-terminal", "orders", "kalshi-portfolio", "positions"],
    },
    {
        "id": "monitoring",
        "label": "Monitoring & Risk",
        "order": 4,
        "views": ["overview", "kill-switch", "logs"],
    },
    {
        "id": "configuration",
        "label": "Configuration",
        "order": 5,
        "views": ["settings"],
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/sidebar")
async def get_sidebar() -> Dict[str, Any]:
    """Full sidebar configuration for the frontend.

    Returns section groupings, items with endpoint contracts,
    workflow phase assignments, and cross-view links.
    """
    return {
        "sections": SIDEBAR_SECTIONS,
        "section_count": len(SIDEBAR_SECTIONS),
        "item_count": sum(len(s["items"]) for s in SIDEBAR_SECTIONS),
    }


@router.get("/mode-indicator")
async def get_mode_indicator() -> Dict[str, Any]:
    """Global + per-venue trading mode and kill-switch state.

    Used by the top-bar mode indicator badge across all views.
    """
    try:
        from merid.prediction.venue_gate import get_venue_gate
        gate = get_venue_gate()
        gate_summary = gate.summary()
    except Exception:
        gate_summary = {
            "mode": "sim",
            "live_enabled": False,
            "is_live": False,
        }

    try:
        from merid.prediction.risk import get_prediction_risk
        risk = get_prediction_risk()
        risk_summary = risk.summary()
        kill_switch = risk_summary.get("kill_switch_active", False)
    except Exception:
        kill_switch = False

    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        bridge = get_ws_bridge()
        ws_connected = bridge.summary().get("running", False)
    except Exception:
        ws_connected = False

    return {
        "global_mode": gate_summary.get("mode", "sim"),
        "live_enabled": gate_summary.get("live_enabled", False),
        "is_live": gate_summary.get("is_live", False),
        "kill_switch_active": kill_switch,
        "ws_connected": ws_connected,
        "venues": {
            "kalshi": {
                "mode": gate_summary.get("mode", "sim"),
                "ws_connected": ws_connected,
                "kill_switch": kill_switch,
            },
        },
    }


@router.get("/workflow")
async def get_workflow() -> Dict[str, Any]:
    """Workflow phase definitions with view assignments.

    Maps the end-to-end trading workflow:
    funding → discovery → strategy → execution → monitoring → analysis
    """
    return {
        "phases": WORKFLOW_PHASES,
        "phase_count": len(WORKFLOW_PHASES),
    }

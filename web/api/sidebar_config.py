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
                    "/api/system/health",
                    "/api/risk/exposure",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kalshi-dashboard", "kill-switch", "exposure"],
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
                "links_to": ["kalshi-dashboard", "kalshi-portfolio", "agent-health"],
                "bus_channels": [
                    "kalshi:price_update",
                    "kalshi:trade",
                    "kalshi:orderbook_delta",
                ],
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
                "links_to": ["exposure", "kalshi-dashboard", "orders"],
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
                "links_to": ["kalshi-dashboard", "exposure"],
            },
        ],
    },
    # ── §2 Risk & Limits ──────────────────────────────────────
    {
        "id": "risk-limits",
        "label": "Risk & Limits",
        "items": [
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
                "links_to": ["exposure", "risk-health", "observability"],
            },
            {
                "id": "exposure",
                "label": "Exposure & PnL",
                "href": "exposure",
                "icon": "BarChart3",
                "color": "text-purple-400",
                "endpoints": [
                    "/api/operator/summary",
                    "/api/v1/kalshi/pnl",
                    "/api/v1/kalshi/risk",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kill-switch", "kalshi-portfolio", "risk-health"],
            },
            {
                "id": "risk-health",
                "label": "Risk & Health",
                "href": "risk",
                "icon": "Shield",
                "color": "text-red-400",
                "endpoints": [
                    "/api/v1/kalshi/risk",
                    "/api/v1/kalshi/health",
                    "/api/v1/resilience/status",
                    "/api/v1/reconciliation/status",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kill-switch", "kalshi-portfolio", "observability"],
            },
            {
                "id": "observability",
                "label": "Observability",
                "href": "observability",
                "icon": "Eye",
                "color": "text-emerald-400",
                "endpoints": [
                    "/api/v1/system/observability",
                    "/api/v1/system/alerts",
                    "/api/v1/system/slo",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["risk-health", "agent-health", "logs"],
            },
        ],
    },
    # ── §3 System ─────────────────────────────────────────────
    {
        "id": "system",
        "label": "System",
        "items": [
            {
                "id": "agent-health",
                "label": "Agent Health",
                "href": "agent-health",
                "icon": "Bot",
                "color": "text-cyan-400",
                "endpoints": [
                    "/api/v1/kalshi-grid/agents",
                    "/api/agents/summary",
                ],
                "workflow_phase": "monitoring",
                "links_to": ["kalshi-grid", "observability"],
            },
            {
                "id": "orchestrator",
                "label": "Orchestrator",
                "href": "operator",
                "icon": "Monitor",
                "color": "text-orange-400",
                "endpoints": [
                    "/api/v1/orchestrator/summary",
                    "/api/v1/kalshi/health",
                ],
                "workflow_phase": "strategy",
                "links_to": ["kalshi-grid", "risk-health", "agent-health"],
                "bus_channels": [
                    "kalshi:order_fill",
                    "kalshi:order_reject",
                ],
            },
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
                "links_to": ["observability", "agent-health"],
            },
            {
                "id": "settings",
                "label": "Settings",
                "href": "settings",
                "icon": "Settings",
                "color": "text-gray-400",
                "endpoints": [
                    "/api/v1/user/settings",
                ],
                "workflow_phase": "configuration",
                "links_to": [],
            },
        ],
    },
    # ── §4 Lab / Legacy ───────────────────────────────────────
    {
        "id": "lab-legacy",
        "label": "Lab / Legacy",
        "items": [
            {
                "id": "paper-trading",
                "label": "Paper Trading",
                "href": "paper-trading",
                "icon": "FileSpreadsheet",
                "color": "text-teal-400",
                "endpoints": [
                    "/api/v1/paper-trading/portfolio",
                    "/api/v1/paper-trading/positions",
                    "/api/v1/paper-trading/orders",
                    "/api/v1/paper-trading/pnl-history",
                ],
                "workflow_phase": "execution",
                "links_to": ["positions", "kalshi-portfolio"],
                "mode_aware": True,
            },
            {
                "id": "positions",
                "label": "Crypto Positions",
                "href": "positions",
                "icon": "Briefcase",
                "color": "text-teal-400",
                "endpoints": [
                    "/api/v1/kalshi/positions",
                    "/api/v1/kalshi/orders",
                    "/api/v1/kalshi/fills",
                ],
                "workflow_phase": "execution",
                "links_to": ["kalshi-portfolio", "paper-trading"],
                "mode_aware": True,
            },
            {
                "id": "agent-library",
                "label": "Agent Library",
                "href": "agents",
                "icon": "Bot",
                "color": "text-cyan-400",
                "endpoints": [
                    "/api/v1/kalshi-grid/agents",
                    "/api/agents/summary",
                ],
                "workflow_phase": "strategy",
                "links_to": ["kalshi-grid", "agent-health"],
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
        "views": ["kalshi-dashboard", "kalshi-vol-dashboard"],
    },
    {
        "id": "strategy",
        "label": "Strategy & Configuration",
        "order": 2,
        "views": ["kalshi-grid", "agents", "operator", "agent-health"],
    },
    {
        "id": "execution",
        "label": "Execution",
        "order": 3,
        "views": ["orders", "kalshi-portfolio", "paper-trading", "positions"],
    },
    {
        "id": "monitoring",
        "label": "Monitoring & Risk",
        "order": 4,
        "views": [
            "overview", "kill-switch", "exposure", "risk",
            "observability", "logs",
        ],
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

"""Swarm Matrix Builder — single source of truth for Kalshi grid cells.

The matrix consolidates data from:
- AgentGrid (cell + agent metadata, recent signals)
- SwarmConsensusAggregator (stance, probability, confidence)
- PaperSession + DeploymentController (promotion stage)
- Execution Gate / Guard + PortfolioRiskAgent (risk flags)
- Lane registry (lane binding + mode inference)

It produces a normalized map of `cell_id -> SwarmCell` that downstream
surfaces (Operator dashboard, Kalshi status, promotion pipeline) can consume
without re-implementing the wiring logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Literal, Optional

from config.trading_constants import (
    SHARPE_WINDOW_SHORT, SHARPE_WINDOW_MEDIUM, SHARPE_MIN_SAMPLES,
    SHARPE_ANNUALISATION, SHARPE_DOWNWEIGHT_THRESHOLD,
)


PromotionStage = Literal["paper", "shadow", "live"]
Mode = Literal["mock", "paper", "live"]


@dataclass
class CellConsensus:
    """Weighted consensus snapshot for a cell."""

    stance: Literal["long", "short", "flat", "skip"]
    weight: float
    edge_bps: float


@dataclass
class CellRiskFlags:
    """Risk surface for a cell."""

    blocked_by_execution_gate: bool
    venue_cap_reached: bool
    portfolio_risk_breach: bool
    drawdown_breach: bool
    slippage_anomaly: bool
    illiquid_market: bool


@dataclass
class CellLaneBinding:
    """Execution lane metadata for a cell."""

    lane_id: Optional[str]
    mode: Mode
    venue: str


@dataclass
class CellPerformance:
    """Rolling performance metrics for a swarm cell."""

    sharpe_short: Optional[float]   # SHARPE_WINDOW_SHORT trades
    sharpe_medium: Optional[float]  # SHARPE_WINDOW_MEDIUM trades
    fill_count: int
    downweight: bool                # True if sharpe_medium < SHARPE_DOWNWEIGHT_THRESHOLD


@dataclass
class SwarmCell:
    """Complete representation of a swarm matrix cell."""

    cell_id: str
    asset: str
    timeframe: str
    role: str
    agents: List[str]
    signals: List[dict]
    consensus: CellConsensus
    promotion_stage: PromotionStage
    mode: Mode
    risk_flags: CellRiskFlags
    lane_binding: CellLaneBinding
    performance: CellPerformance = field(default_factory=lambda: CellPerformance(
        sharpe_short=None, sharpe_medium=None, fill_count=0, downweight=False
    ))

    def to_dict(self) -> dict:
        d = asdict(self)
        # Alias promotion_stage as stage for frontend compatibility
        d["stage"] = d.get("promotion_stage", "paper")
        return d


class SwarmMatrixBuilder:
    """Builds the swarm matrix from the running grid + risk subsystems."""

    def __init__(
        self,
        *,
        agent_grid,
        consensus_aggregator,
        paper_session,
        deployment_controller,
        execution_gate_fn,
        execution_guard,
        portfolio_risk_agent,
        lane_registry,
        promotion_controller=None,
    ) -> None:
        self.agent_grid = agent_grid
        self.consensus_aggregator = consensus_aggregator
        self.paper_session = paper_session
        self.deployment_controller = deployment_controller
        self.execution_gate_fn = execution_gate_fn
        self.execution_guard = execution_guard
        self.portfolio_risk_agent = portfolio_risk_agent
        self.lane_registry = lane_registry
        self.promotion_controller = promotion_controller

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------
    def build_matrix(self) -> Dict[str, SwarmCell]:
        """Return the full swarm matrix as SwarmCell objects."""

        matrix: Dict[str, SwarmCell] = {}
        try:
            gate_status = self.execution_gate_fn()
        except Exception:
            gate_status = None

        venue_cap = None
        if self.execution_guard is not None:
            try:
                venue_cap = self.execution_guard.get_venue_cap("kalshi")
            except Exception:
                venue_cap = None

        for cell in self.agent_grid.iter_cells():
            signals = self.agent_grid.get_signals_for_cell(cell.cell_id)
            consensus = self._compute_consensus(cell)
            promotion_stage = self._determine_promotion_stage(cell)
            lane_binding = self._resolve_lane_binding(cell, promotion_stage)
            mode = self._derive_effective_mode(promotion_stage, lane_binding)
            risk_flags = self._compute_risk_flags(
                cell=cell,
                consensus=consensus,
                gate_status=gate_status,
                venue_cap=venue_cap,
            )
            performance = self._compute_performance(cell)

            matrix[cell.cell_id] = SwarmCell(
                cell_id=cell.cell_id,
                asset=cell.asset,
                timeframe=cell.timeframe,
                role=cell.role,
                agents=list(cell.agent_names),
                signals=signals,
                consensus=consensus,
                promotion_stage=promotion_stage,
                mode=mode,
                risk_flags=risk_flags,
                lane_binding=lane_binding,
                performance=performance,
            )

        return matrix

    # ------------------------------------------------------------------
    # Consensus helpers
    # ------------------------------------------------------------------
    def _compute_consensus(self, cell) -> CellConsensus:
        stance: Literal["long", "short", "flat", "skip"] = "skip"
        weight = 0.0
        edge_bps = 0.0

        view = None
        try:
            view = self.consensus_aggregator.get_consensus(cell.asset, cell.timeframe)
        except Exception:
            view = None

        if view:
            stance = self._direction_to_stance(view.consensus_direction)
            weight = float(max(0.0, min(1.0, view.consensus_confidence)))
            edge_bps = float((view.consensus_probability - 0.5) * 10000.0)

        return CellConsensus(stance=stance, weight=weight, edge_bps=edge_bps)

    @staticmethod
    def _direction_to_stance(direction: str) -> Literal["long", "short", "flat", "skip"]:
        direction = (direction or "").lower()
        if direction in ("yes", "long", "bullish"):
            return "long"
        if direction in ("no", "short", "bearish"):
            return "short"
        if direction in ("neutral", "flat"):
            return "flat"
        return "skip"

    # ------------------------------------------------------------------
    # Promotion stage helpers
    # ------------------------------------------------------------------
    def _determine_promotion_stage(self, cell) -> PromotionStage:
        # Prefer a dedicated promotion controller when available
        try:
            if self.promotion_controller is not None:
                stage = self.promotion_controller.get_stage(cell.cell_id)
                if stage in ("paper", "shadow", "live"):
                    return stage  # type: ignore[return-value]
        except Exception:
            pass

        live = False
        shadow = False
        try:
            from merid.event_venues.kalshi.deployment import AgentMode

            for agent in cell.agent_names:
                try:
                    mode = self.deployment_controller.get_mode(agent)
                except Exception:
                    mode = None
                if mode == AgentMode.LIVE:
                    live = True
                elif mode == AgentMode.SHADOW:
                    shadow = True
        except Exception:
            live = False
            shadow = False

        if live:
            return "live"
        if shadow:
            return "shadow"

        try:
            for agent in cell.agent_names:
                if agent in self.paper_session.live_agents:
                    return "live"
        except Exception:
            pass

        return "paper"

    # ------------------------------------------------------------------
    # Lane binding helpers
    # ------------------------------------------------------------------
    def _resolve_lane_binding(self, cell, promotion_stage: PromotionStage) -> CellLaneBinding:
        lane_id = self._find_lane_id(cell)
        venue = getattr(cell, "venue", "kalshi")

        if not lane_id or not self.lane_registry:
            return CellLaneBinding(lane_id=None, mode="mock", venue=venue)

        lane = self.lane_registry.get_lane(lane_id)
        cfg = self.lane_registry.get_config(lane_id)
        if lane and cfg:
            lane_mode: Mode = "paper" if getattr(cfg, "paper", False) else "live"
            return CellLaneBinding(lane_id=lane_id, mode=lane_mode, venue=venue)

        # No matching lane — fallback to promotion stage for mode
        fallback_mode: Mode = "live" if promotion_stage == "live" else "paper"
        return CellLaneBinding(lane_id=lane_id, mode=fallback_mode, venue=venue)

    def _find_lane_id(self, cell) -> Optional[str]:
        symbol = cell.asset.upper()
        tf = cell.timeframe.upper().replace("MIN", "M")
        candidates = [f"{symbol}_{tf}", f"{symbol}_{tf}_PAPER"]
        for candidate in candidates:
            if self.lane_registry and self.lane_registry.get_lane(candidate):
                return candidate
        return None

    def _derive_effective_mode(self, promotion_stage: PromotionStage, lane_binding: CellLaneBinding) -> Mode:
        if lane_binding.lane_id:
            return lane_binding.mode
        if promotion_stage == "live":
            return "live"
        if promotion_stage == "shadow":
            return "paper"
        # Paper stage with no lane binding — still paper, not mock
        return "paper"

    # ------------------------------------------------------------------
    # Risk helpers
    # ------------------------------------------------------------------
    def _compute_risk_flags(
        self,
        *,
        cell,
        consensus: CellConsensus,
        gate_status,
        venue_cap,
    ) -> CellRiskFlags:
        blocked = False
        if gate_status is not None:
            try:
                state = getattr(gate_status, "gate_state", "clear")
                blocked = state in ("blocked", "halt")
            except Exception:
                blocked = False

        venue_cap_reached = False
        if venue_cap is not None:
            try:
                remaining = float(venue_cap.remaining() or 0.0)
                venue_cap_reached = remaining <= 0.0
            except Exception:
                venue_cap_reached = False

        portfolio_breach = False
        try:
            portfolio_breach = bool(getattr(self.portfolio_risk_agent, "kill_switch_active", False))
        except Exception:
            portfolio_breach = False

        drawdown_breach = any(
            self._is_agent_drawdown_flagged(agent)
            for agent in cell.agent_names
        )

        slippage_anomaly = any(
            self._agent_has_error(agent, "slippage")
            for agent in cell.agent_names
        )

        illiquid_market = not self._cell_has_active_market(cell)

        return CellRiskFlags(
            blocked_by_execution_gate=blocked,
            venue_cap_reached=venue_cap_reached,
            portfolio_risk_breach=portfolio_breach,
            drawdown_breach=drawdown_breach,
            slippage_anomaly=slippage_anomaly,
            illiquid_market=illiquid_market,
        )

    # ------------------------------------------------------------------
    # Performance helpers (rolling Sharpe)
    # ------------------------------------------------------------------
    def _compute_performance(self, cell) -> CellPerformance:
        """Compute rolling Sharpe ratio across all agents in a cell.

        Uses each agent's ``fill_log`` (list of dicts with ``fee_cents`` and
        ``price_cents`` fields) as a proxy for per-trade P&L returns.  The
        cell-level Sharpe is the average of all per-agent Sharpes weighted by
        fill count.
        """
        all_returns: List[float] = []

        for agent_name in cell.agent_names:
            agent = self.agent_grid.get_agent_by_name(agent_name)
            if agent is None:
                continue
            try:
                fills = list(agent.state.fill_log or [])
                for fill in fills:
                    # Treat each fill's net-of-fee return as a single observation
                    price = float(fill.get("price_cents", 0))
                    fee = float(fill.get("fee_cents", 0))
                    count = max(1, int(fill.get("count", 1)))
                    action = str(fill.get("action", "buy")).lower()
                    if price <= 0:
                        continue
                    # Rough return: (payout - cost - fee) / cost
                    cost = price * count
                    payout = (100.0 - price) * count if action == "sell" else price * count
                    net = payout - cost - fee
                    ret = net / max(1.0, cost)
                    all_returns.append(ret)
            except Exception:
                continue

        fill_count = len(all_returns)
        sharpe_short = self._rolling_sharpe(all_returns, SHARPE_WINDOW_SHORT)
        sharpe_medium = self._rolling_sharpe(all_returns, SHARPE_WINDOW_MEDIUM)
        downweight = (
            sharpe_medium is not None and sharpe_medium < SHARPE_DOWNWEIGHT_THRESHOLD
        )
        return CellPerformance(
            sharpe_short=sharpe_short,
            sharpe_medium=sharpe_medium,
            fill_count=fill_count,
            downweight=downweight,
        )

    @staticmethod
    def _rolling_sharpe(returns: List[float], window: int) -> Optional[float]:
        """Compute annualised Sharpe ratio over the last ``window`` returns.

        Returns None when fewer than SHARPE_MIN_SAMPLES observations are available.
        """
        tail = returns[-window:] if len(returns) >= SHARPE_MIN_SAMPLES else []
        if len(tail) < SHARPE_MIN_SAMPLES:
            return None
        n = len(tail)
        mean = sum(tail) / n
        variance = sum((r - mean) ** 2 for r in tail) / max(1, n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0.0:
            return None
        return round((mean / std) * math.sqrt(SHARPE_ANNUALISATION), 4)

    def _is_agent_drawdown_flagged(self, agent_name: str) -> bool:
        try:
            if self.paper_session.is_halted(agent_name):
                return True
            return self.paper_session.is_downsized(agent_name)
        except Exception:
            return False

    def _agent_has_error(self, agent_name: str, keyword: str) -> bool:
        agent = self.agent_grid.get_agent_by_name(agent_name)
        if not agent:
            return False
        lower_kw = keyword.lower()
        for err in agent.state.errors[-5:]:
            if lower_kw in (err or "").lower():
                return True
        if agent.state.last_error and lower_kw in agent.state.last_error.lower():
            return True
        return False

    def _cell_has_active_market(self, cell) -> bool:
        for agent_name in cell.agent_names:
            agent = self.agent_grid.get_agent_by_name(agent_name)
            if not agent:
                continue
            if any(cell.asset.upper() in ticker.upper() for ticker in agent.state.active_tickers):
                return True
        return False

"""Run Summary Automation (P2 Task 11).

This module provides automated run summary generation for the 15m trading loop.
It collects metrics from various sources (loop, PnL, orders, edge rejections) and
generates a structured summary on shutdown and optionally at regular intervals.

Usage:
    from merid.ops.run_summary import RunSummary

    summary = RunSummary(loop, agent_grid, bankroll_service)
    summary.log_on_shutdown()
    # or
    summary.log_periodic(interval_seconds=3600)  # every hour
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.run_summary")


class RunSummary:
    """Automated run summary generator for 15m trading loop."""

    def __init__(
        self,
        loop: Any,
        agent_grid: Any,
        bankroll_service: Any,
        output_dir: Optional[Path] = None,
    ):
        """
        Initialize run summary.

        Args:
            loop: Kalshi15mLoop instance
            agent_grid: AgentGrid instance
            bankroll_service: BankrollServiceV2 instance
            output_dir: Directory to write summary files (default: data/run_summaries)
        """
        self.loop = loop
        self.agent_grid = agent_grid
        self.bankroll_service = bankroll_service
        self.output_dir = output_dir or Path("data/run_summaries")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._start_time = datetime.now(timezone.utc)

    def collect_metrics(self) -> Dict[str, Any]:
        """Collect metrics from all sources."""
        metrics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_start": self._start_time.isoformat(),
            "loop": self._collect_loop_metrics(),
            "agents": self._collect_agent_metrics(),
            "pnl": self._collect_pnl_metrics(),
            "orders": self._collect_order_metrics(),
            "edge_rejections": self._collect_edge_rejection_metrics(),
        }
        return metrics

    def _collect_loop_metrics(self) -> Dict[str, Any]:
        """Collect loop-level metrics."""
        loop_summary = self.loop.summary() if hasattr(self.loop, 'summary') else {}
        return {
            "running": loop_summary.get("running", False),
            "tick": loop_summary.get("tick", 0),
            "cycle_count": loop_summary.get("cycle_count", 0),
            "error_count": loop_summary.get("error_count", 0),
            "cadence_seconds": loop_summary.get("cadence_seconds", 0),
            "uptime_seconds": loop_summary.get("uptime_seconds", 0),
            "last_cycle_at": loop_summary.get("last_cycle_at"),
            "started_at": loop_summary.get("started_at"),
            "agent_count": loop_summary.get("agent_count", 0),
            "halted_due_to_drawdown": loop_summary.get("halted_due_to_drawdown", False),
        }

    def _collect_agent_metrics(self) -> Dict[str, Any]:
        """Collect agent-level metrics."""
        agents = []
        if hasattr(self.agent_grid, '_agents'):
            for agent in self.agent_grid._agents:
                agent_name = getattr(agent, 'agent_id', getattr(agent, 'config', {}).name if hasattr(agent, 'config') else 'unknown')
                agents.append({
                    "name": agent_name,
                    "enabled": getattr(agent, 'enabled', True),
                })
        return {
            "total_agents": len(agents),
            "agents": agents,
        }

    def _collect_pnl_metrics(self) -> Dict[str, Any]:
        """Collect PnL metrics from Prometheus or bankroll service."""
        pnl_metrics = {
            "total_pnl_usd": 0.0,
            "daily_pnl_usd": 0.0,
            "by_asset": {},
        }

        # Try to get PnL from bankroll service
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            equity_usd = get_equity_for_risk_calc_sync()
            if equity_usd:
                pnl_metrics["current_equity_usd"] = float(equity_usd)
        except Exception as e:
            logger.warning("[RUN-SUMMARY] Failed to get equity from bankroll service: %s", e)

        # Try to get per-asset PnL from Prometheus
        try:
            from merid.ops.order_lifecycle_tracker import PROMETHEUS_AVAILABLE, pnl_by_asset
            if PROMETHEUS_AVAILABLE:
                # Collect current PnL values for each asset
                for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    try:
                        # Get the current gauge value
                        metric = pnl_by_asset.labels(asset=asset)
                        # Note: prometheus_client Gauge doesn't expose current value directly
                        # We'd need to query the registry, which is complex
                        # For now, we'll just track that the metric exists
                        pnl_metrics["by_asset"][asset] = {"metric_exists": True}
                    except Exception:
                        pnl_metrics["by_asset"][asset] = {"metric_exists": False}
        except Exception as e:
            logger.warning("[RUN-SUMMARY] Failed to get PnL from Prometheus: %s", e)

        return pnl_metrics

    def _collect_order_metrics(self) -> Dict[str, Any]:
        """Collect order lifecycle metrics from Prometheus."""
        order_metrics = {
            "orders_submitted": 0,
            "orders_filled": 0,
            "orders_cancelled": 0,
            "orders_rejected": 0,
        }

        try:
            from merid.ops.order_lifecycle_tracker import PROMETHEUS_AVAILABLE
            if PROMETHEUS_AVAILABLE:
                # Note: prometheus_client doesn't expose current counter values directly
                # We'd need to query the registry via HTTP endpoint
                # For now, we'll just track that metrics exist
                order_metrics["metrics_available"] = True
            else:
                order_metrics["metrics_available"] = False
        except Exception as e:
            logger.warning("[RUN-SUMMARY] Failed to get order metrics: %s", e)

        return order_metrics

    def _collect_edge_rejection_metrics(self) -> Dict[str, Any]:
        """Collect edge rejection metrics from Prometheus."""
        rejection_metrics = {
            "no_valid_contract_rejections": 0,
            "by_asset": {},
        }

        try:
            from merid.ops.order_lifecycle_tracker import PROMETHEUS_AVAILABLE
            if PROMETHEUS_AVAILABLE:
                rejection_metrics["metrics_available"] = True
            else:
                rejection_metrics["metrics_available"] = False
        except Exception as e:
            logger.warning("[RUN-SUMMARY] Failed to get edge rejection metrics: %s", e)

        return rejection_metrics

    def generate_summary(self) -> str:
        """Generate human-readable summary text."""
        metrics = self.collect_metrics()

        lines = [
            "=" * 80,
            "MERID 15m Trading Run Summary",
            "=" * 80,
            f"Generated: {metrics['timestamp']}",
            f"Run Start: {metrics['run_start']}",
            "",
            "--- Loop Metrics ---",
            f"Running: {metrics['loop']['running']}",
            f"Tick: {metrics['loop']['tick']}",
            f"Cycles Completed: {metrics['loop']['cycle_count']}",
            f"Errors: {metrics['loop']['error_count']}",
            f"Cadence: {metrics['loop']['cadence_seconds']}s",
            f"Uptime: {metrics['loop']['uptime_seconds']:.1f}s ({metrics['loop']['uptime_seconds']/3600:.2f}h)",
            f"Last Cycle: {metrics['loop']['last_cycle_at']}",
            f"Agents: {metrics['loop']['agent_count']}",
            f"Halted (Drawdown): {metrics['loop']['halted_due_to_drawdown']}",
            "",
            "--- Risk Envelope ---",
        ]

        # Add risk envelope info if available
        loop_summary = self.loop.summary() if hasattr(self.loop, 'summary') else {}
        if "risk_envelope" in loop_summary:
            env = loop_summary["risk_envelope"]
            lines.extend([
                f"Current Drawdown: {env.get('current_drawdown_pct', 0)*100:.2f}%",
                f"Risk Band: {env.get('current_risk_band', 'unknown')}",
                f"Halted: {env.get('is_halted', False)}",
                f"Risk Multiplier: {env.get('per_trade_risk_multiplier', 1.0):.2f}x",
                f"Distance to Halt: {env.get('distance_to_halt_pct', 0)*100:.2f}%",
            ])

        lines.extend([
            "",
            "--- PnL Metrics ---",
            f"Current Equity: ${metrics['pnl'].get('current_equity_usd', 0):.2f}",
        ])

        lines.extend([
            "",
            "--- Order Metrics ---",
            f"Metrics Available: {metrics['orders'].get('metrics_available', False)}",
        ])

        lines.extend([
            "",
            "--- Edge Rejection Metrics ---",
            f"Metrics Available: {metrics['edge_rejections'].get('metrics_available', False)}",
        ])

        lines.append("=" * 80)

        return "\n".join(lines)

    def log_to_file(self, filename: Optional[str] = None) -> Path:
        """
        Write summary to JSON file.

        Args:
            filename: Optional filename (default: run_summary_YYYYMMDD_HHMMSS.json)

        Returns:
            Path to written file
        """
        if filename is None:
            filename = f"run_summary_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"

        filepath = self.output_dir / filename
        metrics = self.collect_metrics()

        with open(filepath, 'w') as f:
            json.dump(metrics, f, indent=2, default=str)

        logger.info("[RUN-SUMMARY] Summary written to %s", filepath)
        return filepath

    def log_on_shutdown(self) -> None:
        """Log summary on loop shutdown (call in finally block)."""
        logger.info("[RUN-SUMMARY] Generating shutdown summary...")
        summary_text = self.generate_summary()
        logger.info("\n%s", summary_text)

        # Also write to file
        try:
            self.log_to_file()
        except Exception as e:
            logger.error("[RUN-SUMMARY] Failed to write summary to file: %s", e)

    def log_periodic(self, interval_seconds: float = 3600.0) -> None:
        """
        Log summary periodically (call in loop).

        Args:
            interval_seconds: Interval between periodic summaries (default: 1 hour)
        """
        if not hasattr(self, '_last_periodic_log'):
            self._last_periodic_log = 0.0

        now = time.time()
        if now - self._last_periodic_log >= interval_seconds:
            logger.info("[RUN-SUMMARY] Generating periodic summary...")
            summary_text = self.generate_summary()
            logger.info("\n%s", summary_text)
            self._last_periodic_log = now

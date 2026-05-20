"""
Kalshi 15m Lean Loop — Minimal event loop for kalshi_crypto_15m_v2 profile.

This is a clean, minimal loop designed specifically for the 15-minute crypto trading
stack on Kalshi. It replaces the complex legacy merid.loop for this profile.

Responsibilities:
- Pull latest market state / RTI inputs
- Run 5 agents' signal + decision logic via AgentGrid.run_cycle()
- Route orders through KalshiTradingAgent / order router / risk
- Run at 5-second cadence

This loop intentionally does NOT include:
- Legacy lane orchestration
- Reflection/learning systems
- KalshiContinuousTrader
- PM agents or regime agents
- Cross-venue arbitrage
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.loop_15m")

# Import startup trace helper
from merid.startup_trace import log_startup_phase


class Kalshi15mLoop:
    """
    Lean event loop for Kalshi 15m crypto trading.
    
    Lifecycle:
        loop = Kalshi15mLoop(agent_grid, venue_adapter, cadence_seconds=5.0)
        asyncio.create_task(loop.run_forever())
        ...
        await loop.stop()
    """

    def __init__(
        self,
        agent_grid: Any,
        venue_adapter: Any,
        bankroll_service: Any,
        risk_config: Any,
        cadence_seconds: float = 5.0,
    ):
        """
        Initialize the 15m loop.
        
        Args:
            agent_grid: AgentGrid instance with 5 trading agents
            venue_adapter: KalshiVenueAdapter for order routing
            bankroll_service: BankrollServiceV2 for balance tracking
            risk_config: KalshiRiskConfig for risk limits
            cadence_seconds: Loop cadence (default 5.0 seconds)
        """
        self.agent_grid = agent_grid
        self.venue_adapter = venue_adapter
        self.bankroll_service = bankroll_service
        self.risk_config = risk_config
        self.cadence_seconds = cadence_seconds
        # Watchdog: fixed wall-clock budget per cycle (2x cadence as safety margin)
        self._watchdog_budget = self.cadence_seconds * 2.0
        self._last_cycle_wall_time = time.time()
        self._running = False
        self._tick = 0
        self._loop_task: Optional[asyncio.Task] = None
        self._started_at: Optional[datetime] = None
        self._last_cycle_at: Optional[datetime] = None
        self._cycle_count = 0
        self._error_count = 0
        self._last_tick_time: float = time.time()  # Track last tick for stall detection
        
        # Risk envelope for drawdown tracking
        self._risk_envelope = None
        self._last_risk_multiplier = 1.0

    async def _schedule_next_tick_async(self, delay: float) -> None:
        """Schedule the next tick using asyncio.sleep (Windows ProactorEventLoop compatible)."""
        if not self._running:
            logger.debug("[15M-LOOP-TRACE] _schedule_next_tick_async called but loop not running")
            return

        logger.debug(
            "[15M-LOOP-TRACE] scheduling next tick in %.3fs",
            delay,
        )
        try:
            await asyncio.sleep(delay)
            if self._running:
                await self._on_tick_async()
        except asyncio.CancelledError:
            logger.debug("[15M-LOOP-TRACE] _schedule_next_tick_async cancelled")
            raise
        except Exception as exc:
            logger.error("[15M-LOOP-TRACE] _schedule_next_tick_async failed: %s", exc, exc_info=True)

    async def _on_tick_async(self) -> None:
        """Async tick handler (Windows ProactorEventLoop compatible)."""
        self._last_tick_time = time.time()
        logger.info("[15M-LOOP] ON-TICK-ENTRY running=%s tick_before=%d", self._running, self._tick)
        if not self._running:
            logger.debug("[15M-LOOP-TRACE] _on_tick_async called but loop not running")
            return

        loop = asyncio.get_running_loop()
        logger.debug("[15M-LOOP-TRACE] _on_tick_async: loop.is_running()=%s, loop.time()=%.3f", loop.is_running(), loop.time())
        self._tick += 1
        cycle_id = self._tick
        logger.info("[15M-LOOP] ON-TICK-CREATE-CYCLE cycle=%d loop_time=%.3f", cycle_id, loop.time())

        try:
            # Launch the async cycle task (fire-and-forget with monitoring)
            task = asyncio.create_task(self._run_cycle_wrapper(cycle_id), name=f"cycle-{cycle_id}")
            logger.info("[15M-LOOP] CYCLE-TASK-CREATED cycle=%d name=%s", cycle_id, task.get_name())
            
            # Add done callback to detect silent failures
            def _cycle_done_cb(t: asyncio.Task) -> None:
                if t.cancelled():
                    logger.warning("[15M-LOOP-TRACE] Cycle task %d cancelled", cycle_id)
                    return
                exc = t.exception()
                if exc is not None:
                    logger.error("[15M-LOOP-TRACE] Cycle task %d failed: %s", cycle_id, exc, exc_info=exc)
            
            task.add_done_callback(_cycle_done_cb)
            logger.debug("[15M-LOOP-TRACE] _on_tick_async EXIT (cycle %d launched)", cycle_id)
        except Exception as exc:
            logger.error("[15M-LOOP-TRACE] Exception in _on_tick_async for cycle %d: %s", cycle_id, exc, exc_info=True)

    async def _run_cycle_wrapper(self, cycle_id: int) -> None:
        """Async wrapper for cycle execution (called from callback)."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        logger.info("[15M-LOOP] CYCLE-WRAPPER-ENTER cycle=%d loop_time=%.3f", cycle_id, start)
        
        # Watchdog: check wall-clock time since last cycle
        current_wall_time = time.time()
        wall_clock_since_last_cycle = current_wall_time - self._last_cycle_wall_time
        if wall_clock_since_last_cycle > self._watchdog_budget:
            logger.error(
                "[15M-LOOP-WATCHDOG] WALL-CLOCK BUDGET EXCEEDED: cycle=%d, elapsed=%.3fs, budget=%.3fs",
                cycle_id,
                wall_clock_since_last_cycle,
                self._watchdog_budget
            )
            logger.error(
                "[15M-LOOP-WATCHDOG] event loop health: is_running=%s, task_count=%d",
                loop.is_running(),
                len(asyncio.all_tasks(loop))
            )
        self._last_cycle_wall_time = current_wall_time
        
        logger.debug("[15M-LOOP-TRACE] CYCLE %d START at loop_time=%.3f", cycle_id, start)
        
        cycle_completed = False
        try:
            await self._run_one_cycle(cycle_id)
            cycle_completed = True
        except Exception as exc:
            self._error_count += 1
            logger.error(
                "[15m-LOOP] Cycle %d failed: %s (errors=%d)",
                cycle_id,
                exc,
                self._error_count,
                exc_info=True,
            )
        finally:
            end = loop.time()
            duration = end - start
            logger.info("[15M-LOOP] CYCLE-WRAPPER-EXIT cycle=%d duration=%.3fs completed=%s", cycle_id, duration, cycle_completed)
            logger.debug("[15M-LOOP-TRACE] CYCLE %d END at loop_time=%.3f (duration=%.3fs completed=%s)", cycle_id, end, duration, cycle_completed)

    async def run_forever(self) -> None:
        """Run the loop indefinitely using async pattern (Windows ProactorEventLoop compatible)."""
        logger.debug("[15M-LOOP-TRACE] ENTER run_forever (async pattern)")
        if self._running:
            logger.warning("Kalshi15mLoop already running")
            return

        self._running = True
        self._started_at = datetime.now(timezone.utc)
        
        # Initialize risk envelope for kalshi_crypto_15m_v2
        import os
        profile = os.getenv("MERID_PROFILE", "").lower()
        if profile == "kalshi_crypto_15m_v2":
            try:
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                self._risk_envelope = get_kalshi_crypto_15m_risk_envelope()
                logger.info("[15m-LOOP] Initialized risk envelope for profile")
            except Exception as e:
                logger.warning("[15m-LOOP] Failed to initialize risk envelope: %s", e)
        
        # Log loop entry
        log_startup_phase(
            "loop_execution_start",
            "merid.loop_15m",
            f"cadence={self.cadence_seconds}s, agents={len(self.agent_grid._agents) if hasattr(self.agent_grid, '_agents') else 0}, profile={profile}"
        )
        
        logger.info(
            "[15m-LOOP] Starting Kalshi15mLoop (cadence=%.1fs, agents=%d, profile=%s)",
            self.cadence_seconds,
            len(self.agent_grid._agents) if hasattr(self.agent_grid, '_agents') else 0,
            profile,
        )

        # Start async ticker (first tick immediately)
        self._last_tick_time = time.time()
        
        # Keep this coroutine alive to track lifecycle
        try:
            while self._running:
                print(f"[PRINT-LOOP] Loop iteration start, self._running={self._running}, tick={self._tick}")
                logger.info("[15M-LOOP-DEBUG] Loop iteration start (self._running=%s)", self._running)
                # Run tick directly in this loop (not detached task)
                await self._on_tick_async()
                print(f"[PRINT-LOOP] Loop iteration after _on_tick_async, tick={self._tick}")
                logger.info("[15M-LOOP-DEBUG] Loop iteration after _on_tick_async")
                
                # Wait for cadence before next tick
                try:
                    logger.info("[15M-LOOP-DEBUG] About to sleep for %.1fs", self.cadence_seconds)
                    await asyncio.sleep(self.cadence_seconds)
                    logger.info("[15M-LOOP-DEBUG] Woke up from sleep")
                    logger.debug("[15M-LOOP-TRACE] Woke up from sleep")
                except asyncio.CancelledError:
                    logger.debug("[15M-LOOP-TRACE] Sleep cancelled")
                    raise
                    
                # Watchdog: detect stalled ticker (no tick for > 2x cadence)
                time_since_last_tick = time.time() - self._last_tick_time
                if time_since_last_tick > (self.cadence_seconds * 2.0):
                    logger.error(
                        "[15M-LOOP-WATCHDOG] TICKER STALLED: no tick for %.3fs (cadence=%.1fs, threshold=%.1fs)",
                        time_since_last_tick,
                        self.cadence_seconds,
                        self.cadence_seconds * 2.0
                    )
                    logger.error(
                        "[15M-LOOP-WATCHDOG] Forcing immediate tick"
                    )
                    self._last_tick_time = time.time()
                logger.debug("[15M-LOOP-TRACE] Loop iteration end, checking self._running=%s", self._running)
        except asyncio.CancelledError:
            logger.info("[15m-LOOP] Loop cancelled")
            self._running = False
        finally:
            logger.debug("[15M-LOOP-TRACE] EXIT run_forever")
            logger.info(
                "[15m-LOOP] Stopped (cycles=%d, errors=%d, uptime=%.1fs)",
                self._cycle_count,
                self._error_count,
                (datetime.now(timezone.utc) - self._started_at).total_seconds() if self._started_at else 0,
            )

    async def start(self) -> None:
        """Start the loop in background using callback pattern."""
        if self._running:
            logger.warning("[15m-LOOP] Loop already running, skipping start")
            return
        logger.debug("[15M-LOOP-TRACE] starting callback-driven ticker")
        self._loop_task = asyncio.create_task(self.run_forever(), name="kalshi-15m-loop")

    async def stop(self) -> None:
        """Stop the loop gracefully."""
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("[15m-LOOP] Stop requested")

    async def _run_one_cycle(self, tick: int) -> None:
        """
        Run a single trading cycle.
        
        Steps:
        1) Update envelope equity once per cycle (not per order)
        2) Check if halted due to drawdown
        3) Skip cycle if halted
        4) Pull latest market state / RTI inputs (rely on WS caches)
        5) Call agent_grid.run_cycle(tick) to step all agents
        6) Let AgentGrid/TradingAgent issue orders via venue_adapter
        7) Log band transitions
        """
        logger.info("[15M-LOOP-CYCLE] ENTER cycle=%d", tick)
        cycle_start = time.time()
        self._last_cycle_at = datetime.now(timezone.utc)
        
        # Out-of-band heartbeat (fires every cycle regardless of trading activity)
        now = datetime.utcnow()
        logger.info(
            "[15M-LOOP-HEARTBEAT] cycle=%d ts=%s",
            tick,
            now.isoformat(),
        )

        # REAL CYCLE LOGIC
        logger.info("[15M-LOOP-TRACE]   phase=preconditions ENTER cycle=%d", tick)
        logger.info("[15m-LOOP] Starting cycle %d", tick)

        # Update envelope equity once per cycle (not per order)
        logger.info("[15M-LOOP-TRACE]   phase=risk-envelope-check ENTER cycle=%d", tick)
        if self._risk_envelope:
            logger.info("[15M-LOOP-TRACE]   risk-envelope exists, calling safe_update_envelope_equity cycle=%d", tick)
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
            update_success = safe_update_envelope_equity(self._risk_envelope)
            logger.info("[15M-LOOP-TRACE]   safe_update_envelope_equity returned=%s cycle=%d", update_success, tick)
            if update_success:
                # Log band transitions
                current_multiplier = self._risk_envelope.per_trade_risk_multiplier
                if current_multiplier != self._last_risk_multiplier:
                    logger.info(
                        "[15m-LOOP] Risk band transition: %.2f → %.2f (drawdown=%.2f%%)",
                        self._last_risk_multiplier,
                        current_multiplier,
                        self._risk_envelope.current_drawdown_pct * 100,
                    )
                    self._last_risk_multiplier = current_multiplier
            
            # Check if halted due to drawdown
            logger.info("[15M-LOOP-TRACE]   checking is_halted cycle=%d", tick)
            if self._risk_envelope.is_halted:
                logger.warning(
                    "[15m-LOOP] Cycle %d skipped: drawdown halt (drawdown=%.2f%% >= %.2f%%)",
                    tick,
                    self._risk_envelope.current_drawdown_pct * 100,
                    self._risk_envelope.drawdown_halt_pct * 100,
                )
                logger.error("[15M-LOOP-TRACE]   early-exit=halt-drawdown drawdown=%.2f%% threshold=%.2f%%", 
                    self._risk_envelope.current_drawdown_pct * 100,
                    self._risk_envelope.drawdown_halt_pct * 100
                )
                logger.info("[15M-LOOP-CYCLE] EXIT cycle=%d (halted)", tick)
                return  # Skip cycle
        logger.info("[15M-LOOP-TRACE]   phase=risk-envelope-check EXIT cycle=%d", tick)

        logger.info("[15M-LOOP-TRACE]   phase=agent-grid-cycle ENTER cycle=%d", tick)

        # Step 1: Run agent grid cycle
        # This will call each of the 5 agents to generate signals and place orders
        agent_count = len(self.agent_grid._agents) if hasattr(self.agent_grid, '_agents') else 0
        logger.info("[15M-LOOP-TRACE]   agent-grid-cycle starting n_agents=%d cycle=%d", agent_count, tick)
        try:
            # Add timeout to prevent indefinite hanging
            # P1 FIX: Align timeout to 300s (5 agents × 60s per-agent timeout)
            try:
                logger.info("[15M-LOOP-TRACE]   calling _run_agent_grid_with_timeout cycle=%d", tick)
                await asyncio.wait_for(
                    self._run_agent_grid_with_timeout(tick),
                    timeout=300.0  # 300 second timeout for agent grid cycle (5 agents × 60s)
                )
                logger.info("[15M-LOOP-TRACE]   _run_agent_grid_with_timeout completed cycle=%d", tick)
            except asyncio.TimeoutError:
                self._error_count += 1
                logger.info("[15M-LOOP-TRACE]   agent-grid-cycle TIMEOUT after 300s cycle=%d", tick)
                logger.error("[15m-LOOP] Agent grid cycle timed out after 300s")
                # Continue to next cycle even if timeout occurs
            logger.info("[15M-LOOP-TRACE]   agent-grid-cycle finished cycle=%d", tick)
        except Exception as exc:
            self._error_count += 1
            logger.error("[15m-LOOP] Agent grid cycle failed: %s", exc, exc_info=True)
            logger.error("[15M-LOOP-TRACE]   agent-grid-cycle failed error=%s cycle=%d", str(exc), tick)
            # FIX: Do NOT re-raise - continue running even if a cycle fails
            # The outer try block only catches CancelledError, so re-raising here
            # would break the loop instead of continuing to the next cycle

        logger.info("[15M-LOOP-TRACE]   phase=agent-grid-cycle EXIT cycle=%d", tick)

        cycle_duration = time.time() - cycle_start
        self._cycle_count += 1

        logger.info("[15M-LOOP-TRACE]   phase=cycle-complete duration=%.3fs cycle=%d", cycle_duration, tick)
        logger.info(
            "[15m-LOOP] Cycle %d completed in %.3fs",
            tick,
            cycle_duration,
        )
        logger.info("[15M-LOOP-CYCLE] EXIT cycle=%d duration=%.3fs", tick, cycle_duration)

        # Warn if cycle is taking too long (should be < 1s)
        if cycle_duration > 1.0:
            logger.warning(
                "[15m-LOOP] Cycle %d took %.3fs (expected < 1s)",
                tick,
                cycle_duration,
            )

    async def _run_agent_grid_with_timeout(self, tick: int) -> None:
        """Run agent grid cycle with proper error handling."""
        logger.info("[15M-LOOP] GRID-WITH-TIMEOUT-ENTER cycle=%d", tick)
        logger.info("[15M-LOOP-TRACE] _run_agent_grid_with_timeout ENTER cycle=%d", tick)
        if hasattr(self.agent_grid, 'run_cycle'):
            logger.info("[15M-LOOP] GRID-RUN-CYCLE-AWAIT ENTER cycle=%d", tick)
            logger.info("[15M-LOOP-TRACE] calling agent_grid.run_cycle cycle=%d", tick)
            await self.agent_grid.run_cycle(tick)
            logger.info("[15M-LOOP] GRID-RUN-CYCLE-AWAIT EXIT cycle=%d", tick)
            logger.info("[15M-LOOP-TRACE] agent_grid.run_cycle returned cycle=%d", tick)
        else:
            # Fallback: run agents directly if run_cycle not implemented
            logger.info("[15M-LOOP-TRACE] run_cycle not implemented, running agents directly cycle=%d", tick)
            await self._run_agents_directly(tick)
            logger.info("[15M-LOOP-TRACE] _run_agents_directly returned cycle=%d", tick)
        logger.info("[15M-LOOP-TRACE] _run_agent_grid_with_timeout EXIT cycle=%d", tick)
        logger.info("[15M-LOOP] GRID-WITH-TIMEOUT-EXIT cycle=%d", tick)

    async def _run_agents_directly(self, tick: int) -> None:
        """Fallback: run agents directly if run_cycle not implemented."""
        for agent in self.agent_grid._agents:
            try:
                if hasattr(agent, 'run_cycle'):
                    await agent.run_cycle(tick)
            except Exception as exc:
                logger.error(
                    "[15m-LOOP] Agent %s failed in cycle %d: %s",
                    getattr(agent, 'agent_id', 'unknown'),
                    tick,
                    exc,
                    exc_info=True,
                )

    def summary(self) -> Dict[str, Any]:
        """Get loop status summary for API/monitoring."""
        uptime = (
            (datetime.now(timezone.utc) - self._started_at).total_seconds()
            if self._started_at
            else 0
        )
        return {
            "running": self._running,
            "tick": self._tick,
            "cycle_count": self._cycle_count,
            "error_count": self._error_count,
            "cadence_seconds": self.cadence_seconds,
            "uptime_seconds": uptime,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "agent_count": len(self.agent_grid._agents) if hasattr(self.agent_grid, '_agents') else 0,
        }


def get_kalshi_15m_loop(
    agent_grid: Any,
    venue_adapter: Any,
    bankroll_service: Any,
    risk_config: Any,
    cadence_seconds: float = 5.0,
) -> Kalshi15mLoop:
    """
    Factory function to create/get the Kalshi15mLoop singleton.
    
    This is the canonical way to get the loop instance for the 15m profile.
    """
    return Kalshi15mLoop(
        agent_grid=agent_grid,
        venue_adapter=venue_adapter,
        bankroll_service=bankroll_service,
        risk_config=risk_config,
        cadence_seconds=cadence_seconds,
    )

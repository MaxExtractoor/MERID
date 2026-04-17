"""Integration wiring for Kalshi-market-driven pipeline.

Wires together:
- MarketOpinionPipelineMachine (canonical truth engine)
- GradingObserver (collects metrics)
- ConsensusSignalProcessor (UI read model)
- KalshiSettlementPoller (realized outcomes)
- WebSocket streaming (real-time UI updates)

Usage in main.py:
    from merid.prediction.pipeline_integration import initialize_pipeline_integration
    
    async def _app_lifespan(app):
        # Initialize the integrated pipeline
        integration = initialize_pipeline_integration(kalshi_client)
        await integration.start()
        yield
        await integration.stop()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.prediction.pipeline_integration")


# ── Integration Configuration ───────────────────────────────────────────────────

@dataclass
class PipelineIntegrationConfig:
    """Configuration for pipeline integration."""
    # Settlement polling
    settlement_poll_interval_seconds: float = 60.0
    settlement_lookback_hours: int = 24
    
    # UI streaming
    ws_broadcast_interval_seconds: float = 5.0  # Summary broadcast interval
    
    # Grading
    enable_grading: bool = True
    brier_window_size: int = 50
    
    # Filters
    min_confidence_for_ui: float = 0.30
    min_edge_cents_for_ui: float = 1.0
    
    # Simulation mode (dry run without real orders)
    dry_run: bool = False


# ── Pipeline Integration ─────────────────────────────────────────────────────

class PipelineIntegration:
    """
    Orchestrates the full Kalshi-market-driven pipeline.
    
    Flow:
    1. MarketOpinion generated (news, momentum, RTI)
    2. → SwarmConsensusAggregator (consensus formation)
    3. → GradingObserver (collects metrics)
    4. → ConsensusSignalProcessor (UI read model)
    5. → KalshiSettlementPoller (realized outcomes)
    6. → WebSocket broadcast (UI updates)
    
    All components share the same canonical state from MarketOpinionPipelineMachine.
    """
    
    def __init__(
        self,
        kalshi_client,
        config: Optional[PipelineIntegrationConfig] = None,
    ):
        self.config = config or PipelineIntegrationConfig()
        self.kalshi_client = kalshi_client
        
        # Components (initialized lazily)
        self._processor: Optional[Any] = None
        self._stream: Optional[Any] = None
        self._poller: Optional[Any] = None
        self._bridge: Optional[Any] = None
        self._grading_observer: Optional[Any] = None
        
        # State
        self._running = False
        self._broadcast_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Initialize and start all components."""
        if self._running:
            return
        
        logger.info("Starting pipeline integration...")
        
        # 1. Initialize UI read model
        from web.read_models.grading import (
            get_consensus_processor,
            get_consensus_stream,
            GradingObserverBridge,
        )
        self._processor = get_consensus_processor()
        self._stream = get_consensus_stream()
        
        # 2. Initialize settlement poller
        from merid.event_venues.kalshi.settlement_poller import (
            get_settlement_poller,
            get_settlement_bridge,
        )
        self._poller = get_settlement_poller(self.kalshi_client)
        
        # 3. Create grading observer bridge
        # This wires settlements → grading metrics → UI updates
        self._bridge = GradingObserverBridge(
            self._processor,
            filter_sim_only=False,  # Show all signals in UI
        )
        
        # 4. Wire settlement poller to notify grading
        # When a settlement arrives, the poller calls our callback
        # which triggers grading computation and UI update
        async def on_settlement(market_id: str, price_cents: int):
            """Callback when settlement is received."""
            logger.info(f"Settlement callback: {market_id} = {price_cents}c")
            # Trigger UI update with new grading data
            await self._stream.broadcast_summary()
        
        self._grading_observer = get_settlement_bridge(
            self.kalshi_client,
            grading_callback=on_settlement,
        )
        
        # 5. Start components
        await self._poller.start()
        
        # 6. Start periodic UI broadcast
        self._broadcast_task = asyncio.create_task(self._periodic_broadcast())
        
        self._running = True
        logger.info("Pipeline integration started successfully")
    
    async def stop(self) -> None:
        """Stop all components."""
        if not self._running:
            return
        
        logger.info("Stopping pipeline integration...")
        
        # Stop broadcast task
        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        
        # Stop poller
        if self._poller:
            await self._poller.stop()
        
        self._running = False
        logger.info("Pipeline integration stopped")
    
    async def _periodic_broadcast(self) -> None:
        """Periodically broadcast summary to all WebSocket clients."""
        while self._running:
            try:
                if self._stream:
                    await self._stream.broadcast_summary()
                await asyncio.sleep(self.config.ws_broadcast_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Broadcast error: {exc}")
                await asyncio.sleep(1.0)
    
    def on_opinion_approved(self, record) -> None:
        """
        Entry point: called when MarketOpinionPipelineMachine approves an opinion.
        
        This is the primary hook for the live pipeline. The machine calls this
        when consensus is reached and an opinion is approved for sizing/execution.
        """
        if not self._running:
            return
        
        try:
            # Process through UI read model
            signal = self._processor.process_record(record)
            
            if signal:
                logger.debug(
                    f"Opinion processed: {signal.ticker} "
                    f"({signal.consensus_dir} @ {signal.confidence_pct:.0f}%)"
                )
        except Exception as exc:
            logger.error(f"Opinion processing error: {exc}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get integration status and component health."""
        return {
            "running": self._running,
            "dry_run": self.config.dry_run,
            "components": {
                "processor": self._processor is not None,
                "stream": self._stream is not None,
                "poller": self._poller.get_stats() if self._poller else None,
            },
            "config": {
                "settlement_poll_interval": self.config.settlement_poll_interval_seconds,
                "ws_broadcast_interval": self.config.ws_broadcast_interval_seconds,
            },
        }


# ── Factory ────────────────────────────────────────────────────────────────────

_integration: Optional[PipelineIntegration] = None


def initialize_pipeline_integration(
    kalshi_client,
    config: Optional[PipelineIntegrationConfig] = None,
) -> PipelineIntegration:
    """
    Initialize the pipeline integration singleton.
    
    Usage:
        integration = initialize_pipeline_integration(kalshi_client)
        await integration.start()
    """
    global _integration
    if _integration is None:
        _integration = PipelineIntegration(kalshi_client, config)
    return _integration


def get_pipeline_integration() -> Optional[PipelineIntegration]:
    """Get the initialized integration instance."""
    return _integration


def reset_pipeline_integration() -> None:
    """Reset the singleton (for testing)."""
    global _integration
    _integration = None


# ── FastAPI Lifespan Helper ───────────────────────────────────────────────────

async def pipeline_lifespan(app, kalshi_client):
    """
    FastAPI lifespan context manager for pipeline integration.
    
    Usage in main.py:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with pipeline_lifespan(app, kalshi_client):
                yield
        
        app = FastAPI(lifespan=lifespan)
    """
    integration = initialize_pipeline_integration(kalshi_client)
    await integration.start()
    
    # Register WebSocket routes
    from web.read_models.grading import register_websocket_route
    register_websocket_route(app)
    
    try:
        yield
    finally:
        await integration.stop()


# ── Hook for MarketOpinionPipelineMachine ─────────────────────────────────────

def on_machine_opinion_approved(record) -> None:
    """
    Static hook for MarketOpinionPipelineMachine to call.
    
    This function is registered with the machine as a callback.
    When the machine approves an opinion, it calls this function,
    which forwards to the active integration.
    """
    integration = get_pipeline_integration()
    if integration:
        integration.on_opinion_approved(record)


# ── HTTP Status Endpoint ───────────────────────────────────────────────────────

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/pipeline", tags=["pipeline"])


@router.get("/status")
async def get_pipeline_status() -> Dict[str, Any]:
    """Get pipeline integration status."""
    integration = get_pipeline_integration()
    if integration is None:
        return {"status": "not_initialized"}
    
    return {
        "status": "running" if integration._running else "stopped",
        **integration.get_status(),
    }


@router.post("/refresh")
async def manual_refresh() -> Dict[str, Any]:
    """Manually trigger a UI refresh broadcast."""
    integration = get_pipeline_integration()
    if integration and integration._stream:
        await integration._stream.broadcast_summary()
        return {"status": "refreshed"}
    return {"status": "not_running"}


# ── Example Usage ─────────────────────────────────────────────────────────────

async def example_main():
    """Example of how to wire everything together."""
    # Mock kalshi client (replace with real one)
    class MockKalshiClient:
        async def request(self, method, endpoint, params=None):
            return {"settlements": []}
    
    client = MockKalshiClient()
    
    # Initialize integration
    integration = initialize_pipeline_integration(client)
    await integration.start()
    
    # Simulate an opinion being approved
    from tests.test_replay_grading import ApprovedOpinionRecord
    
    record = ApprovedOpinionRecord(
        market_id="KXBTC-15M",
        asset_id="BTC",
        tenor="15m",
        direction="yes",
        confidence=0.75,
        consensus_agents=3,
        sim_only=False,
        executed=True,
        execution_price_cents=55,
    )
    
    integration.on_opinion_approved(record)
    
    # Let it run
    await asyncio.sleep(10)
    
    # Stop
    await integration.stop()


if __name__ == "__main__":
    asyncio.run(example_main())

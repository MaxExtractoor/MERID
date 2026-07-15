"""UI Read Model for consensus-graded signals.

Provides:
- ConsensusSignal dataclass for UI consumption
- Stream processor from ApprovedOpinionRecord → aggregated signals
- WebSocket streaming for real-time consensus views
- Benchmark targets and grading status

Design:
- Read-only view of the canonical MarketOpinionPipelineMachine state
- Filters by sim_only=False and edge>threshold for live signals
- Rolling aggregates (Brier, Kelly regret, PnL) per source and market
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Callable
from collections import defaultdict
import json

from utils.logger import get_logger

from merid.prediction.market_opinion import BenchmarkThresholds

logger = get_logger("web.read_models.grading")


# ── Benchmark Targets ────────────────────────────────────────────────────────
# NOTE: BenchmarkThresholds is imported from domain module (merid.prediction.market_opinion)
# per Contract §3 to ensure all components use identical thresholds.
# See merid/prediction/market_opinion.py for the canonical definition.


# ── UI Consensus Signal ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConsensusSignal:
    """
    Read-model for UI consumption of consensus-graded signals.
    
    This is a projection from the canonical MarketOpinionPipelineMachine,
    filtered and enriched for display.
    """
    # Identity
    signal_id: str
    timestamp_utc: str
    
    # Market identification
    ticker: str  # Full Kalshi ticker (KXBTC-15M)
    asset: str   # BTC, ETH, etc.
    tenor: str   # 15m, 1h, daily
    
    # Consensus content
    consensus_dir: Literal["UP", "DOWN", "NEUTRAL"]  # UI-friendly direction
    confidence_pct: float  # 0-100
    edge_cents: float      # Edge in cents (not bps for UI clarity)
    
    # Source attribution
    sources: List[str]     # ["news_sentiment", "momentum", "rti"]
    primary_source: str
    agent_count: int       # How many agents contributed
    
    # Execution gating
    sim_only: bool
    executable: bool       # sim_only=False AND confidence > threshold
    size_band: str         # small/base/large
    
    # Live grading metrics (from GradingObserver)
    brier_live: Optional[float] = None       # Rolling Brier for this market
    kelly_regret: Optional[float] = None      # Avg regret for this source
    pnl_realized: Optional[float] = None      # Realized PnL cents
    roi_pct: Optional[float] = None           # Return on investment
    
    # Status
    status: Literal["forming", "ready", "executed", "settled"] = "forming"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON/WebSocket."""
        return asdict(self)
    
    @property
    def grade_quality(self) -> str:
        """Human-readable quality grade."""
        if self.brier_live is None:
            return "uncalibrated"
        return BenchmarkThresholds.grade_brier(self.brier_live)
    
    @property
    def is_actionable(self) -> bool:
        """Can this signal be traded?"""
        return self.executable and not self.sim_only and self.status == "ready"


# ── Stream Processor ───────────────────────────────────────────────────────────

@dataclass
class RollingWindow:
    """Rolling window for metric aggregation."""
    max_size: int = 100
    values: List[float] = field(default_factory=list)
    
    def add(self, value: float) -> None:
        self.values.append(value)
        if len(self.values) > self.max_size:
            self.values.pop(0)
    
    @property
    def avg(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0


class ConsensusSignalProcessor:
    """
    Stream processor: ApprovedOpinionRecord → ConsensusSignal → UI stream.
    
    Maintains:
    - Rolling Brier scores per market
    - Kelly regret per source
    - Aggregated PnL per asset
    """
    
    def __init__(self):
        # Rolling metrics
        self._brier_by_ticker: Dict[str, RollingWindow] = defaultdict(
            lambda: RollingWindow(max_size=50)
        )
        self._regret_by_source: Dict[str, RollingWindow] = defaultdict(
            lambda: RollingWindow(max_size=100)
        )
        self._pnl_by_asset: Dict[str, float] = defaultdict(float)
        
        # Signal cache for deduplication
        self._last_signals: Dict[str, ConsensusSignal] = {}
        
        # Subscribers for real-time updates
        self._subscribers: List[Callable[[ConsensusSignal], None]] = []
    
    def subscribe(self, callback: Callable[[ConsensusSignal], None]) -> None:
        """Subscribe to real-time signal updates."""
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable[[ConsensusSignal], None]) -> None:
        """Unsubscribe from updates."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)
    
    def process_record(
        self,
        record,  # ApprovedOpinionRecord
        grading_metrics=None,  # GradingMetrics from GradingObserver
    ) -> Optional[ConsensusSignal]:
        """
        Process an ApprovedOpinionRecord into a ConsensusSignal.
        
        Args:
            record: The opinion record from the pipeline
            grading_metrics: Optional grading metrics if available
            
        Returns:
            ConsensusSignal for UI, or None if filtered out
        """
        # Filter: require minimum confidence
        # FIX: Aligned with production config (was 0.30)
        min_confidence = 0.65
        if record.confidence < min_confidence:
            return None
        
        # Update rolling metrics if grading data available
        brier_live = None
        kelly_regret = None
        pnl_realized = None
        roi_pct = None
        
        if grading_metrics:
            # Update rolling Brier for this ticker
            if grading_metrics.brier_score is not None:
                self._brier_by_ticker[record.market_id].add(grading_metrics.brier_score)
                brier_live = self._brier_by_ticker[record.market_id].avg
            
            # Update rolling regret for this source
            if grading_metrics.kelly_regret is not None:
                self._regret_by_source[record.originating_source].add(
                    grading_metrics.kelly_regret
                )
                kelly_regret = self._regret_by_source[record.originating_source].avg
            
            # Track PnL
            if grading_metrics.realized_pnl_cents is not None:
                self._pnl_by_asset[record.asset_id] += grading_metrics.realized_pnl_cents
                pnl_realized = self._pnl_by_asset[record.asset_id]
                roi_pct = grading_metrics.roi_pct
        
        # Determine direction for UI
        consensus_dir: Literal["UP", "DOWN", "NEUTRAL"] = "NEUTRAL"
        if record.direction == "yes":
            consensus_dir = "UP"
        elif record.direction == "no":
            consensus_dir = "DOWN"
        
        # FIX: Align#d with production config (was 0.50)
        e Determine executability
        executable = (
            not record.sim_only and6
            record.confidence >= 0.50 and6
            record.consensus_confidence >= 0.50
        )
        
        # Determine status
        status: Literal["forming", "ready", "executed", "settled"] = "forming"
        if record.settlement_price_cents is not None:
            status = "settled"
        elif record.executed:
            status = "executed"
        elif record.consensus_agents >= 2:  # Minimum agents for consensus
            status = "ready"
        
        signal = ConsensusSignal(
            signal_id=record.record_id,
            timestamp_utc=record.timestamp_utc,
            ticker=record.market_id,
            asset=record.asset_id,
            tenor=record.tenor,
            consensus_dir=consensus_dir,
            confidence_pct=record.confidence * 100,
            edge_cents=record.edge_bps / 100,  # Convert bps to cents
            sources=record.consensus_sources,
            primary_source=record.originating_source,
            agent_count=record.consensus_agents,
            sim_only=record.sim_only,
            executable=executable,
            size_band=record.size_band,
            brier_live=brier_live,
            kelly_regret=kelly_regret,
            pnl_realized=pnl_realized,
            roi_pct=roi_pct,
            status=status,
        )
        
        # Cache and notify
        self._last_signals[record.market_id] = signal
        
        for callback in self._subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(signal))
                else:
                    callback(signal)
            except Exception as exc:
                logger.debug(f"Signal subscriber error: {exc}")
        
        return signal
    
    def get_signal(self, ticker: str) -> Optional[ConsensusSignal]:
        """Get the latest signal for a ticker."""
        return self._last_signals.get(ticker.upper())
    
    def get_all_signals(self) -> List[ConsensusSignal]:
        """Get all cached signals."""
        return list(self._last_signals.values())
    
    def get_signals_by_asset(self, asset: str) -> List[ConsensusSignal]:
        """Get signals for a specific asset."""
        return [s for s in self._last_signals.values() if s.asset.upper() == asset.upper()]
    
    def get_actionable_signals(self) -> List[ConsensusSignal]:
        """Get only actionable (live) signals."""
        return [s for s in self._last_signals.values() if s.is_actionable]
    
    def get_grading_summary(self) -> Dict[str, Any]:
        """Get overall grading summary for UI dashboard."""
        all_signals = self.get_all_signals()
        actionable = self.get_actionable_signals()
        
        # Aggregate metrics
        briers = [s.brier_live for s in all_signals if s.brier_live is not None]
        regrets = [s.kelly_regret for s in all_signals if s.kelly_regret is not None]
        
        total_pnl = sum(self._pnl_by_asset.values())
        
        return {
            "total_signals": len(all_signals),
            "actionable_signals": len(actionable),
            "avg_brier": sum(briers) / len(briers) if briers else None,
            "brier_quality": BenchmarkThresholds.grade_brier(
                sum(briers) / len(briers) if briers else 1.0
            ),
            "avg_kelly_regret": sum(regrets) / len(regrets) if regrets else None,
            "total_pnl_cents": total_pnl,
            "by_asset": dict(self._pnl_by_asset),
            "benchmarks": {
                "brier_good": BenchmarkThresholds.BRIER_GOOD,
                "direction_accuracy_min": BenchmarkThresholds.DIRECTION_ACCURACY_MIN,
            },
        }


# ── WebSocket Streaming ────────────────────────────────────────────────────────

class ConsensusSignalStream:
    """
    FastAPI WebSocket stream for real-time consensus signals.
    
    Usage in main_15m_lean.py:
        @app.websocket("/ws/consensus-signals")
        async def consensus_signals_ws(websocket: WebSocket):
            await stream.connect(websocket)
            try:
                while True:
                    await asyncio.sleep(1)
            except:
                await stream.disconnect(websocket)
    """
    
    def __init__(self, processor: ConsensusSignalProcessor):
        self.processor = processor
        self._connections: List[Any] = []  # FastAPI WebSocket objects
        self._connected = False
    
    async def connect(self, websocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        self._connected = True
        
        # Subscribe processor to send updates here
        self.processor.subscribe(self._on_signal)
        
        logger.info(f"ConsensusSignal WebSocket connected (total: {len(self._connections)})")
        
        # Send current snapshot
        snapshot = self.processor.get_all_signals()
        await websocket.send_json({
            "type": "snapshot",
            "signals": [s.to_dict() for s in snapshot],
            "summary": self.processor.get_grading_summary(),
        })
    
    async def disconnect(self, websocket) -> None:
        """Disconnect a WebSocket."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        
        if not self._connections:
            self._connected = False
            self.processor.unsubscribe(self._on_signal)
        
        logger.info(f"ConsensusSignal WebSocket disconnected (total: {len(self._connections)})")
    
    async def _on_signal(self, signal: ConsensusSignal) -> None:
        """Called when processor emits a new signal."""
        if not self._connected:
            return
        
        message = {
            "type": "signal_update",
            "signal": signal.to_dict(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Broadcast to all connections
        disconnected = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        
        # Clean up dead connections
        for ws in disconnected:
            await self.disconnect(ws)
    
    async def broadcast_summary(self) -> None:
        """Broadcast grading summary to all clients."""
        if not self._connected:
            return
        
        summary = self.processor.get_grading_summary()
        message = {
            "type": "summary_update",
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        disconnected = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        
        for ws in disconnected:
            await self.disconnect(ws)


# ── GradingObserver Integration ───────────────────────────────────────────────

class GradingObserverBridge:
    """
    Bridge between GradingObserver and ConsensusSignalProcessor.
    
    Attaches to the live pipeline and forwards graded records to the UI stream.
    """
    
    def __init__(
        self,
        processor: ConsensusSignalProcessor,
        filter_sim_only: bool = False,  # If True, only forward live signals
    ):
        self.processor = processor
        self.filter_sim_only = filter_sim_only
    
    def on_opinion_graded(
        self,
        record,  # ApprovedOpinionRecord
        metrics,  # GradingMetrics
    ) -> None:
        """Called by GradingObserver when an opinion is graded."""
        if self.filter_sim_only and record.sim_only:
            return
        
        # Process into UI signal
        signal = self.processor.process_record(record, metrics)
        
        if signal:
            logger.debug(
                f"Graded signal forwarded to UI: {signal.ticker} "
                f"({signal.consensus_dir} @ {signal.confidence_pct:.0f}%)"
            )


# ── Factory / Singleton ──────────────────────────────────────────────────────

_processor: Optional[ConsensusSignalProcessor] = None
_stream: Optional[ConsensusSignalStream] = None


def get_consensus_processor() -> ConsensusSignalProcessor:
    """Get or create the singleton processor."""
    global _processor
    if _processor is None:
        _processor = ConsensusSignalProcessor()
    return _processor


def get_consensus_stream() -> ConsensusSignalStream:
    """Get or create the singleton stream."""
    global _stream
    if _stream is None:
        _stream = ConsensusSignalStream(get_consensus_processor())
    return _stream


def reset_consensus_read_model() -> None:
    """Reset singletons (for testing)."""
    global _processor, _stream
    _processor = None
    _stream = None


# ── HTTP API Helpers ───────────────────────────────────────────────────────────

from fastapi import APIRouter, WebSocket

router = APIRouter(prefix="/api/v1/consensus-signals", tags=["consensus-signals"])


@router.get("/signals")
async def get_consensus_signals(
    asset: Optional[str] = None,
    actionable_only: bool = False,
) -> Dict[str, Any]:
    """Get current consensus signals (HTTP polling endpoint)."""
    processor = get_consensus_processor()
    
    if asset:
        signals = processor.get_signals_by_asset(asset)
    elif actionable_only:
        signals = processor.get_actionable_signals()
    else:
        signals = processor.get_all_signals()
    
    return {
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
        "summary": processor.get_grading_summary(),
    }


@router.get("/signals/{ticker}")
async def get_signal_by_ticker(ticker: str) -> Dict[str, Any]:
    """Get consensus signal for a specific Kalshi ticker."""
    processor = get_consensus_processor()
    signal = processor.get_signal(ticker)
    
    if signal is None:
        return {"error": f"No signal found for {ticker}"}
    
    return {"signal": signal.to_dict()}


@router.get("/summary")
async def get_grading_summary() -> Dict[str, Any]:
    """Get overall grading summary."""
    processor = get_consensus_processor()
    return processor.get_grading_summary()


# WebSocket endpoint registration helper
def register_websocket_route(app) -> None:
    """Register the WebSocket endpoint with a FastAPI app."""
    stream = get_consensus_stream()
    
    @app.websocket("/ws/consensus-signals")
    async def consensus_signals_websocket(websocket: WebSocket):
        await stream.connect(websocket)
        try:
            while True:
                # Keep connection alive, process any client messages
                data = await websocket.receive_text()
                # Client can request refresh
                if data == "refresh":
                    await stream.broadcast_summary()
                await asyncio.sleep(0.1)
        except Exception:
            await stream.disconnect(websocket)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestConsensusSignal:
    """Tests for ConsensusSignal dataclass."""
    
    def test_signal_actionable(self):
        """Test is_actionable property logic."""
        # Not actionable: sim_only
        signal_sim = ConsensusSignal(
            signal_id="test-1",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            ticker="KXBTC-15M",
            asset="BTC",
            tenor="15m",
            consensus_dir="UP",
            confidence_pct=75.0,
            edge_cents=2.5,
            sources=["momentum"],
            primary_source="momentum",
            agent_count=3,
            sim_only=True,  # Simulation
            executable=True,
            size_band="base",
        )
        assert not signal_sim.is_actionable
        
        # Actionable: live, ready, executable
        signal_live = ConsensusSignal(
            signal_id="test-2",
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            ticker="KXETH-15M",
            asset="ETH",
            tenor="15m",
            consensus_dir="UP",
            confidence_pct=75.0,
            edge_cents=2.5,
            sources=["momentum"],
            primary_source="momentum",
            agent_count=3,
            sim_only=False,  # Live
            executable=True,
            size_band="base",
            status="ready",
        )
        assert signal_live.is_actionable


class TestBenchmarkThresholds:
    """Tests for benchmark grading."""
    
    def test_brier_grading(self):
        """Test Brier score quality grades."""
        assert BenchmarkThresholds.grade_brier(0.05) == "excellent"
        assert BenchmarkThresholds.grade_brier(0.15) == "good"
        assert BenchmarkThresholds.grade_brier(0.20) == "fair"
        assert BenchmarkThresholds.grade_brier(0.30) == "poor"
    
    def test_direction_accuracy_grading(self):
        """Test direction accuracy grades."""
        assert BenchmarkThresholds.grade_direction_accuracy(0.75) == "good"
        assert BenchmarkThresholds.grade_direction_accuracy(0.65) == "fair"
        assert BenchmarkThresholds.grade_direction_accuracy(0.50) == "poor"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

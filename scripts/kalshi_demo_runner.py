"""
Kalshi Swarm Demo Runner — 60-minute Paper Mode
================================================
Orchestrates the full stack in a single process:
  1. Discovers open markets from Kalshi demo API
  2. Starts WS bridge → streams real orderbook data → NATS
  3. Runs a signal agent → watches orderbooks → generates intents → NATS
  4. Starts execution pipeline → consumes intents → paper-trades
  5. Collects and reports metrics every 30 seconds
  6. After duration expires, prints summary and exits

Usage:
    python scripts/kalshi_demo_runner.py [--duration 60] [--markets 3]
"""

import asyncio
import argparse
import json
import logging
import os
import signal
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

from merid_core.event_bus.nats_adapter import NATSEventBus, EventEnvelope
from merid_core.kalshi.ws_bridge import KalshiWebSocketBridge
from merid_core.kalshi.execution_pipeline import ExecutionPipeline

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("demo_runner")


# ── Market Discovery ─────────────────────────────────────────────────────────

def discover_open_markets(env: str = "demo", limit: int = 5) -> List[Dict[str, Any]]:
    """Fetch open markets from Kalshi REST API (unauthenticated)"""
    base = "https://demo-api.kalshi.co" if env == "demo" else "https://api.kalshi.com"
    url = f"{base}/trade-api/v2/markets"
    
    resp = requests.get(url, params={"limit": limit, "status": "open"}, timeout=10)
    resp.raise_for_status()
    
    markets = resp.json().get("markets", [])
    logger.info(f"Discovered {len(markets)} open markets")
    for m in markets:
        logger.info(f"  • {m['ticker']}  —  {m.get('title', 'N/A')}")
    
    return markets


# ── Signal Agent ─────────────────────────────────────────────────────────────

class PaperSignalAgent:
    """
    Simple signal agent for paper-mode demo.
    
    Watches orderbook snapshots arriving on NATS and generates buy/sell intents
    when it detects a bid-ask spread wider than a threshold (mock arb signal).
    Also generates periodic random intents to keep the pipeline exercised.
    """
    
    def __init__(self, event_bus: NATSEventBus, markets: List[str]):
        self.event_bus = event_bus
        self.markets = markets
        self.orderbooks: Dict[str, Dict[str, Any]] = {}
        self.intents_generated = 0
        self.snapshots_received = 0
        self.deltas_received = 0
        self.running = False
        
        # Config
        self.min_spread_threshold = 0.05  # 5¢ spread triggers intent
        self.intent_interval = 30  # seconds between periodic intents
        self.last_periodic_intent = 0
    
    async def start(self) -> None:
        """Subscribe to market data topics"""
        self.running = True
        await self.event_bus.subscribe("kalshi.orderbook_snapshot", self._handle_snapshot)
        await self.event_bus.subscribe("kalshi.orderbook_delta", self._handle_delta)
        logger.info(f"SignalAgent started — watching {len(self.markets)} markets")
    
    async def _handle_snapshot(self, envelope: EventEnvelope) -> None:
        """Process orderbook snapshot"""
        self.snapshots_received += 1
        msg = envelope.data
        ticker = msg.get("msg", {}).get("market_ticker", "unknown")
        self.orderbooks[ticker] = msg.get("msg", {})
        
        await self._evaluate_signal(ticker)
    
    async def _handle_delta(self, envelope: EventEnvelope) -> None:
        """Process orderbook delta"""
        self.deltas_received += 1
        msg = envelope.data
        ticker = msg.get("msg", {}).get("market_ticker", "unknown")
        
        # Update stored orderbook (simplified — just track latest delta)
        if ticker not in self.orderbooks:
            self.orderbooks[ticker] = {}
        self.orderbooks[ticker]["last_delta"] = msg.get("msg", {})
        
        await self._evaluate_signal(ticker)
    
    async def _evaluate_signal(self, ticker: str) -> None:
        """Evaluate whether to generate an intent for this market"""
        ob = self.orderbooks.get(ticker, {})
        
        # Extract best bid/ask from orderbook
        yes_bids = ob.get("yes", [])
        no_bids = ob.get("no", [])
        
        best_yes_bid = yes_bids[0][0] / 100.0 if yes_bids else None
        best_no_bid = no_bids[0][0] / 100.0 if no_bids else None
        
        if best_yes_bid and best_no_bid:
            # In a binary market: implied ask = 1 - best_no_bid
            implied_yes_ask = 1.0 - best_no_bid
            spread = implied_yes_ask - best_yes_bid
            
            if spread > self.min_spread_threshold:
                # Wide spread → generate buy intent at midpoint
                mid = (best_yes_bid + implied_yes_ask) / 2.0
                await self._publish_intent(ticker, "buy_yes", mid, spread)
    
    async def generate_periodic_intent(self) -> None:
        """Generate periodic intents to keep pipeline exercised"""
        now = time.time()
        if now - self.last_periodic_intent < self.intent_interval:
            return
        
        self.last_periodic_intent = now
        
        if not self.markets:
            return
        
        # Round-robin through markets
        idx = self.intents_generated % len(self.markets)
        ticker = self.markets[idx]
        
        # Generate a low-price buy intent (won't fill in paper mode anyway)
        await self._publish_intent(ticker, "buy_yes", 0.05, 0.0, periodic=True)
    
    async def _publish_intent(
        self, 
        ticker: str, 
        side: str, 
        price: float, 
        spread: float, 
        periodic: bool = False
    ) -> None:
        """Publish order intent to NATS"""
        intent = {
            "session_id": "demo-runner",
            "agent_id": "paper-signal-agent",
            "market_ticker": ticker,
            "side": side,
            "qty": 1,
            "price": round(price, 2),
            "client_tag": f"demo-{uuid.uuid4().hex[:12]}",
            "confidence": 0.6 if not periodic else 0.3,
            "rationale": f"spread={spread:.3f}" if not periodic else "periodic_heartbeat"
        }
        
        await self.event_bus.publish("intents.orders", intent)
        self.intents_generated += 1
        
        source = "periodic" if periodic else f"spread={spread:.3f}"
        logger.info(f"📡 Intent #{self.intents_generated}: {side} {ticker} @ {price:.2f} ({source})")
    
    def stats(self) -> Dict[str, Any]:
        return {
            "intents_generated": self.intents_generated,
            "snapshots_received": self.snapshots_received,
            "deltas_received": self.deltas_received,
            "orderbooks_tracked": len(self.orderbooks),
        }


# ── Metric Collector ─────────────────────────────────────────────────────────

class MetricCollector:
    """Collects and reports metrics from all components"""
    
    def __init__(
        self,
        bridge: Optional[KalshiWebSocketBridge],
        agent: PaperSignalAgent,
        pipeline: ExecutionPipeline,
        report_interval: int = 30
    ):
        self.bridge = bridge
        self.agent = agent
        self.pipeline = pipeline
        self.report_interval = report_interval
        self.snapshots: List[Dict[str, Any]] = []
        self.start_time = time.time()
    
    def collect(self) -> Dict[str, Any]:
        """Collect current metrics from all components"""
        elapsed = time.time() - self.start_time
        
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 1),
            "bridge": self.bridge.stats() if self.bridge else {"status": "not_started"},
            "agent": self.agent.stats(),
            "pipeline": self.pipeline.stats(),
        }
        
        self.snapshots.append(snapshot)
        return snapshot
    
    def print_report(self, snapshot: Dict[str, Any]) -> None:
        """Print formatted metric report"""
        elapsed = snapshot["elapsed_seconds"]
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        
        bridge = snapshot["bridge"]
        agent = snapshot["agent"]
        pipeline = snapshot["pipeline"]
        
        logger.info("─" * 60)
        logger.info(f"📊 Metrics Report  [{mins:02d}:{secs:02d} elapsed]")
        logger.info("─" * 60)
        
        if isinstance(bridge, dict) and "messages_received" in bridge:
            logger.info(f"  WS Bridge:")
            logger.info(f"    Messages received:  {bridge['messages_received']}")
            logger.info(f"    Messages published: {bridge['messages_published']}")
            logger.info(f"    Reconnections:      {bridge['reconnect_count']}")
            logger.info(f"    Connected:          {bridge.get('connected', False)}")
        else:
            logger.info(f"  WS Bridge: {bridge.get('status', 'unknown')}")
        
        logger.info(f"  Signal Agent:")
        logger.info(f"    Snapshots received: {agent['snapshots_received']}")
        logger.info(f"    Deltas received:    {agent['deltas_received']}")
        logger.info(f"    Intents generated:  {agent['intents_generated']}")
        logger.info(f"    Orderbooks tracked: {agent['orderbooks_tracked']}")
        
        logger.info(f"  Execution Pipeline:")
        logger.info(f"    Intents received:   {pipeline['intents_received']}")
        logger.info(f"    Intents executed:    {pipeline['intents_executed']}")
        logger.info(f"    Rejected (risk):     {pipeline['intents_rejected_risk']}")
        logger.info(f"    Rejected (rate):     {pipeline['intents_rejected_rate']}")
        logger.info(f"    Positions:           {pipeline['positions']}")
        logger.info(f"    Daily PnL:           ${pipeline['daily_pnl']:.2f}")
        logger.info("─" * 60)
    
    def print_final_summary(self) -> None:
        """Print final summary after run completes"""
        if not self.snapshots:
            self.collect()
        
        final = self.snapshots[-1]
        elapsed = final["elapsed_seconds"]
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        
        agent = final["agent"]
        pipeline = final["pipeline"]
        bridge = final["bridge"]
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("🏁  DEMO RUN COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  Duration:             {mins}m {secs}s")
        logger.info(f"  Metric snapshots:     {len(self.snapshots)}")
        logger.info("")
        
        if isinstance(bridge, dict) and "messages_received" in bridge:
            ws_msgs = bridge["messages_received"]
            msg_rate = ws_msgs / max(elapsed, 1) * 60
            logger.info(f"  WS messages total:    {ws_msgs}")
            logger.info(f"  WS messages/min:      {msg_rate:.1f}")
            logger.info(f"  WS reconnections:     {bridge['reconnect_count']}")
        
        logger.info(f"  Orderbooks tracked:   {agent['orderbooks_tracked']}")
        logger.info(f"  Intents generated:    {agent['intents_generated']}")
        logger.info(f"  Intents executed:     {pipeline['intents_executed']}")
        logger.info(f"  Intents rejected:     {pipeline['intents_rejected_risk'] + pipeline['intents_rejected_rate']}")
        logger.info(f"  Paper positions:      {pipeline['positions']}")
        logger.info(f"  Paper PnL:            ${pipeline['daily_pnl']:.2f}")
        logger.info("=" * 60)
        
        # Save to file
        self._save_observations(final, elapsed)
    
    def _save_observations(self, final: Dict[str, Any], elapsed: float) -> None:
        """Save observations to log file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"observations_{timestamp}.json"
        filepath = os.path.join(os.path.dirname(os.path.dirname(__file__)), filename)
        
        observations = {
            "run_timestamp": datetime.now().isoformat(),
            "duration_seconds": elapsed,
            "mode": "paper",
            "final_metrics": final,
            "all_snapshots": self.snapshots,
        }
        
        with open(filepath, "w") as f:
            json.dump(observations, f, indent=2, default=str)
        
        logger.info(f"  Observations saved:   {filepath}")


# ── Main Runner ──────────────────────────────────────────────────────────────

async def run_demo(
    duration_minutes: int = 60,
    num_markets: int = 3,
    use_ws: bool = True,
    metric_interval: int = 30
):
    """
    Run the full-stack paper-mode demo.
    
    Args:
        duration_minutes: How long to run (default 60)
        num_markets: Number of markets to subscribe to
        use_ws: Whether to connect to Kalshi WS (requires credentials)
        metric_interval: Seconds between metric reports
    """
    end_time = time.time() + (duration_minutes * 60)
    
    logger.info("=" * 60)
    logger.info("🚀  Kalshi Swarm Demo Runner — Paper Mode")
    logger.info("=" * 60)
    logger.info(f"  Duration:    {duration_minutes} minutes")
    logger.info(f"  Markets:     {num_markets}")
    logger.info(f"  WS bridge:   {'enabled' if use_ws else 'disabled'}")
    logger.info(f"  Metrics:     every {metric_interval}s")
    logger.info("=" * 60)
    
    # ── Step 1: Discover markets ─────────────────────────────────────────
    logger.info("\n📡 Step 1: Discovering open markets...")
    try:
        markets_data = discover_open_markets(limit=num_markets)
    except Exception as e:
        logger.error(f"Failed to discover markets: {e}")
        logger.info("Falling back to empty market list (periodic intents only)")
        markets_data = []
    
    market_tickers = [m["ticker"] for m in markets_data]
    
    # ── Step 2: Connect NATS ─────────────────────────────────────────────
    logger.info("\n🔌 Step 2: Connecting to NATS...")
    bus = NATSEventBus("nats://localhost:4222")
    await bus.connect()
    
    # ── Step 3: Start execution pipeline (paper mode) ────────────────────
    logger.info("\n⚙️  Step 3: Starting execution pipeline (PAPER mode)...")
    pipeline = ExecutionPipeline(
        event_bus=bus,
        enable_live_trading=False
    )
    await pipeline.start()
    
    # ── Step 4: Start signal agent ───────────────────────────────────────
    logger.info("\n🧠 Step 4: Starting signal agent...")
    agent = PaperSignalAgent(event_bus=bus, markets=market_tickers)
    await agent.start()
    
    # ── Step 5: Start WS bridge (optional) ───────────────────────────────
    bridge = None
    bridge_task = None
    
    if use_ws and market_tickers:
        key_id = os.environ.get("KALSHI_API_KEY_ID")
        key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
        
        if key_id and key_path:
            logger.info("\n🌐 Step 5: Starting WebSocket bridge...")
            bridge = KalshiWebSocketBridge(
                key_id=key_id,
                private_key_path=key_path,
                env="demo",
                event_bus=bus
            )
            bridge.set_markets(market_tickers)
            
            # Run bridge in background task
            bridge_task = asyncio.create_task(_run_bridge_safe(bridge))
        else:
            logger.warning("⚠ Kalshi credentials not set — WS bridge disabled")
            logger.info("  Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH for live WS data")
    else:
        logger.info("\n🌐 Step 5: WS bridge skipped (no markets or disabled)")
    
    # ── Step 6: Metric collector ─────────────────────────────────────────
    logger.info("\n📊 Step 6: Starting metric collector...")
    collector = MetricCollector(
        bridge=bridge,
        agent=agent,
        pipeline=pipeline,
        report_interval=metric_interval
    )
    
    # ── Main loop ────────────────────────────────────────────────────────
    logger.info("\n✅ All components started. Entering main loop...\n")
    
    last_metric_time = time.time()
    last_periodic_time = time.time()
    
    try:
        while time.time() < end_time:
            now = time.time()
            remaining = end_time - now
            
            # Periodic metric report
            if now - last_metric_time >= metric_interval:
                snapshot = collector.collect()
                collector.print_report(snapshot)
                last_metric_time = now
            
            # Periodic intent generation (even without WS data)
            if now - last_periodic_time >= agent.intent_interval:
                await agent.generate_periodic_intent()
                last_periodic_time = now
            
            # Log remaining time every 5 minutes
            remaining_mins = remaining / 60
            if int(remaining) % 300 == 0 and int(remaining) > 0:
                logger.info(f"⏱  {remaining_mins:.0f} minutes remaining")
            
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        logger.info("Run cancelled")
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("\n🛑 Shutting down...")
    
    if bridge:
        await bridge.stop()
    if bridge_task:
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass
    
    # Final metrics
    collector.collect()
    collector.print_final_summary()
    
    await bus.disconnect()
    logger.info("Done.")


async def _run_bridge_safe(bridge: KalshiWebSocketBridge) -> None:
    """Run bridge with error handling so it doesn't crash the main loop"""
    try:
        await bridge.start()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"WS bridge error: {e}", exc_info=True)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Kalshi Swarm Demo Runner")
    parser.add_argument("--duration", type=int, default=60, help="Run duration in minutes (default: 60)")
    parser.add_argument("--markets", type=int, default=3, help="Number of markets to watch (default: 3)")
    parser.add_argument("--no-ws", action="store_true", help="Disable WebSocket bridge")
    parser.add_argument("--metric-interval", type=int, default=30, help="Seconds between metric reports (default: 30)")
    
    args = parser.parse_args()
    
    try:
        asyncio.run(run_demo(
            duration_minutes=args.duration,
            num_markets=args.markets,
            use_ws=not args.no_ws,
            metric_interval=args.metric_interval
        ))
    except KeyboardInterrupt:
        logger.info("\nInterrupted. Goodbye.")


if __name__ == "__main__":
    main()

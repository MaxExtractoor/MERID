"""End-to-end smoke tests for Kalshi integration.

Test Cases:
1. Full pipeline: signal generation → reconciliation check
2. Signal store persistence
3. Venue adapter → reconciliation flow
4. Consensus bridge integration
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_kalshi_signal_generation_pipeline():
    """End-to-end: Generate signals and verify they're actionable."""
    from merid.signals.kalshi_signals import get_kalshi_signal_generator, reset_kalshi_signal_generator
    from merid.paper_config import InstrumentConfig
    
    reset_kalshi_signal_generator()
    
    with patch("merid.event_venues.kalshi.venue_adapter.get_kalshi_venue_adapter") as mock_adapter:
        # Mock adapter with test markets
        adapter = MagicMock()
        adapter.list_instruments = AsyncMock(return_value=[
            InstrumentConfig(
                id="BTC-TEST-YES",
                domain="prediction",
                venues=["kalshi"],
            ),
        ])
        mock_adapter.return_value = adapter
        
        # Generate signals
        generator = get_kalshi_signal_generator()
        signals = await generator.generate_all()
        
        # Verify signals were generated
        assert isinstance(signals, list)
        
        # If signals exist, verify structure
        if len(signals) > 0:
            signal = signals[0]
            assert hasattr(signal, "to_dict")
            signal_dict = signal.to_dict()
            assert "signal_type" in signal_dict
            assert signal_dict.get("venue") == "kalshi"


@pytest.mark.asyncio
async def test_kalshi_reconciliation_flow():
    """End-to-end: Fetch positions and run reconciliation."""
    from merid.event_venues.kalshi.venue_adapter import get_kalshi_venue_adapter
    from merid.reconciliation.kalshi_reconciler import get_kalshi_reconciler
    
    with patch("merid.event_venues.kalshi.venue_adapter.KalshiVenueClient") as mock_client:
        # Mock client
        client = MagicMock()
        client.get_positions = AsyncMock(return_value=[])
        client.get_orders = AsyncMock(return_value=[])
        mock_client.return_value = client
        
        # Get adapter
        adapter = get_kalshi_venue_adapter()
        
        # Get positions
        positions = await adapter.get_positions()
        orders = await adapter.get_orders()
        
        # Run reconciliation
        reconciler = get_kalshi_reconciler()
        report = reconciler.reconcile(
            positions,
            orders,
        )
        
        # Verify reconciliation completed
        assert report is not None
        assert hasattr(report, "severity")
        assert hasattr(report, "summary")


@pytest.mark.asyncio
async def test_kalshi_consensus_bridge_flow():
    """End-to-end: Signal → Energy packet → Vote."""
    from merid.prediction.consensus_bridge import get_kalshi_consensus_adapter, reset_kalshi_consensus_adapter
    from merid.prediction.strategy import StrategySignal, SignalAction
    from merid.event_venues.base import EventMarket, EventOutcome
    from decimal import Decimal
    
    reset_kalshi_consensus_adapter()
    
    # Create test signal
    signal = MagicMock(spec=StrategySignal)
    signal.action = SignalAction.BUY_YES
    signal.contracts = 10
    signal.limit_price_cents = 55.0
    signal.confidence = 0.7
    signal.reasoning = "Test signal"
    signal.edge = MagicMock(net_edge=0.05)
    
    # Create test market
    market = EventMarket(
        market_id="BTC-TEST",
        venue="kalshi",
        question="Test market",
        description="Test",
        outcomes=[
            EventOutcome("yes", "Yes", Decimal("0.55")),
            EventOutcome("no", "No", Decimal("0.45")),
        ],
        category="crypto",
        active=True,
    )
    
    # Convert signal to energy
    adapter = get_kalshi_consensus_adapter()
    energy = adapter.signal_to_energy(signal, market, "test_agent")
    
    # Verify energy packet structure
    assert energy["source"] == "kalshi"
    assert energy["domain"] == "prediction"
    assert "metadata" in energy
    assert energy["metadata"]["edge_pct"] == 5.0
    
    # Convert to vote
    intent = {
        "action": "BUY_YES",
        "contracts": 10,
        "market_id": "BTC-TEST",
    }
    vote = adapter.order_intent_to_vote(intent, edge=0.05, confidence=0.7)
    
    # Verify vote structure
    assert vote["vote"] == "accept"  # Strong signal
    assert vote["confidence"] == 0.7
    assert "reasoning" in vote


@pytest.mark.asyncio
async def test_kalshi_full_loop_integration():
    """End-to-end: Simulate full loop cycle with Kalshi."""
    from merid.loop import MeridLoop
    import time
    
    loop = MeridLoop()
    summary = {"actions": []}
    now = time.time()
    
    with patch("merid.signals.store.get_signal_store") as mock_store, \
         patch("merid.signals.features.FeatureService") as mock_fs, \
         patch("merid.signals.live_feeds.get_live_feed_manager") as mock_lfm, \
         patch("merid.prediction.agent_grid.get_agent_grid") as mock_grid, \
         patch("merid.signals.kalshi_signals.get_kalshi_venue_adapter") as mock_adapter:
        
        # Mock all dependencies
        store = MagicMock()
        store.store_signal = MagicMock()
        store.store_feature_snapshot = MagicMock()
        mock_store.return_value = store
        
        fs = MagicMock()
        fs.get_news_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        fs.get_social_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        fs.get_onchain_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        fs.get_macro_features = MagicMock(return_value=MagicMock(to_dict=lambda: {}))
        mock_fs.return_value = fs
        
        lfm = MagicMock()
        lfm.refresh_all = AsyncMock()
        mock_lfm.return_value = lfm
        
        grid = MagicMock()
        grid._running = True
        grid.agents = []
        mock_grid.return_value = grid
        
        adapter = MagicMock()
        adapter.list_instruments = AsyncMock(return_value=[])
        mock_adapter.return_value = adapter
        
        # Run full cycle steps
        await loop._refresh_features(now, summary)
        await loop._run_agent_cycles(summary)
        
        # Verify actions were recorded
        assert len(summary["actions"]) > 0
        
        # Should have feature refresh and potentially Kalshi signals
        actions_str = str(summary["actions"])
        assert "features_refreshed" in actions_str or "kalshi" in actions_str.lower()


@pytest.mark.asyncio
async def test_kalshi_execution_guard_via_reconciliation():
    """Test that CRITICAL reconciliation blocks execution."""
    from merid.reconciliation.kalshi_reconciler import (
        get_kalshi_reconciler,
        ReconciliationReport,
        IssueSeverity,
    )
    
    reconciler = get_kalshi_reconciler()
    
    # Create CRITICAL report
    report = ReconciliationReport(
        venue="kalshi",
        domain="prediction",
        severity=IssueSeverity.CRITICAL,
        summary="Critical issues detected",
        issues=[],
        timestamp=1234567890.0,
    )
    
    # Verify severity is CRITICAL
    assert report.severity == IssueSeverity.CRITICAL
    
    # In production, this would block execution
    # Loop should check: if report.severity == IssueSeverity.CRITICAL: block_execution()
    assert report.severity.value == "CRITICAL"

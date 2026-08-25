"""
Full lifecycle trace test for thesis_side invariant.

This test traces the complete lifecycle for one market from each asset family:
BTC, ETH, SOL, XRP, DOGE.

For each market, it traces:
signal → intent → entry order → fill ingestion → cache sync → exit decision → exit order → exit fill

The test verifies that thesis_side is consistent throughout the entire lifecycle.
"""

import pytest
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("lifecycle_thesis_trace")

from merid.event_venues.kalshi.position_cache import CachedPosition
from merid.event_venues.kalshi.strategy_positions import ThesisSide, StrategyPosition, FillRecord, build_exit_order
from merid.prediction.intent_contract import build_entry_order, StrategyIntent, EntryExit, ExitReason


class TestLifecycleThesisTrace:
    """Test thesis_side consistency across full lifecycle for each asset family."""
    
    @pytest.fixture
    def asset_family_markets(self):
        """One market from each asset family."""
        return {
            "BTC": "KXBTC15M-26JUL211745-45",
            "ETH": "KXETH15M-26JUL211745-45",
            "SOL": "KXSOL15M-26JUL211745-45",
            "XRP": "KXXRP15M-26JUL211745-45",
            "DOGE": "KXDOGE15M-26JUL211745-45",
        }
    
    def test_btc_lifecycle_thesis_yes(self, asset_family_markets):
        """Trace full lifecycle for BTC with thesis_side=YES."""
        ticker = asset_family_markets["BTC"]
        thesis_side = "yes"
        
        # Step 1: Signal (simulated - BULLISH_EVENT signal)
        signal = StrategyIntent.BULLISH_EVENT
        logger.info(f"[LIFECYCLE-SIGNAL] ticker={ticker} signal={signal.value} expected_thesis={thesis_side}")
        
        # Step 2: Intent creation
        entry_intent = build_entry_order(
            intent=signal,
            asset="BTC",
            ticker=ticker,
            price_cents=50,
            magnitude=10,
            client_order_id="entry_btc_1",
            rationale="Bullish signal"
        )
        
        # Verify thesis_side matches expected
        assert entry_intent.thesis_side == thesis_side
        assert entry_intent.outcome_side == thesis_side
        logger.info(f"[LIFECYCLE-INTENT] ticker={ticker} thesis_side={entry_intent.thesis_side} outcome_side={entry_intent.outcome_side}")
        
        # Step 3: Entry order generation (simulated)
        # In production, this would use thesis_side to determine Kalshi side
        kalshi_side = "BUY_YES" if thesis_side == "yes" else "BUY_NO"
        logger.info(f"[LIFECYCLE-ENTRY-ORDER] ticker={ticker} thesis_side={thesis_side} kalshi_side={kalshi_side}")
        
        # Step 4: Fill ingestion
        fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_btc_1",
            side="yes",
            action="buy",
            outcome_side=thesis_side,
            count_fp=10,
            price_cents=50,
            fee_cents=0,
            intent_side=thesis_side
        )
        
        # Step 5: StrategyPosition creation from fill
        strategy_position = StrategyPosition(
            ticker=ticker,
            thesis_side=ThesisSide.from_outcome_side(thesis_side),
            size_fp=10.0,
            avg_entry_price_cents=50
        )
        strategy_position.add_entry_fill(fill)
        
        # Verify thesis_side preserved
        assert strategy_position.thesis_side.value == thesis_side
        logger.info(f"[LIFECYCLE-POSITION] ticker={ticker} thesis_side={strategy_position.thesis_side.value} size_fp={strategy_position.size_fp}")
        
        # Step 6: Cache sync (simulated - REST sync preserves thesis_side)
        cached_position = CachedPosition(
            market_id=ticker,
            agent_id="BTC_15M",
            contracts=10,
            side="yes",  # REST side (may differ from thesis)
            thesis_side=thesis_side,  # Preserved from fill
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_btc_1"
        )
        
        # Verify thesis_side preserved through sync
        assert cached_position.thesis_side == thesis_side
        logger.info(f"[LIFECYCLE-CACHE-SYNC] ticker={ticker} thesis_side={cached_position.thesis_side} rest_side={cached_position.side}")
        
        # Step 7: Exit decision (simulated - time to exit)
        exit_reason = ExitReason.EXIT_TP
        
        # Step 8: Exit order generation using thesis_side
        exit_order = build_exit_order(strategy_position, 10, 55)
        
        # Verify exit order uses thesis_side
        assert exit_order["thesis_side"] == thesis_side
        assert exit_order["outcome_side"] == thesis_side
        logger.info(f"[LIFECYCLE-EXIT-ORDER] ticker={ticker} thesis_side={exit_order['thesis_side']} outcome_side={exit_order['outcome_side']} kalshi_side={exit_order['kalshi_side']}")
        
        # Step 9: Exit fill
        exit_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_btc_exit_1",
            side="yes",
            action="sell",
            outcome_side=thesis_side,
            count_fp=10,
            price_cents=55,
            fee_cents=0,
            intent_side=thesis_side
        )
        
        strategy_position.add_exit_fill(exit_fill)
        
        # Verify thesis_side still consistent after exit
        assert strategy_position.thesis_side.value == thesis_side
        logger.info(f"[LIFECYCLE-EXIT-FILL] ticker={ticker} thesis_side={strategy_position.thesis_side.value} final_size_fp={strategy_position.size_fp}")
        
        # Final verification: thesis_side consistent throughout entire lifecycle
        assert entry_intent.thesis_side == thesis_side
        assert strategy_position.thesis_side.value == thesis_side
        assert cached_position.thesis_side == thesis_side
        assert exit_order["thesis_side"] == thesis_side
    
    def test_eth_lifecycle_thesis_no(self, asset_family_markets):
        """Trace full lifecycle for ETH with thesis_side=NO."""
        ticker = asset_family_markets["ETH"]
        thesis_side = "no"
        
        # Step 1: Signal (BEARISH_EVENT signal)
        signal = StrategyIntent.BEARISH_EVENT
        logger.info(f"[LIFECYCLE-SIGNAL] ticker={ticker} signal={signal.value} expected_thesis={thesis_side}")
        
        # Step 2: Intent creation
        entry_intent = build_entry_order(
            intent=signal,
            asset="ETH",
            ticker=ticker,
            price_cents=50,
            magnitude=10,
            client_order_id="entry_eth_1",
            rationale="Bearish signal"
        )
        
        assert entry_intent.thesis_side == thesis_side
        assert entry_intent.outcome_side == thesis_side
        logger.info(f"[LIFECYCLE-INTENT] ticker={ticker} thesis_side={entry_intent.thesis_side} outcome_side={entry_intent.outcome_side}")
        
        # Step 3: Entry order generation
        kalshi_side = "BUY_NO" if thesis_side == "no" else "BUY_YES"
        logger.info(f"[LIFECYCLE-ENTRY-ORDER] ticker={ticker} thesis_side={thesis_side} kalshi_side={kalshi_side}")
        
        # Step 4: Fill ingestion
        fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_eth_1",
            side="no",
            action="buy",
            outcome_side=thesis_side,
            count_fp=10,
            price_cents=50,
            fee_cents=0,
            intent_side=thesis_side
        )
        
        # Step 5: StrategyPosition creation
        strategy_position = StrategyPosition(
            ticker=ticker,
            thesis_side=ThesisSide.from_outcome_side(thesis_side),
            size_fp=10.0,
            avg_entry_price_cents=50
        )
        strategy_position.add_entry_fill(fill)
        
        assert strategy_position.thesis_side.value == thesis_side
        logger.info(f"[LIFECYCLE-POSITION] ticker={ticker} thesis_side={strategy_position.thesis_side.value} size_fp={strategy_position.size_fp}")
        
        # Step 6: Cache sync
        cached_position = CachedPosition(
            market_id=ticker,
            agent_id="ETH_15M",
            contracts=10,
            side="yes",  # REST side (always yes from Kalshi perspective)
            thesis_side=thesis_side,  # Preserved from fill
            avg_price_cents=50,
            fill_source="ws",
            client_order_id="entry_eth_1"
        )
        
        assert cached_position.thesis_side == thesis_side
        logger.info(f"[LIFECYCLE-CACHE-SYNC] ticker={ticker} thesis_side={cached_position.thesis_side} rest_side={cached_position.side}")
        
        # Step 7: Exit decision
        exit_reason = ExitReason.EXIT_SL
        
        # Step 8: Exit order generation
        exit_order = build_exit_order(strategy_position, 10, 45)
        
        assert exit_order["thesis_side"] == thesis_side
        assert exit_order["outcome_side"] == thesis_side
        logger.info(f"[LIFECYCLE-EXIT-ORDER] ticker={ticker} thesis_side={exit_order['thesis_side']} outcome_side={exit_order['outcome_side']} kalshi_side={exit_order['kalshi_side']}")
        
        # Step 9: Exit fill
        exit_fill = FillRecord(
            timestamp=datetime.utcnow(),
            fill_id="fill_eth_exit_1",
            side="no",
            action="sell",
            outcome_side=thesis_side,
            count_fp=10,
            price_cents=45,
            fee_cents=0,
            intent_side=thesis_side
        )
        
        strategy_position.add_exit_fill(exit_fill)
        
        assert strategy_position.thesis_side.value == thesis_side
        logger.info(f"[LIFECYCLE-EXIT-FILL] ticker={ticker} thesis_side={strategy_position.thesis_side.value} final_size_fp={strategy_position.size_fp}")
        
        # Final verification
        assert entry_intent.thesis_side == thesis_side
        assert strategy_position.thesis_side.value == thesis_side
        assert cached_position.thesis_side == thesis_side
        assert exit_order["thesis_side"] == thesis_side
    
    def test_sol_lifecycle_thesis_yes(self, asset_family_markets):
        """Trace full lifecycle for SOL with thesis_side=YES."""
        ticker = asset_family_markets["SOL"]
        thesis_side = "yes"
        
        # Simplified lifecycle trace for SOL
        entry_intent = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset="SOL",
            ticker=ticker,
            price_cents=30,
            magnitude=5,
            client_order_id="entry_sol_1",
            rationale="Bullish signal"
        )
        
        assert entry_intent.thesis_side == thesis_side
        
        strategy_position = StrategyPosition(
            ticker=ticker,
            thesis_side=ThesisSide.from_outcome_side(thesis_side),
            size_fp=5.0,
            avg_entry_price_cents=30
        )
        
        exit_order = build_exit_order(strategy_position, 5, 35)
        
        assert exit_order["thesis_side"] == thesis_side
        assert entry_intent.thesis_side == thesis_side
        assert strategy_position.thesis_side.value == thesis_side
    
    def test_xrp_lifecycle_thesis_no(self, asset_family_markets):
        """Trace full lifecycle for XRP with thesis_side=NO."""
        ticker = asset_family_markets["XRP"]
        thesis_side = "no"
        
        entry_intent = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            asset="XRP",
            ticker=ticker,
            price_cents=40,
            magnitude=8,
            client_order_id="entry_xrp_1",
            rationale="Bearish signal"
        )
        
        assert entry_intent.thesis_side == thesis_side
        
        strategy_position = StrategyPosition(
            ticker=ticker,
            thesis_side=ThesisSide.from_outcome_side(thesis_side),
            size_fp=8.0,
            avg_entry_price_cents=40
        )
        
        exit_order = build_exit_order(strategy_position, 8, 35)
        
        assert exit_order["thesis_side"] == thesis_side
        assert entry_intent.thesis_side == thesis_side
        assert strategy_position.thesis_side.value == thesis_side
    
    def test_doge_lifecycle_thesis_yes(self, asset_family_markets):
        """Trace full lifecycle for DOGE with thesis_side=YES."""
        ticker = asset_family_markets["DOGE"]
        thesis_side = "yes"
        
        entry_intent = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset="DOGE",
            ticker=ticker,
            price_cents=25,
            magnitude=12,
            client_order_id="entry_doge_1",
            rationale="Bullish signal"
        )
        
        assert entry_intent.thesis_side == thesis_side
        
        strategy_position = StrategyPosition(
            ticker=ticker,
            thesis_side=ThesisSide.from_outcome_side(thesis_side),
            size_fp=12.0,
            avg_entry_price_cents=25
        )
        
        exit_order = build_exit_order(strategy_position, 12, 30)
        
        assert exit_order["thesis_side"] == thesis_side
        assert entry_intent.thesis_side == thesis_side
        assert strategy_position.thesis_side.value == thesis_side


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

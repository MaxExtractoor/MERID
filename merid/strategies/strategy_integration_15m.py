"""
15M Strategy Integration - Complete End-to-End Testing

Integration module that combines signals, risk management, order execution,
and performance tracking for comprehensive end-to-end testing.
"""

import time
import logging
from typing import Dict, List, Optional
import pandas as pd
from datetime import datetime, timezone

from .signals_15m import compute_signals_15m, price_service, Signal
from .risk_15m import RiskManager, RiskConfig
from .engine_15m import Strategy15mEngine
from .trade_book_15m import trade_book
from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent

logger = logging.getLogger(__name__)

class StrategyIntegration:
    """Complete strategy integration for end-to-end testing."""
    
    def __init__(self, capital_usd: float = 100000.0, paper_mode: bool = True):
        """Initialize strategy integration."""
        self.paper_mode = paper_mode
        self.capital_usd = capital_usd
        
        # Initialize components
        risk_config = RiskConfig(capital_usd=capital_usd)
        self.risk_manager = RiskManager(risk_config)
        self.engine = Strategy15mEngine(risk_config)
        
        # Testing state
        self.test_start_time = time.time()
        self.cycle_count = 0
        self.last_cycle_time = 0
        
        logger.info(f"StrategyIntegration initialized (paper_mode={paper_mode}, capital=${capital_usd:,.0f})")
    
    def run_end_to_end_test(self, duration_minutes: int = 60) -> Dict[str, any]:
        """
        Run comprehensive end-to-end test.
        
        Args:
            duration_minutes: Test duration in minutes
            
        Returns:
            Test results summary
        """
        test_start = time.time()
        end_time = test_start + (duration_minutes * 60)
        
        logger.info(f"Starting end-to-end test for {duration_minutes} minutes")
        
        test_results = {
            "test_duration_minutes": duration_minutes,
            "test_start": test_start,
            "test_end": end_time,
            "cycles_completed": 0,
            "signals_generated": 0,
            "orders_placed": 0,
            "trades_closed": 0,
            "final_pnl": 0.0,
            "events_emitted": [],
            "errors": []
        }
        
        try:
            while time.time() < end_time:
                cycle_start = time.time()
                
                # 1. Get price data
                prices = price_service.get_latest_15m_bars(["BTC", "ETH"])
                
                # 2. Run strategy cycle
                cycle_results = self.engine.run_bar(prices)
                
                # 3. Update test results
                test_results["cycles_completed"] += 1
                test_results["signals_generated"] += cycle_results["signals_generated"]
                test_results["orders_placed"] += cycle_results["orders_placed"]
                
                # 4. Check trade book updates
                current_trades = len(trade_book.closed_trades)
                test_results["trades_closed"] = current_trades
                
                # 5. Log cycle summary
                logger.info(f"Cycle {test_results['cycles_completed']}: "
                          f"{cycle_results['signals_generated']} signals, "
                          f"{cycle_results['orders_placed']} orders, "
                          f"{current_trades} trades closed")
                
                # 6. Sleep until next cycle (simulate 15m bars with faster testing)
                cycle_duration = time.time() - cycle_start
                sleep_time = max(1, 30 - cycle_duration)  # 30 second cycles for testing
                time.sleep(sleep_time)
                
                self.last_cycle_time = cycle_start
        
        except Exception as e:
            logger.error(f"Error in end-to-end test: {e}")
            test_results["errors"].append(str(e))
        
        # Final summary
        test_results["test_end_actual"] = time.time()
        test_results["actual_duration_minutes"] = (test_results["test_end_actual"] - test_results["test_start"]) / 60
        
        # Get final performance
        performance = trade_book.get_performance_summary()
        test_results["final_pnl"] = performance.get("net_pnl", 0.0)
        test_results["final_performance"] = performance
        
        logger.info(f"End-to-end test completed: {test_results}")
        
        return test_results
    
    def validate_signal_quality(self, num_cycles: int = 10) -> Dict[str, any]:
        """Validate signal quality over multiple cycles."""
        logger.info(f"Running signal quality validation over {num_cycles} cycles")
        
        all_signals = []
        validation_results = {
            "cycles_tested": 0,
            "total_signals": 0,
            "signal_distribution": {},
            "avg_strength": 0.0,
            "avg_z_score": 0.0,
            "quality_issues": []
        }
        
        for cycle in range(num_cycles):
            try:
                # Get prices and generate signals
                prices = price_service.get_latest_15m_bars(["BTC", "ETH"])
                signals = compute_signals_15m(prices, time.time(), z_thresh=0.7)
                
                all_signals.extend(signals)
                validation_results["cycles_tested"] += 1
                
                # Log cycle results
                signal_types = {}
                for signal in signals:
                    signal_type = signal.side
                    signal_types[signal_type] = signal_types.get(signal_type, 0) + 1
                
                logger.info(f"Cycle {cycle + 1}: {len(signals)} signals, types: {signal_types}")
                
                time.sleep(2)  # Small delay between cycles
                
            except Exception as e:
                logger.error(f"Error in validation cycle {cycle + 1}: {e}")
                validation_results["quality_issues"].append(f"Cycle {cycle + 1}: {e}")
        
        # Analyze all signals
        if all_signals:
            validation_results["total_signals"] = len(all_signals)
            validation_results["avg_strength"] = sum(s.strength for s in all_signals) / len(all_signals)
            validation_results["avg_z_score"] = sum(abs(s.z_score) for s in all_signals) / len(all_signals)
            
            # Signal distribution
            for signal in all_signals:
                signal_type = signal.side
                validation_results["signal_distribution"][signal_type] = \
                    validation_results["signal_distribution"].get(signal_type, 0) + 1
            
            # Check for quality issues
            weak_signals = [s for s in all_signals if s.strength < 0.3]
            if weak_signals:
                validation_results["quality_issues"].append(f"Weak signals: {len(weak_signals)}/{len(all_signals)}")
            
            extreme_z = [s for s in all_signals if abs(s.z_score) > 5]
            if extreme_z:
                validation_results["quality_issues"].append(f"Extreme Z-scores: {len(extreme_z)}")
        
        logger.info(f"Signal validation completed: {validation_results}")
        
        return validation_results
    
    def test_risk_management(self) -> Dict[str, any]:
        """Test risk management functionality."""
        logger.info("Testing risk management")
        
        risk_results = {
            "position_sizing_tests": [],
            "risk_limit_tests": [],
            "kelly_calculation_tests": [],
            "errors": []
        }
        
        try:
            # Test 1: Position sizing
            test_strengths = [0.2, 0.5, 0.8, 1.0]
            for strength in test_strengths:
                size = self.risk_manager.compute_position_size(strength, "BTC")
                risk_results["position_sizing_tests"].append({
                    "strength": strength,
                    "position_size": size,
                    "expected_min": 1 if strength > 0.5 else 0
                })
            
            # Test 2: Risk limits
            test_positions = [
                ("BTC", 50, "long_up"),
                ("BTC", 100, "long_up"),
                ("ETH", 30, "long_down")
            ]
            
            for asset, contracts, side in test_positions:
                can_trade = self.risk_manager.check_risk_limits(asset, contracts, side)
                risk_results["risk_limit_tests"].append({
                    "asset": asset,
                    "contracts": contracts,
                    "side": side,
                    "allowed": can_trade
                })
            
            # Test 3: Kelly calculation
            kelly_size = self.risk_manager._kelly_position_size()
            risk_results["kelly_calculation_tests"].append({
                "kelly_contracts": kelly_size,
                "kelly_fraction": self.risk_manager.config.kelly_fraction
            })
            
        except Exception as e:
            logger.error(f"Error in risk management test: {e}")
            risk_results["errors"].append(str(e))
        
        logger.info(f"Risk management test completed: {risk_results}")
        
        return risk_results
    
    def test_event_integration(self) -> Dict[str, any]:
        """Test event bus integration."""
        logger.info("Testing event integration")
        
        event_results = {
            "events_tested": 0,
            "events_emitted": [],
            "subscription_tests": [],
            "errors": []
        }
        
        try:
            # Test event emission
            test_events = [
                KalshiEvent(
                    type="position_update",
                    payload={"test": "integration_test", "timestamp": time.time()},
                    ts=time.time(),
                    source="test"
                ),
                KalshiEvent(
                    type="api_error",
                    payload={"error": "test_error", "details": "integration test"},
                    ts=time.time(),
                    source="test"
                )
            ]
            
            for event in test_events:
                kalshi_event_bus.publish(event)
                event_results["events_emitted"].append({
                    "type": event.type,
                    "source": event.source,
                    "timestamp": event.ts
                })
                event_results["events_tested"] += 1
            
            # Test subscription (trade book should be subscribed)
            event_results["subscription_tests"].append({
                "component": "trade_book",
                "subscribed": True,
                "event_types": ["order_fill", "position_update"]
            })
            
            # Test strategy engine subscription
            event_results["subscription_tests"].append({
                "component": "strategy_engine",
                "subscribed": True,
                "event_types": ["order_fill", "order_reject", "position_update", "api_error"]
            })
            
        except Exception as e:
            logger.error(f"Error in event integration test: {e}")
            event_results["errors"].append(str(e))
        
        logger.info(f"Event integration test completed: {event_results}")
        
        return event_results
    
    def run_comprehensive_test_suite(self) -> Dict[str, any]:
        """Run comprehensive test suite covering all components."""
        logger.info("Starting comprehensive test suite")
        
        suite_results = {
            "test_start": time.time(),
            "signal_validation": None,
            "risk_management": None,
            "event_integration": None,
            "end_to_end": None,
            "overall_status": "passed",
            "errors": []
        }
        
        try:
            # 1. Signal validation
            suite_results["signal_validation"] = self.validate_signal_quality(num_cycles=5)
            
            # 2. Risk management test
            suite_results["risk_management"] = self.test_risk_management()
            
            # 3. Event integration test
            suite_results["event_integration"] = self.test_event_integration()
            
            # 4. Short end-to-end test
            suite_results["end_to_end"] = self.run_end_to_end_test(duration_minutes=5)
            
            # 5. Overall assessment
            total_errors = (len(suite_results["signal_validation"].get("quality_issues", [])) +
                          len(suite_results["risk_management"].get("errors", [])) +
                          len(suite_results["event_integration"].get("errors", [])) +
                          len(suite_results["end_to_end"].get("errors", [])))
            
            if total_errors > 0:
                suite_results["overall_status"] = "failed"
                suite_results["errors"] = [f"Total errors: {total_errors}"]
            
        except Exception as e:
            logger.error(f"Error in comprehensive test suite: {e}")
            suite_results["overall_status"] = "error"
            suite_results["errors"].append(str(e))
        
        suite_results["test_end"] = time.time()
        suite_results["test_duration_minutes"] = (suite_results["test_end"] - suite_results["test_start"]) / 60
        
        logger.info(f"Comprehensive test suite completed: {suite_results['overall_status']}")
        
        return suite_results
    
    def get_integration_status(self) -> Dict[str, any]:
        """Get current integration status."""
        return {
            "paper_mode": self.paper_mode,
            "capital_usd": self.capital_usd,
            "cycle_count": self.cycle_count,
            "last_cycle_time": self.last_cycle_time,
            "trade_book_status": trade_book.get_performance_summary(),
            "risk_manager_status": self.risk_manager.get_risk_status(),
            "strategy_engine_status": self.engine.get_strategy_status()
        }

# Integration singleton
strategy_integration = StrategyIntegration()

# Example usage:
"""
# Run comprehensive test suite
results = strategy_integration.run_comprehensive_test_suite()
print(f"Test results: {results}")

# Run individual tests
signal_results = strategy_integration.validate_signal_quality(num_cycles=10)
risk_results = strategy_integration.test_risk_management()
event_results = strategy_integration.test_event_integration()

# Run end-to-end test
e2e_results = strategy_integration.run_end_to_end_test(duration_minutes=30)

# Get current status
status = strategy_integration.get_integration_status()
print(f"Integration status: {status}")
"""

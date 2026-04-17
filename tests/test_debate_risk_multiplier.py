#!/usr/bin/env python3
"""
Unit tests for DebateRiskMultiplier
Comprehensive test coverage for all debate risk adjustment scenarios.
"""

import pytest
from merid.trading.debate_risk_multiplier import DebateRiskMultiplier, apply_debate_risk_adjustment
from merid.trading.debate_risk_config import DEBATE_RISK_CONFIG

class TestDebateRiskMultiplier:
    """Test suite for DebateRiskMultiplier functionality"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.multiplier = DebateRiskMultiplier()
    
    def test_no_alerts_healthy_state(self):
        """Test healthy state with no alerts returns 1.0 multiplier"""
        context = {
            'status': 'healthy',
            'alerts_24h': {'critical': 0, 'warnings': 0, 'total': 0}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        assert adjustment.multiplier == 1.0
        assert adjustment.adjusted_size == 100
        assert not adjustment.should_warn
        assert adjustment.reason == 'No debate alerts - normal sizing'
        assert adjustment.debate_status == 'healthy'
    
    def test_single_critical_alert(self):
        """Test single critical alert reduces size by 20%"""
        context = {
            'status': 'critical',
            'alerts_24h': {'critical': 1, 'warnings': 0, 'total': 1}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        expected_multiplier = 1.0 - DEBATE_RISK_CONFIG.CRITICAL_REDUCTION_PER_ALERT
        assert adjustment.multiplier == expected_multiplier
        assert adjustment.adjusted_size == int(100 * expected_multiplier)
        assert adjustment.should_warn
        assert 'critical' in adjustment.reason.lower()
        assert adjustment.debate_status == 'critical'
    
    def test_multiple_critical_alerts_capped(self):
        """Test multiple critical alerts with capping"""
        context = {
            'status': 'critical',
            'alerts_24h': {'critical': 10, 'warnings': 0, 'total': 10}  # More than cap
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        # Should be capped at max_critical_alerts
        expected_multiplier = max(
            DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER,
            1.0 - (DEBATE_RISK_CONFIG.CRITICAL_REDUCTION_PER_ALERT * DEBATE_RISK_CONFIG.MAX_CRITICAL_ALERTS)
        )
        assert adjustment.multiplier == expected_multiplier
        assert adjustment.adjusted_size >= int(100 * DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER)
    
    def test_single_warning_alert(self):
        """Test single warning alert reduces size by 10%"""
        context = {
            'status': 'degraded',
            'alerts_24h': {'critical': 0, 'warnings': 1, 'total': 1}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        expected_multiplier = 1.0 - DEBATE_RISK_CONFIG.WARNING_REDUCTION_PER_ALERT
        assert adjustment.multiplier == expected_multiplier
        assert adjustment.adjusted_size == int(100 * expected_multiplier)
        assert adjustment.should_warn
        assert 'warning' in adjustment.reason.lower()
        assert adjustment.debate_status == 'degraded'
    
    def test_multiple_warnings_floored(self):
        """Test multiple warnings with minimum floor"""
        context = {
            'status': 'degraded',
            'alerts_24h': {'critical': 0, 'warnings': 10, 'total': 10}  # More than cap
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        # Should be capped at max_warning_alerts but floored at min_warning_multiplier
        expected_multiplier = max(
            DEBATE_RISK_CONFIG.MIN_WARNING_MULTIPLIER,
            1.0 - (DEBATE_RISK_CONFIG.WARNING_REDUCTION_PER_ALERT * DEBATE_RISK_CONFIG.MAX_WARNING_ALERTS)
        )
        assert adjustment.multiplier == expected_multiplier
        assert adjustment.adjusted_size >= int(100 * DEBATE_RISK_CONFIG.MIN_WARNING_MULTIPLIER)
    
    def test_unknown_status_no_alerts(self):
        """Test unknown status with no alerts treated as healthy"""
        context = {
            'status': 'unknown',
            'alerts_24h': {'critical': 0, 'warnings': 0, 'total': 0}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        # Unknown status with 0 alerts is treated as healthy
        assert adjustment.multiplier == 1.0
        assert adjustment.adjusted_size == 100
        assert not adjustment.should_warn
    
    def test_missing_context(self):
        """Test missing context returns conservative sizing"""
        adjustment = self.multiplier.calculate_multiplier(None, 100)
        
        assert adjustment.multiplier == DEBATE_RISK_CONFIG.UNKNOWN_MULTIPLIER
        assert adjustment.adjusted_size == int(100 * DEBATE_RISK_CONFIG.UNKNOWN_MULTIPLIER)
        assert adjustment.should_warn
        assert adjustment.debate_status == 'unknown'
        assert 'unavailable' in adjustment.reason.lower()
    
    def test_malformed_alerts_24h(self):
        """Test malformed alerts_24h is handled gracefully"""
        # Test with string instead of dict
        context = {
            'status': 'critical',
            'alerts_24h': 'invalid'
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        # Malformed alerts_24h is converted to empty dict, resulting in 0 alerts = healthy
        assert adjustment.multiplier == 1.0
        assert adjustment.adjusted_size == 100
        assert not adjustment.should_warn
        assert adjustment.alert_counts == {'critical': 0, 'warnings': 0, 'total': 0}
    
    def test_zero_base_size(self):
        """Test zero base size returns minimum size"""
        context = {
            'status': 'critical',
            'alerts_24h': {'critical': 1, 'warnings': 0, 'total': 1}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 0)
        
        assert adjustment.adjusted_size >= DEBATE_RISK_CONFIG.MIN_POSITION_SIZE
        assert adjustment.original_size == 0
    
    def test_convenience_function(self):
        """Test convenience function apply_debate_risk_adjustment"""
        context = {
            'status': 'critical',
            'alerts_24h': {'critical': 2, 'warnings': 0, 'total': 2}
        }
        
        adjustment = apply_debate_risk_adjustment(50, context)
        
        assert adjustment.adjusted_size < 50
        assert adjustment.adjusted_size >= DEBATE_RISK_CONFIG.MIN_POSITION_SIZE
        assert adjustment.original_size == 50
    
    def test_alert_counts_structure(self):
        """Test alert_counts structure is properly populated"""
        context = {
            'status': 'critical',
            'alerts_24h': {'critical': 2, 'warnings': 1, 'total': 3}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        assert adjustment.alert_counts['critical'] == 2
        assert adjustment.alert_counts['warnings'] == 1
        assert adjustment.alert_counts['total'] == 3
    
    def test_warning_message_content(self):
        """Test warning messages contain relevant information"""
        context = {
            'status': 'critical',
            'alerts_24h': {'critical': 1, 'warnings': 0, 'total': 1}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100)
        
        assert adjustment.warning_message != ''
        assert 'critical' in adjustment.warning_message.lower()
        assert '%' in adjustment.warning_message
    
    def test_extreme_values(self):
        """Test extreme values are handled safely"""
        # Very large base size
        context = {
            'status': 'critical',
            'alerts_24h': {'critical': 5, 'warnings': 0, 'total': 5}
        }
        
        adjustment = self.multiplier.calculate_multiplier(context, 100000)
        
        assert adjustment.adjusted_size < 100000
        assert adjustment.adjusted_size >= DEBATE_RISK_CONFIG.MIN_POSITION_SIZE
        
        # Maximum alerts
        extreme_context = {
            'status': 'critical',
            'alerts_24h': {'critical': 100, 'warnings': 50, 'total': 150}
        }
        
        adjustment = self.multiplier.calculate_multiplier(extreme_context, 1000)
        
        assert adjustment.multiplier == DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER
        assert adjustment.adjusted_size == int(1000 * DEBATE_RISK_CONFIG.MIN_CRITICAL_MULTIPLIER)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

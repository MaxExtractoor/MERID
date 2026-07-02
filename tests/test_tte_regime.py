"""Tests for TTE-specific behavior near expiry."""
import pytest

from merid.risk.tte_regime import (
    TTERegime,
    TTERegimeConfig,
    TTERegimeClassifier,
    get_tte_classifier,
)


class TestTTERegimeConfig:
    """Test TTE regime configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = TTERegimeConfig()
        assert config.approaching_threshold == 10.0
        assert config.critical_threshold == 5.0
        assert config.terminal_threshold == 2.0
        assert config.normal_size_multiplier == 1.0
        assert config.critical_size_multiplier == 0.5


class TestTTERegimeClassifier:
    """Test TTE regime classifier."""
    
    def test_classify_normal(self):
        """Test classification of normal regime (>10 min)."""
        classifier = TTERegimeClassifier()
        regime = classifier.classify(tte_seconds=720)  # 12 minutes
        assert regime == TTERegime.NORMAL
    
    def test_classify_approaching(self):
        """Test classification of approaching regime (5-10 min)."""
        classifier = TTERegimeClassifier()
        regime = classifier.classify(tte_seconds=420)  # 7 minutes
        assert regime == TTERegime.APPROACHING
    
    def test_classify_critical(self):
        """Test classification of critical regime (2-5 min)."""
        classifier = TTERegimeClassifier()
        regime = classifier.classify(tte_seconds=240)  # 4 minutes
        assert regime == TTERegime.CRITICAL
    
    def test_classify_terminal(self):
        """Test classification of terminal regime (<2 min)."""
        classifier = TTERegimeClassifier()
        regime = classifier.classify(tte_seconds=90)  # 1.5 minutes
        assert regime == TTERegime.TERMINAL
    
    def test_classify_boundary_critical(self):
        """Test classification at critical boundary (exactly 5 min)."""
        classifier = TTERegimeClassifier()
        regime = classifier.classify(tte_seconds=300)  # 5 minutes
        # Boundary is exclusive (< 5 min = critical), so 5 min is approaching
        assert regime == TTERegime.APPROACHING
    
    def test_classify_boundary_terminal(self):
        """Test classification at terminal boundary (exactly 2 min)."""
        classifier = TTERegimeClassifier()
        regime = classifier.classify(tte_seconds=120)  # 2 minutes
        # Boundary is exclusive (< 2 min = terminal), so 2 min is critical
        assert regime == TTERegime.CRITICAL
    
    def test_get_size_multiplier_normal(self):
        """Test size multiplier in normal regime."""
        classifier = TTERegimeClassifier()
        multiplier = classifier.get_size_multiplier(tte_seconds=720)
        assert multiplier == 1.0
    
    def test_get_size_multiplier_critical(self):
        """Test size multiplier in critical regime."""
        classifier = TTERegimeClassifier()
        multiplier = classifier.get_size_multiplier(tte_seconds=240)
        assert multiplier == 0.5
    
    def test_get_size_multiplier_terminal(self):
        """Test size multiplier in terminal regime."""
        classifier = TTERegimeClassifier()
        multiplier = classifier.get_size_multiplier(tte_seconds=90)
        assert multiplier == 0.25
    
    def test_get_edge_multiplier_normal(self):
        """Test edge multiplier in normal regime."""
        classifier = TTERegimeClassifier()
        multiplier = classifier.get_edge_multiplier(tte_seconds=720)
        assert multiplier == 1.0
    
    def test_get_edge_multiplier_critical(self):
        """Test edge multiplier in critical regime."""
        classifier = TTERegimeClassifier()
        multiplier = classifier.get_edge_multiplier(tte_seconds=240)
        assert multiplier == 1.5
    
    def test_get_edge_multiplier_terminal(self):
        """Test edge multiplier in terminal regime."""
        classifier = TTERegimeClassifier()
        multiplier = classifier.get_edge_multiplier(tte_seconds=90)
        assert multiplier == 2.0
    
    def test_get_max_spread_normal(self):
        """Test max spread in normal regime."""
        classifier = TTERegimeClassifier()
        max_spread = classifier.get_max_spread(tte_seconds=720)
        assert max_spread == 40
    
    def test_get_max_spread_critical(self):
        """Test max spread in critical regime."""
        classifier = TTERegimeClassifier()
        max_spread = classifier.get_max_spread(tte_seconds=240)
        assert max_spread == 20
    
    def test_get_max_spread_terminal(self):
        """Test max spread in terminal regime."""
        classifier = TTERegimeClassifier()
        max_spread = classifier.get_max_spread(tte_seconds=90)
        assert max_spread == 10
    
    def test_get_min_depth_normal(self):
        """Test min depth in normal regime."""
        classifier = TTERegimeClassifier()
        min_depth = classifier.get_min_depth(tte_seconds=720)
        assert min_depth == 5
    
    def test_get_min_depth_critical(self):
        """Test min depth in critical regime."""
        classifier = TTERegimeClassifier()
        min_depth = classifier.get_min_depth(tte_seconds=240)
        assert min_depth == 15
    
    def test_get_min_depth_terminal(self):
        """Test min depth in terminal regime."""
        classifier = TTERegimeClassifier()
        min_depth = classifier.get_min_depth(tte_seconds=90)
        assert min_depth == 20
    
    def test_should_allow_entry_normal(self):
        """Test entry allowed in normal regime."""
        classifier = TTERegimeClassifier()
        allowed = classifier.should_allow_entry(tte_seconds=720)
        assert allowed == True
    
    def test_should_allow_entry_critical(self):
        """Test entry allowed in critical regime."""
        classifier = TTERegimeClassifier()
        allowed = classifier.should_allow_entry(tte_seconds=240)
        assert allowed == True
    
    def test_should_allow_entry_terminal(self):
        """Test entry blocked in terminal regime."""
        classifier = TTERegimeClassifier()
        allowed = classifier.should_allow_entry(tte_seconds=90)
        assert allowed == False
    
    def test_custom_config(self):
        """Test classifier with custom configuration."""
        config = TTERegimeConfig(
            approaching_threshold=5.0,
            critical_threshold=3.0,
            terminal_threshold=1.0,
        )
        classifier = TTERegimeClassifier(config)
        
        # With custom thresholds, 240 seconds (4 min) should be approaching (5-10 min range)
        regime = classifier.classify(tte_seconds=240)
        assert regime == TTERegime.APPROACHING
        
        # 150 seconds (2.5 min) should be critical with custom threshold (1-3 min range)
        regime = classifier.classify(tte_seconds=150)
        assert regime == TTERegime.CRITICAL


class TestTTEClassifierSingleton:
    """Test TTE classifier singleton."""
    
    def test_get_tte_classifier(self):
        """Test singleton pattern."""
        classifier1 = get_tte_classifier()
        classifier2 = get_tte_classifier()
        
        assert classifier1 is classifier2

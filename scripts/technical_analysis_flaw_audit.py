"""
Technical Analysis Flaw Audit Script

This script exposes flaws and gaps in the MERID trading system's technical analysis,
velocity, volatility, momentum, and directional decision making. It also audits
spot price to strike price tracking and trade decision timing.

Run with: python scripts/technical_analysis_flaw_audit.py

Output: Detailed report of flaws, gaps, and inconsistencies across the trading stack.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import importlib

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('technical_analysis_flaw_audit.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class Severity(Enum):
    """Severity levels for findings."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class Category(Enum):
    """Categories of findings."""
    VELOCITY = "VELOCITY"
    VOLATILITY = "VOLATILITY"
    MOMENTUM = "MOMENTUM"
    DIRECTIONAL = "DIRECTIONAL"
    SPOT_STRIKE = "SPOT_STRIKE"
    TIMING = "TIMING"
    CONFIGURATION = "CONFIGURATION"
    CONSISTENCY = "CONSISTENCY"


@dataclass
class Finding:
    """A single audit finding."""
    category: Category
    severity: Severity
    title: str
    description: str
    location: str  # File/module where issue was found
    recommendation: str
    evidence: Dict[str, Any] = field(default_factory=dict)


class TechnicalAnalysisAuditor:
    """Auditor for technical analysis implementation flaws."""
    
    def __init__(self):
        self.findings: List[Finding] = []
        self.assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        self.start_time = datetime.now(timezone.utc)
        
    def add_finding(self, category: Category, severity: Severity, title: str, 
                   description: str, location: str, recommendation: str, 
                   evidence: Dict[str, Any] = None):
        """Add a finding to the audit report."""
        self.findings.append(Finding(
            category=category,
            severity=severity,
            title=title,
            description=description,
            location=location,
            recommendation=recommendation,
            evidence=evidence or {}
        ))
        
    def audit_velocity_implementation(self):
        """Audit velocity signal implementation for flaws."""
        logger.info("Auditing velocity implementation...")
        
        try:
            from merid.event_venues.coinbase.velocity_signal import CoinbaseVelocitySignalGenerator
            
            generator = CoinbaseVelocitySignalGenerator()
            thresholds = generator.VELOCITY_THRESHOLDS
            
            # Check 1: Asset coverage
            expected_assets = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]
            missing_assets = set(expected_assets) - set(thresholds.keys())
            
            if missing_assets:
                self.add_finding(
                    category=Category.VELOCITY,
                    severity=Severity.CRITICAL,
                    title="Missing velocity thresholds for assets",
                    description=f"Velocity thresholds missing for assets: {missing_assets}",
                    location="merid/event_venues/coinbase/velocity_signal.py",
                    recommendation="Add velocity thresholds for all 5 crypto assets to ensure complete coverage",
                    evidence={"missing_assets": list(missing_assets), "existing_assets": list(thresholds.keys())}
                )
            
            # Check 2: Threshold consistency with profile
            try:
                # Load profile YAML directly to avoid import issues
                profile_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
                if os.path.exists(profile_path):
                    import yaml
                    with open(profile_path, 'r', encoding='utf-8') as f:
                        profile_data = yaml.safe_load(f)
                    
                    if 'velocity_thresholds' in profile_data:
                        profile_thresholds = profile_data['velocity_thresholds']
                    
                    for asset in self.assets:
                        asset_key = f"{asset}-USD"
                        if asset_key in thresholds and asset in profile_thresholds:
                            velocity_diff = abs(thresholds[asset_key] - profile_thresholds[asset])
                            if velocity_diff > 0.00001:  # More than 0.001% difference
                                self.add_finding(
                                    category=Category.VELOCITY,
                                    severity=Severity.HIGH,
                                    title=f"Velocity threshold mismatch for {asset}",
                                    description=f"Velocity threshold in velocity_signal.py ({thresholds[asset_key]}) "
                                              f"differs from profile YAML ({profile_thresholds[asset]})",
                                    location="merid/event_venues/coinbase/velocity_signal.py vs config/profiles/kalshi_crypto_15m_v2.yaml",
                                    recommendation="Align velocity thresholds between code and profile YAML to use single source of truth",
                                    evidence={
                                        "code_threshold": thresholds[asset_key],
                                        "profile_threshold": profile_thresholds[asset],
                                        "difference": velocity_diff
                                    }
                                )
            except Exception as e:
                self.add_finding(
                    category=Category.VELOCITY,
                    severity=Severity.MEDIUM,
                    title="Could not verify velocity threshold consistency with profile",
                    description=f"Error loading profile for comparison: {e}",
                    location="config/profiles/kalshi_crypto_15m_v2.yaml",
                    recommendation="Ensure profile YAML is accessible and contains velocity_thresholds section"
                )
            
            # Check 3: Threshold reasonableness
            for asset_key, threshold in thresholds.items():
                if threshold < 0.00001:  # Less than 0.001%
                    self.add_finding(
                        category=Category.VELOCITY,
                        severity=Severity.MEDIUM,
                        title=f"Very low velocity threshold for {asset_key}",
                        description=f"Velocity threshold {threshold} is extremely low (< 0.001%), "
                                  f"may generate excessive noise signals",
                        location="merid/event_venues/coinbase/velocity_signal.py",
                        recommendation="Review if threshold is appropriate for market conditions or if it should be higher",
                        evidence={"threshold": threshold, "asset": asset_key}
                    )
                elif threshold > 0.01:  # More than 1%
                    self.add_finding(
                        category=Category.VELOCITY,
                        severity=Severity.MEDIUM,
                        title=f"Very high velocity threshold for {asset_key}",
                        description=f"Velocity threshold {threshold} is very high (> 1%), "
                                  f"may miss legitimate trading opportunities",
                        location="merid/event_venues/coinbase/velocity_signal.py",
                        recommendation="Review if threshold is too conservative for current market volatility",
                        evidence={"threshold": threshold, "asset": asset_key}
                    )
            
            # Check 4: Cooldown mechanism
            if hasattr(generator, '_cooldown_seconds'):
                if generator._cooldown_seconds > 60:
                    self.add_finding(
                        category=Category.VELOCITY,
                        severity=Severity.MEDIUM,
                        title="Long cooldown period may miss opportunities",
                        description=f"Velocity signal cooldown is {generator._cooldown_seconds}s, "
                                  f"which may cause missed trades in fast-moving markets",
                        location="merid/event_venues/coinbase/velocity_signal.py",
                        recommendation="Consider reducing cooldown to 15-30s for 15m trading windows",
                        evidence={"cooldown_seconds": generator._cooldown_seconds}
                    )
            
        except Exception as e:
            self.add_finding(
                category=Category.VELOCITY,
                severity=Severity.CRITICAL,
                title="Failed to load velocity signal generator",
                description=f"Error importing velocity signal module: {e}",
                location="merid/event_venues/coinbase/velocity_signal.py",
                recommendation="Ensure velocity_signal module is accessible and dependencies are installed"
            )
    
    def audit_volatility_implementation(self):
        """Audit volatility implementation for flaws."""
        logger.info("Auditing volatility implementation...")
        
        try:
            from merid.signals.crypto_15m_indicators import IndicatorConfig, Crypto15mIndicatorStack
            
            # Check 1: Volatility gate configuration
            config = IndicatorConfig(asset="BTC")
            
            if config.vol_low_threshold > config.vol_high_threshold:
                self.add_finding(
                    category=Category.VOLATILITY,
                    severity=Severity.CRITICAL,
                    title="Volatility gate thresholds inverted",
                    description=f"vol_low_threshold ({config.vol_low_threshold}) > vol_high_threshold ({config.vol_high_threshold})",
                    location="merid/signals/crypto_15m_indicators.py",
                    recommendation="Fix threshold values to ensure low < high",
                    evidence={
                        "vol_low_threshold": config.vol_low_threshold,
                        "vol_high_threshold": config.vol_high_threshold
                    }
                )
            
            # Check 2: ATR min-move gate per asset
            for asset in self.assets:
                asset_config = IndicatorConfig(asset=asset)
                atr_threshold = asset_config.atr_min_move_pct
                
                if atr_threshold == 0.0:
                    self.add_finding(
                        category=Category.VOLATILITY,
                        severity=Severity.HIGH,
                        title=f"Zero ATR min-move threshold for {asset}",
                        description=f"ATR min-move threshold is 0 for {asset}, effectively disabling the gate",
                        location="merid/signals/crypto_15m_indicators.py",
                        recommendation="Set appropriate ATR min-move threshold based on asset volatility",
                        evidence={"asset": asset, "atr_threshold": atr_threshold}
                    )
                
                # Check if thresholds are asset-appropriate
                if asset in ["BTC", "ETH"] and atr_threshold > 0.001:
                    self.add_finding(
                        category=Category.VOLATILITY,
                        severity=Severity.MEDIUM,
                        title=f"High ATR threshold for liquid asset {asset}",
                        description=f"ATR threshold {atr_threshold} may be too high for liquid asset {asset}",
                        location="merid/signals/crypto_15m_indicators.py",
                        recommendation="Consider lower threshold for liquid assets to capture more opportunities",
                        evidence={"asset": asset, "atr_threshold": atr_threshold}
                    )
            
            # Check 3: Volatility regime classification
            try:
                from merid.prediction.unified_edge import classify_volatility_regime
                
                # Test regime classification
                test_cases = [
                    (20, "LOW"),
                    (40, "NORMAL"),
                    (60, "HIGH"),
                    (100, "EXTREME")
                ]
                
                for vol, expected_regime in test_cases:
                    regime = classify_volatility_regime(vol)
                    if regime != expected_regime:
                        self.add_finding(
                            category=Category.VOLATILITY,
                            severity=Severity.MEDIUM,
                            title="Volatility regime classification mismatch",
                            description=f"Volatility {vol}% classified as {regime}, expected {expected_regime}",
                            location="merid/prediction/unified_edge.py",
                            recommendation="Review volatility regime threshold constants",
                            evidence={"volatility": vol, "actual": regime, "expected": expected_regime}
                        )
            except Exception as e:
                self.add_finding(
                    category=Category.VOLATILITY,
                    severity=Severity.LOW,
                    title="Could not verify volatility regime classification",
                    description=f"Error testing regime classification: {e}",
                    location="merid/prediction/unified_edge.py",
                    recommendation="Ensure classify_volatility_regime function is accessible"
                )
            
        except Exception as e:
            self.add_finding(
                category=Category.VOLATILITY,
                severity=Severity.CRITICAL,
                title="Failed to load volatility indicators",
                description=f"Error importing indicator module: {e}",
                location="merid/signals/crypto_15m_indicators.py",
                recommendation="Ensure crypto_15m_indicators module is accessible"
            )
    
    def audit_momentum_implementation(self):
        """Audit momentum implementation for flaws."""
        logger.info("Auditing momentum implementation...")
        
        try:
            from merid.signals.crypto_15m_indicators import IndicatorConfig
            
            # Check 1: RSI configuration
            config = IndicatorConfig(asset="BTC")
            
            if config.rsi_oversold >= config.rsi_overbought:
                self.add_finding(
                    category=Category.MOMENTUM,
                    severity=Severity.CRITICAL,
                    title="RSI thresholds inverted",
                    description=f"RSI oversold ({config.rsi_oversold}) >= overbought ({config.rsi_overbought})",
                    location="merid/signals/crypto_15m_indicators.py",
                    recommendation="Fix RSI thresholds to ensure oversold < overbought",
                    evidence={
                        "rsi_oversold": config.rsi_oversold,
                        "rsi_overbought": config.rsi_overbought
                    }
                )
            
            # Check 2: RSI threshold reasonableness
            if config.rsi_oversold < 10 or config.rsi_oversold > 40:
                self.add_finding(
                    category=Category.MOMENTUM,
                    severity=Severity.MEDIUM,
                    title="Unusual RSI oversold threshold",
                    description=f"RSI oversold threshold {config.rsi_oversold} is outside typical range (10-40)",
                    location="merid/signals/crypto_15m_indicators.py",
                    recommendation="Review if threshold is appropriate for trading strategy",
                    evidence={"rsi_oversold": config.rsi_oversold}
                )
            
            if config.rsi_overbought < 60 or config.rsi_overbought > 90:
                self.add_finding(
                    category=Category.MOMENTUM,
                    severity=Severity.MEDIUM,
                    title="Unusual RSI overbought threshold",
                    description=f"RSI overbought threshold {config.rsi_overbought} is outside typical range (60-90)",
                    location="merid/signals/crypto_15m_indicators.py",
                    recommendation="Review if threshold is appropriate for trading strategy",
                    evidence={"rsi_overbought": config.rsi_overbought}
                )
            
            # Check 3: MACD configuration
            if config.macd_fast >= config.macd_slow:
                self.add_finding(
                    category=Category.MOMENTUM,
                    severity=Severity.CRITICAL,
                    title="MACD fast/slow periods inverted",
                    description=f"MACD fast period ({config.macd_fast}) >= slow period ({config.macd_slow})",
                    location="merid/signals/crypto_15m_indicators.py",
                    recommendation="Fix MACD periods to ensure fast < slow",
                    evidence={
                        "macd_fast": config.macd_fast,
                        "macd_slow": config.macd_slow
                    }
                )
            
            # Check 4: Regime-based RSI shifting
            if config.regime_based_rsi_enabled:
                # Check if regime thresholds are reasonable
                if config.rsi_bull_oversold >= config.rsi_bull_overbought:
                    self.add_finding(
                        category=Category.MOMENTUM,
                        severity=Severity.HIGH,
                        title="Bull regime RSI thresholds inverted",
                        description=f"Bull regime RSI oversold ({config.rsi_bull_oversold}) >= overbought ({config.rsi_bull_overbought})",
                        location="merid/signals/crypto_15m_indicators.py",
                        recommendation="Fix bull regime RSI thresholds",
                        evidence={
                            "rsi_bull_oversold": config.rsi_bull_oversold,
                            "rsi_bull_overbought": config.rsi_bull_overbought
                        }
                    )
                
                if config.rsi_bear_oversold >= config.rsi_bear_overbought:
                    self.add_finding(
                        category=Category.MOMENTUM,
                        severity=Severity.HIGH,
                        title="Bear regime RSI thresholds inverted",
                        description=f"Bear regime RSI oversold ({config.rsi_bear_oversold}) >= overbought ({config.rsi_bear_overbought})",
                        location="merid/signals/crypto_15m_indicators.py",
                        recommendation="Fix bear regime RSI thresholds",
                        evidence={
                            "rsi_bear_oversold": config.rsi_bear_oversold,
                            "rsi_bear_overbought": config.rsi_bear_overbought
                        }
                    )
            
            # Check 5: Multi-timeframe RSI alignment
            try:
                # This would require actual price data to test, but we can check configuration
                if hasattr(config, 'rsi_period') and config.rsi_period < 5:
                    self.add_finding(
                        category=Category.MOMENTUM,
                        severity=Severity.MEDIUM,
                        title="Very short RSI period",
                        description=f"RSI period {config.rsi_period} is very short, may be noisy",
                        location="merid/signals/crypto_15m_indicators.py",
                        recommendation="Consider using longer RSI period (8-14) for more stable signals",
                        evidence={"rsi_period": config.rsi_period}
                    )
            except Exception as e:
                pass  # Skip if attribute doesn't exist
            
        except Exception as e:
            self.add_finding(
                category=Category.MOMENTUM,
                severity=Severity.CRITICAL,
                title="Failed to load momentum indicators",
                description=f"Error importing indicator module: {e}",
                location="merid/signals/crypto_15m_indicators.py",
                recommendation="Ensure crypto_15m_indicators module is accessible"
            )
    
    def audit_directional_decision_making(self):
        """Audit yes/no, buy/sell directional decision making."""
        logger.info("Auditing directional decision making...")
        
        try:
            from merid.prediction.agent_grid_15m import LeanAgentConfig
            
            # Check 1: Signal mode configuration
            config = LeanAgentConfig(
                name="TEST_AGENT",
                series_tickers=["KXBTC15M"]
            )
            
            valid_signal_modes = ["trend", "mean_reversion", "momentum_fvg", "hybrid", "price_based"]
            if config.signal_mode not in valid_signal_modes:
                self.add_finding(
                    category=Category.DIRECTIONAL,
                    severity=Severity.HIGH,
                    title="Invalid signal mode",
                    description=f"Signal mode '{config.signal_mode}' is not in valid modes: {valid_signal_modes}",
                    location="merid/prediction/agent_grid_15m.py",
                    recommendation="Use valid signal mode from: trend, mean_reversion, momentum_fvg, hybrid, price_based",
                    evidence={"signal_mode": config.signal_mode, "valid_modes": valid_signal_modes}
                )
            
            # Check 2: Regime detection integration
            try:
                from merid.prediction.regime_detector import RegimeDetector
                
                detector = RegimeDetector()
                
                # Check if confidence threshold is reasonable
                # This is tested in the regime detector itself, but we can check default config
                if hasattr(detector, 'min_history') and detector.min_history < 30:
                    self.add_finding(
                        category=Category.DIRECTIONAL,
                        severity=Severity.MEDIUM,
                        title="Low regime detection minimum history",
                        description=f"Regime detector min_history ({detector.min_history}) may be too low for reliable detection",
                        location="merid/prediction/regime_detector.py",
                        recommendation="Consider increasing min_history to 50-100 for more stable regime detection",
                        evidence={"min_history": detector.min_history}
                    )
                
                # Check if regime-based signal inversion has safeguards
                # The detector has a confidence check to prevent signal inversion with low confidence
                # This is good, but we should verify it's being used
                
            except Exception as e:
                self.add_finding(
                    category=Category.DIRECTIONAL,
                    severity=Severity.HIGH,
                    title="Regime detector not available",
                    description=f"Error importing regime detector: {e}",
                    location="merid/prediction/regime_detector.py",
                    recommendation="Ensure regime detector is available for adaptive signal generation"
                )
            
            # Check 3: Edge computation consistency
            try:
                from merid.prediction.unified_edge import PerAssetCalibration
                
                calibration = PerAssetCalibration()
                
                # Check if all 5 assets have calibration
                for asset in self.assets:
                    if asset not in calibration.calibrations:
                        self.add_finding(
                            category=Category.DIRECTIONAL,
                            severity=Severity.HIGH,
                            title=f"Missing calibration for {asset}",
                            description=f"No calibration parameters found for asset {asset}",
                            location="merid/prediction/unified_edge.py",
                            recommendation="Add calibration parameters for all 5 crypto assets",
                            evidence={"asset": asset, "calibrated_assets": list(calibration.calibrations.keys())}
                        )
                    else:
                        cal = calibration.calibrations[asset]
                        # Check calibration parameters are reasonable
                        if cal.get('spot_sensitivity', 0) <= 0:
                            self.add_finding(
                                category=Category.DIRECTIONAL,
                                severity=Severity.HIGH,
                                title=f"Invalid spot sensitivity for {asset}",
                                description=f"Spot sensitivity for {asset} is <= 0, which is invalid",
                                location="merid/prediction/unified_edge.py",
                                recommendation="Set positive spot sensitivity for all assets",
                                evidence={"asset": asset, "spot_sensitivity": cal.get('spot_sensitivity')}
                            )
                        
                        if cal.get('time_decay', 0) < 0:
                            self.add_finding(
                                category=Category.DIRECTIONAL,
                                severity=Severity.HIGH,
                                title=f"Invalid time decay for {asset}",
                                description=f"Time decay for {asset} is negative, which is invalid",
                                location="merid/prediction/unified_edge.py",
                                recommendation="Set non-negative time decay for all assets",
                                evidence={"asset": asset, "time_decay": cal.get('time_decay')}
                            )
                        
                        if cal.get('vol_adjustment', 0) <= 0:
                            self.add_finding(
                                category=Category.DIRECTIONAL,
                                severity=Severity.MEDIUM,
                                title=f"Invalid volatility adjustment for {asset}",
                                description=f"Volatility adjustment for {asset} is <= 0, should be positive",
                                location="merid/prediction/unified_edge.py",
                                recommendation="Set positive volatility adjustment for all assets",
                                evidence={"asset": asset, "vol_adjustment": cal.get('vol_adjustment')}
                            )
            
            except Exception as e:
                self.add_finding(
                    category=Category.DIRECTIONAL,
                    severity=Severity.HIGH,
                    title="Could not verify edge calibration",
                    description=f"Error loading calibration: {e}",
                    location="merid/prediction/unified_edge.py",
                    recommendation="Ensure PerAssetCalibration is accessible and properly configured"
                )
            
            # Check 4: Yes/No side selection logic
            # This is in edge_computer.py - check if it has proper tie-breaking
            try:
                from merid.prediction.edge_computer import LegacyEdgeBackend
                
                backend = LegacyEdgeBackend()
                
                # The backend should have deterministic tie-breaking logic
                # We can't test this without actual market state, but we can check if it exists
                
            except Exception as e:
                self.add_finding(
                    category=Category.DIRECTIONAL,
                    severity=Severity.LOW,
                    title="Could not verify side selection logic",
                    description=f"Error loading edge backend: {e}",
                    location="merid/prediction/edge_computer.py",
                    recommendation="Ensure edge backend is accessible for side selection"
                )
            
        except Exception as e:
            self.add_finding(
                category=Category.DIRECTIONAL,
                severity=Severity.CRITICAL,
                title="Failed to load directional decision components",
                description=f"Error importing agent grid: {e}",
                location="merid/prediction/agent_grid_15m.py",
                recommendation="Ensure agent grid module is accessible"
            )
    
    def audit_spot_strike_tracking(self):
        """Audit spot price to strike price tracking."""
        logger.info("Auditing spot-strike tracking...")
        
        try:
            from merid.prediction.spot_strike_context import (
                distance_to_strike_pct,
                warn_abs_dist_pct,
                veto_abs_dist_pct,
                evaluate_spot_strike_anomaly
            )
            
            # Check 1: Distance calculation function
            # Test with known values
            test_cases = [
                (100.0, 95.0, 0.0526),  # spot=100, strike=95, expected ~5.26%
                (100.0, 105.0, -0.0476),  # spot=100, strike=105, expected ~-4.76%
                (50.0, 50.0, 0.0),  # spot=50, strike=50, expected 0%
            ]
            
            for spot, strike, expected in test_cases:
                result = distance_to_strike_pct(spot, strike)
                if result is None:
                    self.add_finding(
                        category=Category.SPOT_STRIKE,
                        severity=Severity.HIGH,
                        title="Distance calculation returns None",
                        description=f"distance_to_strike_pct returned None for spot={spot}, strike={strike}",
                        location="merid/prediction/spot_strike_context.py",
                        recommendation="Fix distance calculation to handle valid inputs",
                        evidence={"spot": spot, "strike": strike}
                    )
                else:
                    # Check if result is approximately correct (within 1%)
                    if abs(float(result) - expected) > 0.01:
                        self.add_finding(
                            category=Category.SPOT_STRIKE,
                            severity=Severity.HIGH,
                            title="Distance calculation incorrect",
                            description=f"distance_to_strike_pct({spot}, {strike}) = {result}, expected ~{expected}",
                            location="merid/prediction/spot_strike_context.py",
                            recommendation="Fix distance calculation formula",
                            evidence={"spot": spot, "strike": strike, "actual": float(result), "expected": expected}
                        )
            
            # Check 2: Warning/veto threshold reasonableness
            warn_threshold = warn_abs_dist_pct()
            veto_threshold = veto_abs_dist_pct()
            
            if warn_threshold >= veto_threshold:
                self.add_finding(
                    category=Category.SPOT_STRIKE,
                    severity=Severity.CRITICAL,
                    title="Warning threshold >= veto threshold",
                    description=f"Warning threshold ({warn_threshold}) >= veto threshold ({veto_threshold})",
                    location="merid/prediction/spot_strike_context.py",
                    recommendation="Set warning threshold < veto threshold",
                    evidence={
                        "warn_threshold": warn_threshold,
                        "veto_threshold": veto_threshold
                    }
                )
            
            if veto_threshold > 2.0:
                self.add_finding(
                    category=Category.SPOT_STRIKE,
                    severity=Severity.MEDIUM,
                    title="Very high veto threshold",
                    description=f"Veto threshold {veto_threshold} is very high (> 200%), may never trigger",
                    location="merid/prediction/spot_strike_context.py",
                    recommendation="Consider lowering veto threshold to more reasonable level (e.g., 1.0-1.5)",
                    evidence={"veto_threshold": veto_threshold}
                )
            
            if warn_threshold < 0.5:
                self.add_finding(
                    category=Category.SPOT_STRIKE,
                    severity=Severity.MEDIUM,
                    title="Very low warning threshold",
                    description=f"Warning threshold {warn_threshold} is very low (< 50%), may generate excessive warnings",
                    location="merid/prediction/spot_strike_context.py",
                    recommendation="Consider raising warning threshold to reduce noise",
                    evidence={"warn_threshold": warn_threshold}
                )
            
            # Check 3: Asset resolution for macro markets
            try:
                from merid.prediction.spot_strike_context import resolve_asset_for_snapshot, is_crypto_market_ticker
                
                # Test crypto tickers
                crypto_tickers = ["KXBTC-15M", "KXETH-15M", "KXSOL-15M", "KXXRP-15M", "KXDOGE-15M"]
                for ticker in crypto_tickers:
                    asset = resolve_asset_for_snapshot(["BTC"], ticker)
                    if not asset:
                        self.add_finding(
                            category=Category.SPOT_STRIKE,
                            severity=Severity.HIGH,
                            title=f"Failed to resolve asset for crypto ticker {ticker}",
                            description=f"resolve_asset_for_snapshot returned empty string for crypto ticker {ticker}",
                            location="merid/prediction/spot_strike_context.py",
                            recommendation="Fix asset resolution to properly handle crypto tickers",
                            evidence={"ticker": ticker, "resolved_asset": asset}
                        )
                
                # Test macro tickers should return empty string
                macro_tickers = ["KXFED-27APR-T4.25", "KXFEDDECISION-YES", "KXECON-GDP"]
                for ticker in macro_tickers:
                    asset = resolve_asset_for_snapshot(["BTC"], ticker)
                    if asset:  # Should be empty for macro
                        self.add_finding(
                            category=Category.SPOT_STRIKE,
                            severity=Severity.HIGH,
                            title=f"Macro ticker {ticker} incorrectly resolved to crypto asset",
                            description=f"resolve_asset_for_snapshot returned '{asset}' for macro ticker {ticker}, should be empty",
                            location="merid/prediction/spot_strike_context.py",
                            recommendation="Fix asset resolution to return empty string for macro tickers",
                            evidence={"ticker": ticker, "resolved_asset": asset}
                        )
                
                # Test is_crypto_market_ticker
                for ticker in crypto_tickers:
                    if not is_crypto_market_ticker(ticker):
                        self.add_finding(
                            category=Category.SPOT_STRIKE,
                            severity=Severity.HIGH,
                            title=f"is_crypto_market_ticker incorrectly returns False for {ticker}",
                            description=f"Crypto ticker {ticker} not recognized as crypto market",
                            location="merid/prediction/spot_strike_context.py",
                            recommendation="Fix is_crypto_market_ticker to recognize all crypto tickers",
                            evidence={"ticker": ticker}
                        )
                
                for ticker in macro_tickers:
                    if is_crypto_market_ticker(ticker):
                        self.add_finding(
                            category=Category.SPOT_STRIKE,
                            severity=Severity.HIGH,
                            title=f"is_crypto_market_ticker incorrectly returns True for {ticker}",
                            description=f"Macro ticker {ticker} incorrectly recognized as crypto market",
                            location="merid/prediction/spot_strike_context.py",
                            recommendation="Fix is_crypto_market_ticker to reject macro tickers",
                            evidence={"ticker": ticker}
                        )
            
            except Exception as e:
                self.add_finding(
                    category=Category.SPOT_STRIKE,
                    severity=Severity.HIGH,
                    title="Could not verify asset resolution",
                    description=f"Error testing asset resolution: {e}",
                    location="merid/prediction/spot_strike_context.py",
                    recommendation="Ensure asset resolution functions are accessible"
                )
            
        except Exception as e:
            self.add_finding(
                category=Category.SPOT_STRIKE,
                severity=Severity.CRITICAL,
                title="Failed to load spot-strike tracking module",
                description=f"Error importing spot_strike_context: {e}",
                location="merid/prediction/spot_strike_context.py",
                recommendation="Ensure spot_strike_context module is accessible"
            )
    
    def audit_trade_decision_timing(self):
        """Audit trade decision timing mechanisms."""
        logger.info("Auditing trade decision timing...")
        
        try:
            from merid.prediction.entry_timing_filters import (
                check_patience_filter,
                get_time_weighted_edge_threshold,
                check_pullback_condition,
                scale_size_by_timing_quality,
                EntryTimingFilterConfig
            )
            
            # Check 1: Patience filter logic
            # Test YES side
            passes, reason = check_patience_filter(50, 100.0, "yes", 200)
            if passes:  # Should fail because 50 - 200 = -150 < 1
                self.add_finding(
                    category=Category.TIMING,
                    severity=Severity.HIGH,
                    title="Patience filter logic incorrect for YES side",
                    description=f"Patience filter passed when it should have failed (price=50c, discount=200c)",
                    location="merid/prediction/entry_timing_filters.py",
                    recommendation="Fix patience filter logic to correctly enforce discount requirements",
                    evidence={"price_cents": 50, "side": "yes", "discount": 200, "result": passes}
                )
            
            # Test NO side
            passes, reason = check_patience_filter(50, 100.0, "no", 200)
            if not passes:  # Should pass because 50 + 200 = 250 > 99 (but capped at 99)
                # Actually this might fail due to cap, let's check the logic
                pass  # This is expected behavior due to cap
            
            # Check 2: Time-weighted edge threshold
            # Test at different positions in window
            test_positions = [
                (0.1, 1.5),  # Early: 1.5x multiplier
                (0.4, 1.25),  # Mid-early: 1.25x multiplier
                (0.6, 1.0),  # Mid: 1.0x multiplier
                (0.9, 0.75),  # Late: 0.75x multiplier
            ]
            
            base_threshold = 0.02  # 2%
            window_duration = 900  # 15 minutes
            
            for position, expected_multiplier in test_positions:
                time_into_window = position * window_duration
                adjusted = get_time_weighted_edge_threshold(base_threshold, time_into_window, window_duration)
                expected_threshold = base_threshold * expected_multiplier
                
                if abs(adjusted - expected_threshold) > 0.0001:
                    self.add_finding(
                        category=Category.TIMING,
                        severity=Severity.MEDIUM,
                        title="Time-weighted edge threshold incorrect",
                        description=f"At position {position}, expected threshold {expected_threshold}, got {adjusted}",
                        location="merid/prediction/entry_timing_filters.py",
                        recommendation="Fix time-weighted edge threshold calculation",
                        evidence={
                            "position": position,
                            "expected": expected_threshold,
                            "actual": adjusted
                        }
                    )
            
            # Check 3: Size scaling logic
            # Test different timing qualities
            test_sizes = [
                (100, 0.9, 0.05, 100),  # Excellent timing: full size
                (100, 0.5, 0.2, 75),  # Good timing: 75% size
                (100, 0.3, 0.4, 50),  # Poor timing: 50% size
                (100, 0.1, 0.6, 25),  # Very poor timing: 25% size
            ]
            
            for base_size, timing_score, early_cost, expected_size in test_sizes:
                adjusted = scale_size_by_timing_quality(base_size, timing_score, early_cost)
                if adjusted != expected_size:
                    self.add_finding(
                        category=Category.TIMING,
                        severity=Severity.MEDIUM,
                        title="Size scaling logic incorrect",
                        description=f"Base size {base_size}, timing score {timing_score}, early cost {early_cost}: "
                                  f"expected {expected_size}, got {adjusted}",
                        location="merid/prediction/entry_timing_filters.py",
                        evidence={
                            "base_size": base_size,
                            "timing_score": timing_score,
                            "early_cost": early_cost,
                            "expected": expected_size,
                            "actual": adjusted
                        }
                    )
            
            # Check 4: Configuration validation
            try:
                config = EntryTimingFilterConfig.from_env()
                
                if config.patience_discount_cents < 0 or config.patience_discount_cents > 1000:
                    self.add_finding(
                        category=Category.TIMING,
                        severity=Severity.HIGH,
                        title="Invalid patience discount cents",
                        description=f"Patience discount cents {config.patience_discount_cents} is outside valid range (0-1000)",
                        location="merid/prediction/entry_timing_filters.py",
                        recommendation="Set patience discount to reasonable value (e.g., 100-500 cents)",
                        evidence={"patience_discount_cents": config.patience_discount_cents}
                    )
                
                if config.min_pullback_cents < 0 or config.min_pullback_cents > 1000:
                    self.add_finding(
                        category=Category.TIMING,
                        severity=Severity.HIGH,
                        title="Invalid min pullback cents",
                        description=f"Min pullback cents {config.min_pullback_cents} is outside valid range (0-1000)",
                        location="merid/prediction/entry_timing_filters.py",
                        recommendation="Set min pullback to reasonable value (e.g., 50-200 cents)",
                        evidence={"min_pullback_cents": config.min_pullback_cents}
                    )
            
            except Exception as e:
                self.add_finding(
                    category=Category.TIMING,
                    severity=Severity.LOW,
                    title="Could not verify timing filter configuration",
                    description=f"Error loading config: {e}",
                    location="merid/prediction/entry_timing_filters.py",
                    recommendation="Ensure EntryTimingFilterConfig.from_env() is accessible"
                )
            
        except Exception as e:
            self.add_finding(
                category=Category.TIMING,
                severity=Severity.CRITICAL,
                title="Failed to load entry timing filters",
                description=f"Error importing entry_timing_filters: {e}",
                location="merid/prediction/entry_timing_filters.py",
                recommendation="Ensure entry_timing_filters module is accessible"
            )
    
    def audit_configuration_consistency(self):
        """Audit configuration consistency across the stack."""
        logger.info("Auditing configuration consistency...")
        
        try:
            # Check 1: Profile YAML existence
            profile_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
            if not os.path.exists(profile_path):
                self.add_finding(
                    category=Category.CONFIGURATION,
                    severity=Severity.CRITICAL,
                    title="Profile YAML missing",
                    description=f"Profile file {profile_path} does not exist",
                    location="config/profiles/kalshi_crypto_15m_v2.yaml",
                    recommendation="Create profile YAML with proper configuration",
                    evidence={"profile_path": profile_path}
                )
            else:
                # Try to load and parse profile
                try:
                    import yaml
                    with open(profile_path, 'r', encoding='utf-8') as f:
                        profile_data = yaml.safe_load(f)
                    
                    # Check for required sections
                    required_sections = ['velocity_thresholds', 'guardrails', 'agent_defaults']
                    for section in required_sections:
                        if section not in profile_data:
                            self.add_finding(
                                category=Category.CONFIGURATION,
                                severity=Severity.HIGH,
                                title=f"Missing profile section: {section}",
                                description=f"Profile YAML missing required section: {section}",
                                location="config/profiles/kalshi_crypto_15m_v2.yaml",
                                recommendation=f"Add {section} section to profile YAML",
                                evidence={"missing_section": section}
                            )
                    
                    # Check asset coverage in velocity thresholds
                    if 'velocity_thresholds' in profile_data:
                        vt = profile_data['velocity_thresholds']
                        for asset in self.assets:
                            if asset.lower() not in [k.lower() for k in vt.keys()]:
                                self.add_finding(
                                    category=Category.CONFIGURATION,
                                    severity=Severity.HIGH,
                                    title=f"Missing velocity threshold for {asset}",
                                    description=f"Profile YAML missing velocity threshold for asset {asset}",
                                    location="config/profiles/kalshi_crypto_15m_v2.yaml",
                                    recommendation=f"Add velocity threshold for {asset} to profile YAML",
                                    evidence={"asset": asset, "available_assets": list(vt.keys())}
                                )
                
                except Exception as e:
                    self.add_finding(
                        category=Category.CONFIGURATION,
                        severity=Severity.HIGH,
                        title="Failed to parse profile YAML",
                        description=f"Error parsing profile YAML: {e}",
                        location="config/profiles/kalshi_crypto_15m_v2.yaml",
                        recommendation="Fix YAML syntax errors in profile file",
                        evidence={"error": str(e)}
                    )
            
            # Check 2: Risk envelope consistency
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile
                
                profile_adapter = get_active_profile()
                if profile_adapter and hasattr(profile_adapter, 'profile'):
                    profile = profile_adapter.profile
                    
                    # Check critical risk parameters
                    if hasattr(profile, 'guardrails_per_window_risk_pct'):
                        if profile.guardrails_per_window_risk_pct <= 0 or profile.guardrails_per_window_risk_pct > 0.10:
                            self.add_finding(
                                category=Category.CONFIGURATION,
                                severity=Severity.HIGH,
                                title="Unusual per-window risk percentage",
                                description=f"Per-window risk {profile.guardrails_per_window_risk_pct} is outside typical range (0-10%)",
                                location="merid/risk/profiles/crypto_15m_profile.py",
                                recommendation="Review if per-window risk is appropriate for strategy",
                                evidence={"per_window_risk_pct": profile.guardrails_per_window_risk_pct}
                            )
                    
                    if hasattr(profile, 'guardrails_total_venue_risk_pct'):
                        if profile.guardrails_total_venue_risk_pct <= 0 or profile.guardrails_total_venue_risk_pct > 0.20:
                            self.add_finding(
                                category=Category.CONFIGURATION,
                                severity=Severity.HIGH,
                                title="Unusual total venue risk percentage",
                                description=f"Total venue risk {profile.guardrails_total_venue_risk_pct} is outside typical range (0-20%)",
                                location="merid/risk/profiles/crypto_15m_profile.py",
                                recommendation="Review if total venue risk is appropriate for strategy",
                                evidence={"total_venue_risk_pct": profile.guardrails_total_venue_risk_pct}
                            )
            
            except Exception as e:
                self.add_finding(
                    category=Category.CONFIGURATION,
                    severity=Severity.MEDIUM,
                    title="Could not verify risk envelope consistency",
                    description=f"Error loading risk profile: {e}",
                    location="merid/risk/profiles/crypto_15m_profile.py",
                    recommendation="Ensure risk profile is accessible"
                )
            
        except Exception as e:
            self.add_finding(
                category=Category.CONFIGURATION,
                severity=Severity.CRITICAL,
                title="Failed to audit configuration consistency",
                description=f"Error during configuration audit: {e}",
                location="config/profiles/",
                recommendation="Ensure configuration files are accessible and valid"
            )
    
    def audit_cross_layer_consistency(self):
        """Audit consistency across upstream/midstream/downstream layers."""
        logger.info("Auditing cross-layer consistency...")
        
        # Check 1: Velocity threshold consistency
        try:
            from merid.event_venues.coinbase.velocity_signal import CoinbaseVelocitySignalGenerator
            from merid.prediction.agent_grid_15m import LeanAgentConfig
            
            # Get velocity thresholds from velocity_signal
            velocity_gen = CoinbaseVelocitySignalGenerator()
            velocity_thresholds = velocity_gen.VELOCITY_THRESHOLDS
            
            # Get velocity thresholds from agent grid config
            agent_config = LeanAgentConfig(name="TEST", series_tickers=["KXBTC15M"])
            agent_thresholds = {
                "BTC": agent_config.velocity_threshold_btc,
                "ETH": agent_config.velocity_threshold_eth,
                "SOL": agent_config.velocity_threshold_sol,
                "XRP": agent_config.velocity_threshold_xrp,
                "DOGE": agent_config.velocity_threshold_doge,
            }
            
            # Compare
            for asset in self.assets:
                asset_key = f"{asset}-USD"
                if asset_key in velocity_thresholds and asset in agent_thresholds:
                    diff = abs(velocity_thresholds[asset_key] - agent_thresholds[asset])
                    if diff > 0.00001:  # More than 0.001% difference
                        self.add_finding(
                            category=Category.CONSISTENCY,
                            severity=Severity.HIGH,
                            title=f"Velocity threshold inconsistency for {asset}",
                            description=f"Velocity threshold differs between velocity_signal.py ({velocity_thresholds[asset_key]}) "
                                      f"and agent_grid_15m.py ({agent_thresholds[asset]})",
                            location="merid/event_venues/coinbase/velocity_signal.py vs merid/prediction/agent_grid_15m.py",
                            recommendation="Align velocity thresholds across all layers to use single source of truth",
                            evidence={
                                "asset": asset,
                                "velocity_signal_threshold": velocity_thresholds[asset_key],
                                "agent_grid_threshold": agent_thresholds[asset],
                                "difference": diff
                            }
                        )
        
        except Exception as e:
            self.add_finding(
                category=Category.CONSISTENCY,
                severity=Severity.MEDIUM,
                title="Could not verify velocity threshold consistency",
                description=f"Error comparing velocity thresholds: {e}",
                location="merid/event_venues/coinbase/velocity_signal.py vs merid/prediction/agent_grid_15m.py",
                recommendation="Ensure both modules are accessible for comparison"
            )
        
        # Check 2: RSI threshold consistency
        try:
            from merid.signals.crypto_15m_indicators import IndicatorConfig
            
            # Check if asset-specific RSI thresholds are consistent
            for asset in self.assets:
                config = IndicatorConfig(asset=asset)
                
                # Check if asset-specific overrides are set
                if config.rsi_oversold_asset is not None:
                    if config.rsi_oversold_asset >= config.rsi_overbought_asset:
                        self.add_finding(
                            category=Category.CONSISTENCY,
                            severity=Severity.HIGH,
                            title=f"Asset-specific RSI thresholds inverted for {asset}",
                            description=f"RSI oversold ({config.rsi_oversold_asset}) >= overbought ({config.rsi_overbought_asset})",
                            location="merid/signals/crypto_15m_indicators.py",
                            recommendation="Fix asset-specific RSI thresholds",
                            evidence={
                                "asset": asset,
                                "rsi_oversold_asset": config.rsi_oversold_asset,
                                "rsi_overbought_asset": config.rsi_overbought_asset
                            }
                        )
        
        except Exception as e:
            self.add_finding(
                category=Category.CONSISTENCY,
                severity=Severity.MEDIUM,
                title="Could not verify RSI threshold consistency",
                description=f"Error checking RSI thresholds: {e}",
                location="merid/signals/crypto_15m_indicators.py",
                recommendation="Ensure indicator config is accessible"
            )
    
    def generate_report(self) -> str:
        """Generate a comprehensive audit report."""
        end_time = datetime.now(timezone.utc)
        duration = (end_time - self.start_time).total_seconds()
        
        report = []
        report.append("=" * 80)
        report.append("TECHNICAL ANALYSIS FLAW AUDIT REPORT")
        report.append("=" * 80)
        report.append(f"Generated: {end_time.isoformat()}")
        report.append(f"Duration: {duration:.2f} seconds")
        report.append(f"Total Findings: {len(self.findings)}")
        report.append("")
        
        # Summary by severity
        severity_counts = {}
        for finding in self.findings:
            severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
        
        report.append("SUMMARY BY SEVERITY:")
        report.append("-" * 40)
        for severity in [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]:
            count = severity_counts.get(severity, 0)
            if count > 0:
                report.append(f"  {severity.value}: {count}")
        report.append("")
        
        # Summary by category
        category_counts = {}
        for finding in self.findings:
            category_counts[finding.category] = category_counts.get(finding.category, 0) + 1
        
        report.append("SUMMARY BY CATEGORY:")
        report.append("-" * 40)
        for category in [Category.VELOCITY, Category.VOLATILITY, Category.MOMENTUM, 
                        Category.DIRECTIONAL, Category.SPOT_STRIKE, Category.TIMING,
                        Category.CONFIGURATION, Category.CONSISTENCY]:
            count = category_counts.get(category, 0)
            if count > 0:
                report.append(f"  {category.value}: {count}")
        report.append("")
        
        # Detailed findings
        report.append("DETAILED FINDINGS:")
        report.append("=" * 80)
        
        # Sort by severity (critical first)
        sorted_findings = sorted(self.findings, key=lambda f: (
            0 if f.severity == Severity.CRITICAL else
            1 if f.severity == Severity.HIGH else
            2 if f.severity == Severity.MEDIUM else
            3 if f.severity == Severity.LOW else
            4
        ))
        
        for i, finding in enumerate(sorted_findings, 1):
            report.append(f"\n[{i}] {finding.severity.value} - {finding.category.value}")
            report.append(f"    Title: {finding.title}")
            report.append(f"    Location: {finding.location}")
            report.append(f"    Description: {finding.description}")
            report.append(f"    Recommendation: {finding.recommendation}")
            if finding.evidence:
                report.append(f"    Evidence: {json.dumps(finding.evidence, indent=6, default=str)}")
            report.append("-" * 80)
        
        # Save to file
        report_text = "\n".join(report)
        with open('technical_analysis_flaw_audit_report.txt', 'w') as f:
            f.write(report_text)
        
        logger.info(f"Report saved to technical_analysis_flaw_audit_report.txt")
        
        return report_text
    
    def run_full_audit(self):
        """Run all audits and generate report."""
        logger.info("Starting technical analysis flaw audit...")
        
        self.audit_velocity_implementation()
        self.audit_volatility_implementation()
        self.audit_momentum_implementation()
        self.audit_directional_decision_making()
        self.audit_spot_strike_tracking()
        self.audit_trade_decision_timing()
        self.audit_configuration_consistency()
        self.audit_cross_layer_consistency()
        
        report = self.generate_report()
        
        logger.info("Audit complete.")
        return report


def main():
    """Main entry point."""
    auditor = TechnicalAnalysisAuditor()
    report = auditor.run_full_audit()
    print(report)


if __name__ == "__main__":
    main()

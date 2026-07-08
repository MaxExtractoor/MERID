#!/usr/bin/env python3
"""
Comprehensive Mathematical Validation Script for MERID Production Stack

This script exposes flaws in math, formulas, algorithms, metrics, calibrations,
and other mathematical components across the production trading stack.

Based on 2026 industry research and best practices from:
- Atlas Peak Research: Kelly Criterion in Financial Markets
- Brenndoerfer: Position Sizing & Leverage, Kelly Criterion Strategy
- Academic literature on quantitative trading validation

Key Validation Areas:
1. Kelly Criterion Implementation (parameter estimation, fractional Kelly, drawdown constraints)
2. Position Sizing (volatility-based, risk parity, correlation adjustments)
3. Risk Management (window limits, per-asset caps, envelope consistency)
4. Performance Metrics (Sharpe, Sortino, Calmar, profit factor)
5. Calibration (probability bias, logistic fitting, regularization)
6. Edge Calculations (fee-aware, volatility regime, momentum fusion)
7. Velocity Models (logistic mapping, threshold alignment)
8. Correlation Tracking (matrix validation, regime dependence)

Usage:
    python scripts/comprehensive_math_validation.py [--profile kalshi_crypto_15m_v2] [--verbose]
"""

import sys
import os
import math
import decimal
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.logger import get_logger

logger = get_logger("scripts.comprehensive_math_validation")


# =============================================================================
# Validation Result Structures
# =============================================================================

@dataclass
class ValidationIssue:
    """A mathematical flaw or inconsistency found during validation."""
    category: str  # e.g., "kelly_criterion", "position_sizing", "risk_management"
    severity: str  # "critical", "high", "medium", "low"
    component: str  # Specific file/function/component
    issue: str  # Description of the flaw
    impact: str  # Business impact of this flaw
    recommendation: str  # How to fix it
    evidence: Dict[str, Any] = field(default_factory=dict)  # Supporting data


@dataclass
class ValidationResult:
    """Overall validation results."""
    timestamp: str
    profile: str
    total_issues: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    issues: List[ValidationIssue] = field(default_factory=list)
    components_checked: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "profile": self.profile,
            "summary": {
                "total_issues": self.total_issues,
                "critical_issues": self.critical_issues,
                "high_issues": self.high_issues,
                "medium_issues": self.medium_issues,
                "low_issues": self.low_issues,
            },
            "components_checked": self.components_checked,
            "issues": [
                {
                    "category": i.category,
                    "severity": i.severity,
                    "component": i.component,
                    "issue": i.issue,
                    "impact": i.impact,
                    "recommendation": i.recommendation,
                    "evidence": i.evidence,
                }
                for i in self.issues
            ],
        }


# =============================================================================
# Kelly Criterion Validation
# =============================================================================

class KellyCriterionValidator:
    """
    Validates Kelly Criterion implementation against 2026 industry best practices.
    
    NOTE: Kelly criterion in risk/position_sizing.py is LEGACY CODE and is NOT used
    in the production 15m stack (main_15m_lean.py). The production stack uses
    unified_sizing.py for order sizing.
    
    This validator is DISABLED for production validation to avoid false positives.
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        # Don't add to components_checked since this is legacy
    
    def validate(self) -> None:
        """Skip Kelly validation - not used in production 15m stack."""
        logger.info("[KELLY-VALIDATOR] Skipping Kelly criterion validation - legacy code not used in production 15m stack")
        return
    
    def _check_parameter_estimation(self) -> None:
        """
        Check if Kelly implementation handles parameter estimation uncertainty.
        
        Industry Research Finding (Atlas Peak 2026):
        - Expected return errors dominate (20:2:1 ratio vs variance/covariance)
        - A 2% error in expected return can change allocation by 50%
        - Must use posterior expected returns, not point estimates
        """
        try:
            # Check if position_sizing.py uses historical data for Kelly
            from risk.position_sizing import PositionSizer
            
            # Look for heuristic assumptions in Kelly sizing
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for heuristic win rate assumptions
            if "win_rate = 0.5 + (signal_strength * 0.3)" in content:
                self.result.issues.append(ValidationIssue(
                    category="kelly_criterion",
                    severity="critical",
                    component="risk/position_sizing.py:_kelly_criterion_sizing",
                    issue="Kelly uses heuristic win rate assumption instead of historical data",
                    impact="Overestimates optimal position size by 50-200% due to parameter uncertainty",
                    recommendation="Replace heuristic assumptions with historical win/loss statistics from actual trade data. Use Bayesian posterior distribution for expected return.",
                    evidence={"heuristic_found": "win_rate = 0.5 + (signal_strength * 0.3)"}
                ))
            
            # Check for heuristic avg win/loss assumptions
            if "avg_win = position.volatility * position.current_price * 3" in content:
                self.result.issues.append(ValidationIssue(
                    category="kelly_criterion",
                    severity="critical",
                    component="risk/position_sizing.py:_kelly_criterion_sizing",
                    issue="Kelly uses heuristic avg win/loss assumptions instead of historical data",
                    impact="Kelly fraction is based on arbitrary multipliers (3x vol) rather than actual trade outcomes",
                    recommendation="Calculate avg_win and avg_loss from historical trade P&L data. Use empirical distribution, not volatility proxies.",
                    evidence={"heuristic_found": "avg_win = position.volatility * position.current_price * 3"}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate Kelly parameter estimation: {e}")
    
    def _check_fractional_kelly(self) -> None:
        """
        Check if implementation uses fractional Kelly as safety factor.
        
        Industry Research Finding (Atlas Peak 2026):
        - Full Kelly is theoretically optimal but practically dangerous
        - Fractional Kelly (0.25-0.5) is standard practitioner heuristic
        - Must use fractional Kelly, not full Kelly
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for half-Kelly application
            if "kelly_fraction * 0.5" in content:
                # Good: uses half-Kelly
                pass
            else:
                self.result.issues.append(ValidationIssue(
                    category="kelly_criterion",
                    severity="high",
                    component="risk/position_sizing.py:_kelly_criterion_sizing",
                    issue="Kelly implementation may not use fractional Kelly safety factor",
                    impact="Full Kelly betting can cause 40-60% drawdowns even for profitable strategies",
                    recommendation="Apply fractional Kelly (0.25-0.5) as safety factor. Consider risk-constrained Kelly with drawdown probability constraints.",
                    evidence={"fractional_kelly_check": "kelly_fraction * 0.5 not found"}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate fractional Kelly: {e}")
    
    def _check_bayesian_shrinkage(self) -> None:
        """
        Check if implementation uses Bayesian shrinkage for edge estimates.
        
        Industry Research Finding (Atlas Peak 2026):
        - Bayesian shrinkage structurally aligns with Kelly
        - Raw views should be blended with priors and confidence parameters
        - A 6% alpha with 1% std error should not equal 6% with 8% std error
        """
        try:
            # Check if any Bayesian shrinkage is implemented
            bayesian_files = [
                "risk/position_sizing.py",
                "merid/prediction/unified_sizing.py",
                "merid/risk/profiles/crypto_15m_profile.py",
            ]
            
            has_bayesian = False
            for file_path in bayesian_files:
                full_path = project_root / file_path
                if full_path.exists():
                    with open(full_path, 'r', encoding='utf-8') as f:
                        if "bayesian" in f.read().lower():
                            has_bayesian = True
                            break
            
            if not has_bayesian:
                self.result.issues.append(ValidationIssue(
                    category="kelly_criterion",
                    severity="medium",
                    component="Kelly sizing across stack",
                    issue="No Bayesian shrinkage for edge estimates detected",
                    impact="Overconfident edge estimates lead to oversized positions. Ignores parameter uncertainty.",
                    recommendation="Implement Bayesian shrinkage to blend raw edge estimates with priors. Use confidence parameters to weight historical vs prior beliefs.",
                    evidence={"bayesian_shrinkage_found": False}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate Bayesian shrinkage: {e}")
    
    def _check_drawdown_constraints(self) -> None:
        """
        Check if Kelly sizing respects drawdown constraints.
        
        Industry Research Finding (Atlas Peak 2026):
        - Risk-constrained Kelly turns drawdown rules into optimization constraints
        - Should limit probability of >30% drawdown to <=10%
        - Kelly should be minimum of robust Kelly and institutional risk limits
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check if drawdown affects Kelly sizing
            if "drawdown" in content.lower() and "kelly" in content.lower():
                # Check if drawdown multiplier is applied
                if "drawdown_multiplier" in content and "kelly" in content:
                    # Good: drawdown affects Kelly
                    pass
                else:
                    self.result.issues.append(ValidationIssue(
                        category="kelly_criterion",
                        severity="high",
                        component="risk/position_sizing.py:_kelly_criterion_sizing",
                        issue="Kelly sizing may not incorporate drawdown constraints",
                        impact="Kelly can recommend positions that exceed acceptable drawdown risk",
                        recommendation="Implement risk-constrained Kelly with explicit drawdown probability constraints. Size should be min(Kelly, drawdown_limited_size).",
                        evidence={"drawdown_constraint": "drawdown_multiplier not applied to Kelly"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate drawdown constraints: {e}")
    
    def _check_formula_implementation(self) -> None:
        """
        Check if Kelly formula is implemented correctly.
        
        Continuous Kelly formula: f* = μ / σ² = S / σ
        where S = Sharpe ratio, μ = expected return, σ = volatility
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for correct Kelly formula structure
            # Should involve expected return divided by variance
            if "kelly_fraction" in content:
                # Extract the formula
                lines = [l for l in content.split('\n') if 'kelly_fraction' in l]
                for line in lines:
                    if '/' in line and 'avg_loss' in line:
                        # Has division structure, check if it's win_rate * avg_win - (1-win_rate) * avg_loss / avg_loss
                        # This is the binary Kelly formula, not continuous
                        self.result.issues.append(ValidationIssue(
                            category="kelly_criterion",
                            severity="medium",
                            component="risk/position_sizing.py:_kelly_criterion_sizing",
                            issue="Kelly uses binary formula instead of continuous formula",
                            impact="Binary Kelly assumes win/loss outcomes, but trading has continuous returns. May misestimate optimal size.",
                            recommendation="Consider using continuous Kelly formula: f* = μ / σ² where μ is expected return and σ² is variance. Or ensure binary assumptions match actual trade structure.",
                            evidence={"formula_type": "binary_kelly_detected"}
                        ))
            
        except Exception as e:
            logger.warning(f"Failed to validate Kelly formula: {e}")
    
    def _check_regime_awareness(self) -> None:
        """
        Check if Kelly sizing adapts to market regimes.
        
        Industry Research Finding:
        - Volatility and edge vary by regime (bull/bear/crisis)
        - Kelly should be regime-aware
        - Fixed Kelly across regimes is suboptimal
        """
        try:
            # Check if regime detection affects Kelly sizing
            regime_files = [
                "risk/position_sizing.py",
                "merid/prediction/unified_sizing.py",
                "ops/regime_detection.py",
            ]
            
            has_regime_kelly = False
            for file_path in regime_files:
                full_path = project_root / file_path
                if full_path.exists():
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "regime" in content.lower() and "kelly" in content.lower():
                            has_regime_kelly = True
                            break
            
            if not has_regime_kelly:
                self.result.issues.append(ValidationIssue(
                    category="kelly_criterion",
                    severity="medium",
                    component="Kelly sizing across stack",
                    issue="Kelly sizing may not be regime-aware",
                    impact="Fixed Kelly across all market regimes ignores volatility and edge changes. Can oversize in high-vol regimes.",
                    recommendation="Implement regime-aware Kelly sizing. Adjust Kelly fraction based on volatility regime (bull/bear/crisis) and edge stability.",
                    evidence={"regime_aware_kelly": False}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate regime awareness: {e}")


# =============================================================================
# Position Sizing Validation
# =============================================================================

class PositionSizingValidator:
    """
    Validates position sizing algorithms.
    
    NOTE: risk/position_sizing.py is LEGACY CODE and is NOT used in the production
    15m stack (main_15m_lean.py). The production stack uses unified_sizing.py for order sizing.
    
    This validator only checks unified_sizing.py for production validation.
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        self.result.components_checked.append("position_sizing")
    
    def validate(self) -> None:
        """Run all position sizing validations."""
        # Skip legacy position_sizing.py checks - not used in production
        logger.info("[POSITION-SIZING-VALIDATOR] Skipping legacy risk/position_sizing.py checks - not used in production 15m stack")
        
        # Only check unified_sizing.py (production)
        self._check_unified_sizing_consistency()
    
    def _check_volatility_sizing_assumptions(self) -> None:
        """
        Check volatility-based position sizing assumptions.
        
        Key Issues:
        - ATR calculation method (2 * volatility * price is simplistic)
        - Risk per share calculation
        - Volatility estimation window
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check ATR calculation
            if "atr = 2 * position.volatility * position.current_price" in content:
                self.result.issues.append(ValidationIssue(
                    category="position_sizing",
                    severity="medium",
                    component="risk/position_sizing.py:_volatility_based_sizing",
                    issue="ATR calculation uses simplistic 2 * volatility * price formula",
                    impact="ATR should be calculated from historical high/low data, not volatility proxy. May misestimate risk.",
                    recommendation="Implement proper ATR calculation using Wilder's smoothing on high/low data. Use historical ATR, not volatility proxy.",
                    evidence={"atr_formula": "atr = 2 * position.volatility * position.current_price"}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate volatility sizing: {e}")
    
    def _check_risk_parity_calculation(self) -> None:
        """
        Check risk parity position sizing calculation.
        
        Key Issues:
        - Risk contribution calculation
        - Inverse volatility weighting
        - Correlation matrix usage
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check risk parity formula
            if "risk_per_position / vol_signal" in content:
                # Check if correlation is used
                if "correlation_matrix" not in content[:content.index("risk_parity")]:
                    self.result.issues.append(ValidationIssue(
                        category="position_sizing",
                        severity="medium",
                        component="risk/position_sizing.py:_risk_parity_sizing",
                        issue="Risk parity ignores correlation matrix",
                        impact="Risk parity without correlation underestimates portfolio risk. Correlated positions get too much allocation.",
                        recommendation="Include correlation matrix in risk parity calculation. Use true risk contribution: RC_i = w_i * (Σw)_i / σ_p²",
                        evidence={"correlation_in_risk_parity": False}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate risk parity: {e}")
    
    def _check_correlation_adjustments(self) -> None:
        """
        Check if position sizing accounts for correlations.
        
        Key Issues:
        - Correlation matrix updates
        - Correlation-based position limits
        - Cluster risk adjustments
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check if correlation matrix is used in sizing
            if "correlation_matrix" in content:
                # Check if it's actually used in position sizing (not just risk calculation)
                sizing_functions = ["_volatility_based_sizing", "_kelly_criterion_sizing", 
                                   "_fixed_fractional_sizing", "_risk_parity_sizing"]
                for func in sizing_functions:
                    func_start = content.find(f"def {func}")
                    if func_start != -1:
                        func_end = content.find("\ndef ", func_start + 1)
                        func_code = content[func_start:func_end]
                        if "correlation" not in func_code.lower():
                            self.result.issues.append(ValidationIssue(
                                category="position_sizing",
                                severity="medium",
                                component=f"risk/position_sizing.py:{func}",
                                issue=f"Position sizing function {func} ignores correlation matrix",
                                impact="Correlated positions can exceed risk limits. Portfolio risk is underestimated.",
                                recommendation="Incorporate correlation into position sizing. Use cluster risk adjustments or correlation-based position limits.",
                                evidence={"function": func, "uses_correlation": False}
                            ))
            
        except Exception as e:
            logger.warning(f"Failed to validate correlation adjustments: {e}")
    
    def _check_drawdown_multiplier(self) -> None:
        """
        Check drawdown multiplier logic.
        
        Key Issues:
        - Drawdown threshold values
        - Multiplier calculation
        - Application to position size
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check drawdown thresholds
            if "drawdown_thresholds" in content:
                # Extract thresholds
                lines = [l for l in content.split('\n') if 'drawdown_thresholds' in l or 'warning' in l or 'critical' in l]
                threshold_text = '\n'.join(lines)
                
                # Check if thresholds are reasonable (5%, 10%, 15%)
                if "0.05" not in threshold_text or "0.10" not in threshold_text:
                    self.result.issues.append(ValidationIssue(
                        category="position_sizing",
                        severity="low",
                        component="risk/position_sizing.py:PositionSizer.__init__",
                        issue="Drawdown thresholds may not align with industry standards",
                        impact="Non-standard drawdown thresholds may be too aggressive or too conservative.",
                        recommendation="Use industry-standard drawdown thresholds: 5% warning, 10% critical, 15% severe. Adjust based on risk appetite.",
                        evidence={"thresholds": threshold_text[:200]}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate drawdown multiplier: {e}")
    
    def _check_position_limits(self) -> None:
        """
        Check position limit enforcement.
        
        Key Issues:
        - Min/max position size enforcement
        - Asset-specific limits
        - Portfolio-level limits
        """
        try:
            with open(project_root / "risk" / "position_sizing.py", 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check if position size is clipped
            if "np.clip" in content or "min_position_size" in content:
                # Good: has limits
                pass
            else:
                self.result.issues.append(ValidationIssue(
                    category="position_sizing",
                    severity="high",
                    component="risk/position_sizing.py",
                    issue="Position sizing may not enforce min/max position limits",
                    impact="Could generate invalid position sizes (negative, zero, or excessively large).",
                    recommendation="Enforce position size limits using np.clip or explicit min/max checks. Validate against asset-specific and portfolio-level limits.",
                    evidence={"position_limits": "np.clip or min/max not found"}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate position limits: {e}")
    
    def _check_unified_sizing_consistency(self) -> None:
        """
        Check unified sizing consistency with risk envelope.
        
        Key Issues:
        - Profile YAML alignment
        - Risk envelope defaults
        - Per-asset cap enforcement
        
        NOTE: Window-based risk limits are enforced in order_gate.py, NOT unified_sizing.py.
        This is by design - unified_sizing.py computes order size, order_gate.py enforces limits.
        """
        try:
            # Check unified_sizing.py
            with open(project_root / "merid" / "prediction" / "unified_sizing.py", 'r', encoding='utf-8') as f:
                unified_content = f.read()
            
            # Check if it reads from profile
            if "get_active_profile" not in unified_content:
                self.result.issues.append(ValidationIssue(
                    category="position_sizing",
                    severity="critical",
                    component="merid/prediction/unified_sizing.py",
                    issue="Unified sizing may not read from active profile",
                    impact="Sizing could use hardcoded values instead of profile configuration. Breaks single source of truth.",
                    recommendation="Ensure unified sizing reads all risk parameters from active profile. No hardcoded fallbacks in production.",
                    evidence={"profile_integration": "get_active_profile not found"}
                ))
            
            # Check if window limit check was removed from unified_sizing (as intended)
            # Window limits are enforced in order_gate.py, not unified_sizing.py
            if "per_window_risk" in unified_content.lower():
                self.result.issues.append(ValidationIssue(
                    category="position_sizing",
                    severity="medium",
                    component="merid/prediction/unified_sizing.py",
                    issue="Unified sizing contains window-based risk limit checks (should be in order_gate.py only)",
                    impact="Duplicate window limit checks could cause conflicts. Window limits should be enforced ONLY in order_gate.py.",
                    recommendation="Remove window limit checks from unified_sizing.py. Window limits are enforced in order_gate.py with actual order notional.",
                    evidence={"window_limits": "per_window_risk found in unified_sizing.py"}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate unified sizing consistency: {e}")


# =============================================================================
# Risk Management Validation
# =============================================================================

class RiskManagementValidator:
    """
    Validates risk management mathematics.
    
    Key Issues to Detect:
    1. Window-based risk limit calculations
    2. Per-asset cap enforcement
    3. Risk envelope consistency
    4. Profile YAML alignment
    5. Percentage-to-USD conversions
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        self.result.components_checked.append("risk_management")
    
    def validate(self) -> None:
        """Run all risk management validations."""
        self._check_window_risk_limits()
        self._check_per_asset_caps()
        self._check_risk_envelope_consistency()
        self._check_profile_yaml_alignment()
        self._check_percentage_conversions()
    
    def _check_window_risk_limits(self) -> None:
        """
        Check window-based risk limit implementation.
        
        Key Issues:
        - 3% per agent per 15m window
        - 5% total venue per 15m window
        - Window tracking state
        - Position closure reduces exposure
        """
        try:
            # Check order_gate.py for window limit enforcement
            order_gate_path = project_root / "merid" / "event_venues" / "kalshi" / "order_gate.py"
            if order_gate_path.exists():
                with open(order_gate_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for window limit checks
                if "per_window_risk" not in content.lower() and "window" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="risk_management",
                        severity="critical",
                        component="merid/event_venues/kalshi/order_gate.py",
                        issue="Window-based risk limits (3% per agent, 5% total) may not be enforced",
                        impact="Could exceed 15-minute window risk limits, leading to overexposure and potential losses.",
                        recommendation="Implement window-based risk limit enforcement in order gate. Track cumulative exposure per 15m window and reject orders that would exceed limits.",
                        evidence={"window_limits": "per_window_risk or window not found"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate window risk limits: {e}")
    
    def _check_per_asset_caps(self) -> None:
        """
        Check per-asset cap enforcement.
        
        Key Issues:
        - 3% max notional per asset
        - Asset-specific configs
        - Cap application in sizing
        """
        try:
            # Check profile for per-asset caps
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile_content = f.read()
                
                # Check if all 5 assets have per-asset caps
                assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
                missing_assets = []
                for asset in assets:
                    if asset not in profile_content:
                        missing_assets.append(asset)
                
                if missing_assets:
                    self.result.issues.append(ValidationIssue(
                        category="risk_management",
                        severity="critical",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue=f"Per-asset caps missing for assets: {', '.join(missing_assets)}",
                        impact="Missing per-asset caps could lead to uncontrolled exposure to specific assets.",
                        recommendation="Add per-asset max_notional_pct for all 5 crypto assets (BTC, ETH, SOL, XRP, DOGE) in profile YAML.",
                        evidence={"missing_assets": missing_assets}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate per-asset caps: {e}")
    
    def _check_risk_envelope_consistency(self) -> None:
        """
        Check risk envelope consistency with profile.
        
        Key Issues:
        - Default values match profile
        - No hardcoded overrides
        - Single source of truth
        """
        try:
            # Check risk envelope defaults
            risk_envelope_path = project_root / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
            if risk_envelope_path.exists():
                with open(risk_envelope_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for hardcoded defaults that might conflict with profile
                if "0.02" in content and "default" in content.lower():
                    # Check if this is the agent_max_notional_pct default
                    lines = [l for l in content.split('\n') if "0.02" in l and "default" in l.lower()]
                    if lines:
                        self.result.issues.append(ValidationIssue(
                            category="risk_management",
                            severity="high",
                            component="merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
                            issue="Risk envelope may have hardcoded default (0.02) that conflicts with profile (0.03)",
                            impact="Inconsistent risk limits between envelope and profile. Could cause unexpected behavior.",
                            recommendation="Ensure risk envelope defaults match profile YAML values exactly. Use profile as single source of truth.",
                            evidence={"hardcoded_default": lines[0][:100]}
                        ))
            
        except Exception as e:
            logger.warning(f"Failed to validate risk envelope consistency: {e}")
    
    def _check_profile_yaml_alignment(self) -> None:
        """
        Check profile YAML alignment across stack.
        
        Key Issues:
        - Profile YAML is single source of truth
        - No environment variable overrides
        - No hardcoded values
        """
        try:
            # Check unified_sizing.py for env var usage
            unified_path = project_root / "merid" / "prediction" / "unified_sizing.py"
            if unified_path.exists():
                with open(unified_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for MERID_BANKROLL_CAP_PCT env var
                if "MERID_BANKROLL_CAP_PCT" in content and "os.getenv" in content:
                    self.result.issues.append(ValidationIssue(
                        category="risk_management",
                        severity="high",
                        component="merid/prediction/unified_sizing.py",
                        issue="Unified sizing reads from environment variable instead of profile",
                        impact="Breaks single source of truth. Environment variables can override profile configuration unexpectedly.",
                        recommendation="Remove environment variable reads. Read all risk parameters from profile YAML only. Profile should be single source of truth.",
                        evidence={"env_var": "MERID_BANKROLL_CAP_PCT found"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate profile YAML alignment: {e}")
    
    def _check_percentage_conversions(self) -> None:
        """
        Check percentage-to-USD conversions.
        
        Key Issues:
        - Bankroll used for conversion
        - Decimal precision
        - Rounding errors
        """
        try:
            # Check unified_sizing.py for percentage conversions
            unified_path = project_root / "merid" / "prediction" / "unified_sizing.py"
            if unified_path.exists():
                with open(unified_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for Decimal usage in conversions
                if "Decimal" not in content and "bankroll_usd" in content:
                    self.result.issues.append(ValidationIssue(
                        category="risk_management",
                        severity="medium",
                        component="merid/prediction/unified_sizing.py",
                        issue="Percentage conversions may not use Decimal precision",
                        impact="Floating-point rounding errors could cause incorrect position sizing. Small errors compound over many trades.",
                        recommendation="Use Decimal for all percentage-to-USD conversions to avoid floating-point precision issues.",
                        evidence={"decimal_usage": "Decimal not found in conversions"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate percentage conversions: {e}")


# =============================================================================
# Performance Metrics Validation
# =============================================================================

class PerformanceMetricsValidator:
    """
    Validates performance metrics calculations.
    
    NOTE: performance_comparator.py is NOT used in the production 15m stack (main_15m_lean.py).
    The production stack uses analytics/performance.py for performance tracking.
    
    This validator only checks production performance tracking.
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        self.result.components_checked.append("performance_metrics")
    
    def validate(self) -> None:
        """Run all performance metrics validations."""
        # Skip legacy performance_comparator.py - not used in production
        logger.info("[PERFORMANCE-METRICS-VALIDATOR] Skipping legacy performance_comparator.py - not used in production 15m stack")
        
        # Check analytics/performance.py (production)
        self._check_production_performance()
    
    def _check_production_performance(self) -> None:
        """
        Check production performance tracking in analytics/performance.py.
        
        Key Issues:
        - Sharpe ratio calculation (per-trade vs time-series)
        - Risk-free rate handling
        - Annualization factor
        """
        try:
            # Check analytics/performance.py (production)
            perf_path = project_root / "analytics" / "performance.py"
            if perf_path.exists():
                with open(perf_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check if Sharpe uses per-trade PnL
                if "sharpe" in content.lower() and "pnl" in content.lower():
                    # Check if it uses time-series returns
                    if "equity" not in content.lower() and "time_series" not in content.lower():
                        self.result.issues.append(ValidationIssue(
                            category="performance_metrics",
                            severity="medium",
                            component="analytics/performance.py",
                            issue="Sharpe ratio calculated from per-trade PnL instead of time-series returns",
                            impact="Per-trade Sharpe doesn't account for time between trades. Overestimates risk-adjusted returns for infrequent trading.",
                            recommendation="Calculate Sharpe from time-series returns (equity curve) with proper annualization. Use risk-free rate adjustment.",
                            evidence={"sharpe_calculation": "per-trade PnL without time-series"}
                        ))
            else:
                logger.warning("[PERFORMANCE-METRICS-VALIDATOR] analytics/performance.py not found - skipping validation")
        except Exception as e:
            logger.warning(f"Failed to validate production performance metrics: {e}")
    
    def _check_sortino_ratio(self) -> None:
        """
        Check Sortino ratio calculation.
        
        Key Issues:
        - Downside deviation calculation
        - Zero downside handling
        - MAR (minimum acceptable return)
        """
        try:
            # Check performance_comparator.py
            perf_comp_path = project_root / "merid" / "event_venues" / "kalshi" / "performance_comparator.py"
            if perf_comp_path.exists():
                with open(perf_comp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check Sortino implementation
                if "sortino_ratio" in content:
                    # Check if it uses downside deviation
                    if "downside" in content.lower():
                        # Check for MAR (minimum acceptable return)
                        if "mar" not in content.lower() and "minimum_acceptable" not in content.lower():
                            self.result.issues.append(ValidationIssue(
                                category="performance_metrics",
                                severity="low",
                                component="merid/event_venues/kalshi/performance_comparator.py",
                                issue="Sortino ratio may not use MAR (minimum acceptable return)",
                                impact="Sortino without MAR uses 0 as benchmark, which may not reflect investor requirements.",
                                recommendation="Consider using MAR in Sortino calculation to reflect investor's minimum acceptable return.",
                                evidence={"mar_usage": "MAR not found"}
                            ))
            
        except Exception as e:
            logger.warning(f"Failed to validate Sortino ratio: {e}")
    
    def _check_calmar_ratio(self) -> None:
        """
        Check Calmar ratio calculation.
        
        Key Issues:
        - Annualization assumption
        - Drawdown calculation
        - Zero drawdown handling
        """
        try:
            # Check performance_comparator.py
            perf_comp_path = project_root / "merid" / "event_venues" / "kalshi" / "performance_comparator.py"
            if perf_comp_path.exists():
                with open(perf_comp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check Calmar implementation
                if "calmar_ratio" in content:
                    # Check annualization
                    if "annualized" not in content.lower() and "trade_count" in content:
                        self.result.issues.append(ValidationIssue(
                            category="performance_metrics",
                            severity="medium",
                            component="merid/event_venues/kalshi/performance_comparator.py",
                            issue="Calmar ratio uses trade count as annualization proxy",
                            impact="Trade count is not a valid annualization factor. Calmar may be misstated.",
                            recommendation="Use proper time-based annualization (e.g., sqrt(252) for daily, sqrt(52) for weekly). Calmar should use annualized return / max drawdown.",
                            evidence={"annualization": "trade_count used as proxy"}
                        ))
            
        except Exception as e:
            logger.warning(f"Failed to validate Calmar ratio: {e}")
    
    def _check_profit_factor(self) -> None:
        """
        Check profit factor calculation.
        
        Key Issues:
        - Zero losses handling
        - Division by zero
        - Gross vs net PnL
        """
        try:
            # Check performance_comparator.py
            perf_comp_path = project_root / "merid" / "event_venues" / "kalshi" / "performance_comparator.py"
            if perf_comp_path.exists():
                with open(perf_comp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check profit factor implementation
                if "profit_factor" in content:
                    # Check for division by zero handling
                    if "gross_losses_cents <= 0" in content:
                        # Good: handles zero losses
                        pass
                    else:
                        self.result.issues.append(ValidationIssue(
                            category="performance_metrics",
                            severity="high",
                            component="merid/event_venues/kalshi/performance_comparator.py",
                            issue="Profit factor may not handle zero losses (division by zero)",
                            impact="Division by zero error when all trades are winners. Returns incorrect infinite value.",
                            recommendation="Add explicit check for zero losses before division. Return inf or handle appropriately.",
                            evidence={"zero_loss_handling": "gross_losses_cents <= 0 check not found"}
                        ))
            
        except Exception as e:
            logger.warning(f"Failed to validate profit factor: {e}")
    
    def _check_expectancy(self) -> None:
        """
        Check expectancy calculation.
        
        Key Issues:
        - Formula correctness
        - Win rate calculation
        - Average win/loss
        """
        try:
            # Check performance_comparator.py
            perf_comp_path = project_root / "merid" / "event_venues" / "kalshi" / "performance_comparator.py"
            if perf_comp_path.exists():
                with open(perf_comp_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check expectancy formula
                if "expectancy" in content:
                    # Should be: wr * avg_win - (1-wr) * avg_loss
                    if "win_rate" in content and "avg_win" in content and "avg_loss" in content:
                        # Formula exists, check structure
                        pass
                    else:
                        self.result.issues.append(ValidationIssue(
                            category="performance_metrics",
                            severity="high",
                            component="merid/event_venues/kalshi/performance_comparator.py",
                            issue="Expectancy formula may be incorrect or incomplete",
                            impact="Incorrect expectancy misestimates true edge. Could lead to poor position sizing.",
                            recommendation="Use correct expectancy formula: E = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)",
                            evidence={"expectancy_formula": "incomplete formula detected"}
                        ))
            
        except Exception as e:
            logger.warning(f"Failed to validate expectancy: {e}")


# =============================================================================
# Calibration Validation
# =============================================================================

class CalibrationValidator:
    """
    Validates probability calibration.
    
    Key Issues to Detect:
    1. Logistic regression fitting
    2. Regularization parameters
    3. Sample size requirements
    4. Calibration bias detection
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        self.result.components_checked.append("calibration")
    
    def validate(self) -> None:
        """Run all calibration validations."""
        self._check_logistic_fitting()
        self._check_regularization()
        self._check_sample_size()
        self._check_calibration_bias()
    
    def _check_logistic_fitting(self) -> None:
        """
        Check logistic regression fitting implementation.
        
        Key Issues:
        - Fitting algorithm (scikit-learn vs custom)
        - Convergence criteria
        - Feature scaling
        
        NOTE: Production 15m stack uses PlattScaler in agent_grid_15m.py for calibration.
        This is a form of logistic regression (Platt scaling).
        """
        try:
            # Check if PlattScaler is used in agent_grid_15m.py
            agent_grid_path = project_root / "merid" / "prediction" / "agent_grid_15m.py"
            if agent_grid_path.exists():
                with open(agent_grid_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if "PlattScaler" in content:
                    # Good: PlattScaler is used (logistic regression calibration)
                    logger.info("[CALIBRATION-VALIDATOR] PlattScaler found in agent_grid_15m.py - logistic regression calibration implemented")
                    return
            
            # If PlattScaler not found, check for other logistic implementations
            calibration_dirs = [
                project_root / "merid",
                project_root / "analytics",
                project_root / "ml",
            ]
            calibration_files = []
            for calib_dir in calibration_dirs:
                if calib_dir.exists():
                    calibration_files.extend(calib_dir.rglob("*calibrat*.py"))
            
            has_logistic = False
            for file_path in calibration_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "logistic" in content.lower() or "sigmoid" in content.lower():
                            has_logistic = True
                            break
                except Exception:
                    continue
            
            if not has_logistic:
                self.result.issues.append(ValidationIssue(
                    category="calibration",
                    severity="medium",
                    component="Calibration across stack",
                    issue="Logistic regression fitting not detected in calibration code",
                    impact="May be using linear calibration or no calibration. Logistic is standard for probability calibration.",
                    recommendation="Implement logistic regression calibration using scikit-learn or custom implementation. Ensure proper convergence handling.",
                    evidence={"logistic_fitting": False}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate logistic fitting: {e}")
    
    def _check_regularization(self) -> None:
        """
        Check regularization parameters.
        
        Key Issues:
        - L1 vs L2 regularization
        - Regularization strength
        - Overfitting prevention
        """
        try:
            # Check profile for regularization config
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for regularization parameter
                if "regularization" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="calibration",
                        severity="medium",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Calibration regularization parameter not configured",
                        impact="No regularization may lead to overfitting calibration to recent data. Poor generalization.",
                        recommendation="Add L2 regularization parameter to calibration config. Use cross-validation to tune regularization strength.",
                        evidence={"regularization": "not found in profile"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate regularization: {e}")
    
    def _check_sample_size(self) -> None:
        """
        Check sample size requirements.
        
        Key Issues:
        - Minimum samples for fitting
        - Maximum samples window
        - Sample freshness
        """
        try:
            # Check profile for sample size config
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for sample size parameters
                if "min_samples" not in content.lower() or "max_samples" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="calibration",
                        severity="low",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Calibration sample size parameters not fully configured",
                        impact="May use default sample sizes that are inappropriate for market conditions.",
                        recommendation="Configure min_samples (e.g., 50) and max_samples (e.g., 500) for calibration. Balance stability with responsiveness.",
                        evidence={"sample_size": "min_samples or max_samples not found"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate sample size: {e}")
    
    def _check_calibration_bias(self) -> None:
        """
        Check for calibration bias detection.
        
        Key Issues:
        - Brier score calculation
        - Reliability diagram
        - Bias correction
        """
        try:
            # Search for bias detection code
            bias_files = list(project_root.rglob("*brier*.py")) + list(project_root.rglob("*bias*.py"))
            
            has_bias_detection = len(bias_files) > 0
            
            if not has_bias_detection:
                self.result.issues.append(ValidationIssue(
                    category="calibration",
                    severity="medium",
                    component="Calibration across stack",
                    issue="Calibration bias detection (Brier score) not implemented",
                    impact="Cannot detect if probabilities are systematically biased (overconfident or underconfident).",
                    recommendation="Implement Brier score calculation and reliability diagrams. Add bias correction if systematic bias detected.",
                    evidence={"bias_detection": False}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate calibration bias: {e}")


# =============================================================================
# Edge Calculation Validation
# =============================================================================

class EdgeCalculationValidator:
    """
    Validates edge calculation algorithms.
    
    Key Issues to Detect:
    1. Fee-aware edge calculation
    2. Volatility regime adjustments
    3. Momentum fusion weights
    4. Edge threshold hierarchy
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        self.result.components_checked.append("edge_calculation")
    
    def validate(self) -> None:
        """Run all edge calculation validations."""
        self._check_fee_aware_edge()
        self._check_volatility_regime()
        self._check_momentum_fusion()
        self._check_edge_hierarchy()
    
    def _check_fee_aware_edge(self) -> None:
        """
        Check fee-aware edge calculation.
        
        Key Issues:
        - Fee subtraction from edge
        - Fee per contract
        - Minimum edge after fees
        """
        try:
            # Check profile for fee-aware edge config
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for fee-aware edge
                if "fee_aware_edge" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="edge_calculation",
                        severity="high",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Fee-aware edge calculation not configured",
                        impact="Edge calculations may not account for trading fees. Could accept negative-edge trades after fees.",
                        recommendation="Enable fee-aware edge calculation. Subtract per-contract fee from edge before threshold checks.",
                        evidence={"fee_aware": "not found in profile"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate fee-aware edge: {e}")
    
    def _check_volatility_regime(self) -> None:
        """
        Check volatility regime edge adjustments.
        
        Key Issues:
        - Regime detection
        - Edge adjustment factors
        - Low/high volatility thresholds
        """
        try:
            # Check profile for volatility regime config
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for volatility regime adjustments
                if "volatility_regime" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="edge_calculation",
                        severity="medium",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Volatility regime edge adjustments not configured",
                        impact="Edge thresholds don't adapt to volatility regime. May be too tight in high vol or too loose in low vol.",
                        recommendation="Implement volatility regime edge adjustments. Reduce edge requirements in low vol, increase in high vol.",
                        evidence={"volatility_regime": "not found in profile"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate volatility regime: {e}")
    
    def _check_momentum_fusion(self) -> None:
        """
        Check momentum fusion weights.
        
        Key Issues:
        - Logit fusion weights
        - Multi-window velocity weights
        - Weight normalization
        """
        try:
            # Check profile for fusion weights
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for fusion weights
                if "logit_fusion" not in content.lower() and "momentum_weights" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="edge_calculation",
                        severity="medium",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Momentum fusion weights not configured",
                        impact="Signal fusion may use default or unoptimized weights. Suboptimal signal combination.",
                        recommendation="Configure logit fusion weights and multi-window velocity weights. Ensure weights sum to 1.0.",
                        evidence={"fusion_weights": "not found in profile"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate momentum fusion: {e}")
    
    def _check_edge_hierarchy(self) -> None:
        """
        Check edge threshold hierarchy.
        
        Key Issues:
        - Min edge hierarchy (early/mid/late/terminal)
        - Priority order
        - Documentation clarity
        """
        try:
            # Check profile for edge hierarchy
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for edge hierarchy
                if "min_edge" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="edge_calculation",
                        severity="medium",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Edge threshold hierarchy not configured",
                        impact="May use single edge threshold across all TTE. Should have time-varying thresholds (early/mid/late/terminal).",
                        recommendation="Configure edge threshold hierarchy with different values for early, mid, late, and terminal TTE regimes.",
                        evidence={"edge_hierarchy": "not found in profile"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate edge hierarchy: {e}")


# =============================================================================
# Velocity Model Validation
# =============================================================================

class VelocityModelValidator:
    """
    Validates velocity model implementation.
    
    Key Issues to Detect:
    1. Logistic mapping coefficients
    2. Velocity threshold alignment
    3. Multi-window weights
    4. Responsiveness to market conditions
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        self.result.components_checked.append("velocity_model")
    
    def validate(self) -> None:
        """Run all velocity model validations."""
        self._check_logistic_coefficients()
        self._check_velocity_thresholds()
        self._check_multi_window_weights()
        self._check_responsiveness()
    
    def _check_logistic_coefficients(self) -> None:
        """
        Check logistic mapping coefficients.
        
        Key Issues:
        - Alpha_0 and alpha_1 values
        - Responsiveness (slope)
        - Per-asset differences
        """
        try:
            # Check profile for velocity coefficients
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for velocity coefficients
                if "velocity_model:" not in content:
                    self.result.issues.append(ValidationIssue(
                        category="velocity_model",
                        severity="high",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Velocity model logistic coefficients not configured",
                        impact="Velocity-to-probability mapping may use default coefficients. May be unresponsive to market velocity.",
                        recommendation="Configure velocity_model section with alpha_0 and alpha_1 for each asset. Ensure coefficients produce responsive probability shifts.",
                        evidence={"velocity_coefficients": "velocity_model section not found in profile"}
                    ))
                else:
                    # Check if coefficients are reasonable (not too low)
                    # Low coefficients (< 10) cause p_model to stay near 50%
                    import re
                    alpha_pattern = r'velocity_model_alpha_1_[a-z]+:\s*([\d.]+)'
                    matches = re.findall(alpha_pattern, content)
                    for match in matches:
                        alpha_val = float(match)
                        if alpha_val < 10.0:
                            self.result.issues.append(ValidationIssue(
                                category="velocity_model",
                                severity="high",
                                component="config/profiles/kalshi_crypto_15m_v2.yaml",
                                issue=f"Velocity model alpha_1 coefficient too low: {alpha_val}",
                                impact="Low coefficient causes probability to stay near 50% regardless of velocity. Signal is unresponsive.",
                                recommendation="Increase alpha_1 coefficients to 100-500 range for responsive velocity-to-probability mapping.",
                                evidence={"alpha_1_value": alpha_val}
                            ))
            
        except Exception as e:
            logger.warning(f"Failed to validate logistic coefficients: {e}")
    
    def _check_velocity_thresholds(self) -> None:
        """
        Check velocity threshold alignment.
        
        Key Issues:
        - Threshold values vs actual market velocities
        - Per-asset differences
        - Recent market data alignment
        """
        try:
            # Check profile for velocity thresholds
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for velocity thresholds
                if "velocity_threshold" not in content:
                    self.result.issues.append(ValidationIssue(
                        category="velocity_model",
                        severity="high",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Velocity thresholds not configured",
                        impact="May use default thresholds that don't match actual market conditions. Could block all trades or allow excessive noise.",
                        recommendation="Configure velocity_threshold for each asset based on historical market velocity analysis.",
                        evidence={"velocity_thresholds": "not found in profile"}
                    ))
                else:
                    # Check if thresholds are reasonable (not too high)
                    # High thresholds (> 0.01 = 1%) may block all trades in calm markets
                    import re
                    threshold_pattern = r'velocity_threshold_[a-z]+:\s*([\d.]+)'
                    matches = re.findall(threshold_pattern, content)
                    for match in matches:
                        threshold_val = float(match)
                        if threshold_val > 0.01:  # > 1%
                            self.result.issues.append(ValidationIssue(
                                category="velocity_model",
                                severity="high",
                                component="config/profiles/kalshi_crypto_15m_v2.yaml",
                                issue=f"Velocity threshold too high: {threshold_val:.4f} ({threshold_val*100:.2f}%)",
                                impact="High threshold may block all trades in calm markets. Actual market velocities are typically 0.0001-0.001%.",
                                recommendation="Reduce velocity thresholds to 0.0001-0.001 range (0.01-0.1%) based on actual market data analysis.",
                                evidence={"threshold_value": threshold_val}
                            ))
            
        except Exception as e:
            logger.warning(f"Failed to validate velocity thresholds: {e}")
    
    def _check_multi_window_weights(self) -> None:
        """
        Check multi-window velocity weights.
        
        Key Issues:
        - Weight values
        - Normalization (sum to 1)
        - Window sizes
        """
        try:
            # Check profile for multi-window weights
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for multi-window weights
                if "momentum_weights" not in content:
                    self.result.issues.append(ValidationIssue(
                        category="velocity_model",
                        severity="medium",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Multi-window velocity weights not configured",
                        impact="May use single window or default weights. Suboptimal momentum signal fusion.",
                        recommendation="Configure momentum_weights_windows and momentum_weights_values. Ensure weights sum to 1.0.",
                        evidence={"multi_window_weights": "not found in profile"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate multi-window weights: {e}")
    
    def _check_responsiveness(self) -> None:
        """
        Check velocity model responsiveness.
        
        Key Issues:
        - Probability shift range
        - Saturation behavior
        - Edge cases
        """
        try:
            # This would require running the model with test inputs
            # For now, check if there are any tests for responsiveness
            test_files = list(project_root.rglob("*test*velocity*.py"))
            
            has_responsiveness_tests = any("responsiv" in f.name.lower() for f in test_files)
            
            if not has_responsiveness_tests:
                self.result.issues.append(ValidationIssue(
                    category="velocity_model",
                    severity="low",
                    component="Velocity model testing",
                    issue="No velocity model responsiveness tests found",
                    impact="Cannot verify that velocity model produces meaningful probability shifts across velocity range.",
                    recommendation="Add unit tests that verify probability shifts across velocity range (e.g., 0% → 30%, 50% → 70%, 100% → 90%).",
                    evidence={"responsiveness_tests": False}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate responsiveness: {e}")


# =============================================================================
# Correlation Tracking Validation
# =============================================================================

class CorrelationTrackingValidator:
    """
    Validates correlation tracking implementation.
    
    NOTE: Correlation matrices are NOT actively used in the production 15m stack.
    The validation script checks for correlation tracking but it's not a critical
    production concern for the current implementation.
    """
    
    def __init__(self, result: ValidationResult):
        self.result = result
        self.result.components_checked.append("correlation_tracking")
    
    def validate(self) -> None:
        """Run all correlation tracking validations."""
        # Check if correlation tracking is actually used in production
        if not self._is_correlation_used_in_production():
            logger.info("[CORRELATION-VALIDATOR] Correlation tracking not actively used in production 15m stack - skipping validation")
            return
        
        self._check_matrix_updates()
        self._check_matrix_validation()
        self._check_regime_dependence()
        self._check_risk_usage()
    
    def _is_correlation_used_in_production(self) -> bool:
        """Check if correlation matrices are actively used in production."""
        try:
            # Check main_15m_lean.py for active correlation usage
            main_path = project_root / "web" / "main_15m_lean.py"
            if main_path.exists():
                with open(main_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Only count as used if there's actual correlation logic, not just comments
                if "correlation" in content.lower() and "import" in content.lower():
                    # Check if it's importing correlation modules
                    import_lines = [line for line in content.split('\n') if 'import' in line.lower() and 'correlation' in line.lower()]
                    if import_lines:
                        return True
            return False
        except Exception:
            return False
    
    def _check_matrix_updates(self) -> None:
        """
        Check correlation matrix update mechanism.
        
        Key Issues:
        - Update frequency
        - Lookback window
        - Data source
        """
        try:
            # Check if correlation tracking is enabled
            profile_path = project_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
            if profile_path.exists():
                with open(profile_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check for correlation tracking config
                if "correlation_tracking" not in content.lower():
                    self.result.issues.append(ValidationIssue(
                        category="correlation_tracking",
                        severity="medium",
                        component="config/profiles/kalshi_crypto_15m_v2.yaml",
                        issue="Correlation tracking not configured",
                        impact="Portfolio risk calculations ignore correlations. May underestimate portfolio risk for correlated assets.",
                        recommendation="Enable correlation tracking with appropriate update frequency and lookback window.",
                        evidence={"correlation_tracking": "not found in profile"}
                    ))
            
        except Exception as e:
            logger.warning(f"Failed to validate matrix updates: {e}")
    
    def _check_matrix_validation(self) -> None:
        """
        Check correlation matrix validation.
        
        Key Issues:
        - Symmetry check
        - Positive definiteness check
        - Diagonal values = 1
        """
        try:
            # Search for correlation matrix validation code - limit search to specific directories
            corr_dirs = [
                project_root / "risk",
                project_root / "merid",
                project_root / "analytics",
            ]
            corr_files = []
            for corr_dir in corr_dirs:
                if corr_dir.exists():
                    corr_files.extend(corr_dir.rglob("*correlation*.py"))
            
            has_validation = False
            for file_path in corr_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "positive_definite" in content.lower() or "symmetry" in content.lower():
                            has_validation = True
                            break
                except Exception:
                    continue
            
            if not has_validation:
                self.result.issues.append(ValidationIssue(
                    category="correlation_tracking",
                    severity="medium",
                    component="Correlation tracking across stack",
                    issue="Correlation matrix validation not implemented",
                    impact="Invalid correlation matrices (non-symmetric, non-positive-definite) can cause numerical errors in risk calculations.",
                    recommendation="Add validation checks: symmetry (C == C.T), positive definiteness (all eigenvalues > 0), diagonal = 1.",
                    evidence={"matrix_validation": False}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate matrix validation: {e}")
    
    def _check_regime_dependence(self) -> None:
        """
        Check if correlation tracking is regime-dependent.
        
        Key Issues:
        - Regime-specific correlations
        - Transition handling
        - Smooth transitions
        """
        try:
            # Check if correlation tracking uses regime detection - limit search to specific directories
            corr_dirs = [
                project_root / "risk",
                project_root / "merid",
                project_root / "analytics",
            ]
            corr_files = []
            for corr_dir in corr_dirs:
                if corr_dir.exists():
                    corr_files.extend(corr_dir.rglob("*correlation*.py"))
            
            has_regime_corr = False
            for file_path in corr_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if "regime" in content.lower() and "correlation" in content.lower():
                            has_regime_corr = True
                            break
                except Exception:
                    continue
            
            if not has_regime_corr:
                self.result.issues.append(ValidationIssue(
                    category="correlation_tracking",
                    severity="low",
                    component="Correlation tracking across stack",
                    issue="Correlation tracking may not be regime-dependent",
                    impact="Correlations vary by market regime (crisis vs normal). Static correlations may misestimate risk in regime transitions.",
                    recommendation="Consider implementing regime-dependent correlation matrices. Use different correlations for bull/bear/crisis regimes.",
                    evidence={"regime_correlation": False}
                ))
            
        except Exception as e:
            logger.warning(f"Failed to validate regime dependence: {e}")
    
    def _check_risk_usage(self) -> None:
        """
        Check if correlation matrix is used in risk calculations.
        
        Key Issues:
        - Portfolio risk calculation
        - Position sizing adjustment
        - Risk limit enforcement
        """
        try:
            # Check if correlation is used in position_sizing.py
            pos_sizing_path = project_root / "risk" / "position_sizing.py"
            if pos_sizing_path.exists():
                with open(pos_sizing_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Check if correlation is used in portfolio risk calculation
                if "correlation_matrix" in content:
                    # Check if it's actually used (not just stored)
                    if "correlation_risk" in content or "correlation" in content.lower():
                        # Good: correlation is used
                        pass
                    else:
                        self.result.issues.append(ValidationIssue(
                            category="correlation_tracking",
                            severity="medium",
                            component="risk/position_sizing.py",
                            issue="Correlation matrix stored but not used in risk calculations",
                            impact="Portfolio risk calculations ignore correlations despite having correlation data. Risk is underestimated.",
                            recommendation="Use correlation matrix in portfolio risk calculation: σ_p² = wᵀΣw where Σ is correlation matrix.",
                            evidence={"correlation_usage": "matrix stored but not used"}
                        ))
            
        except Exception as e:
            logger.warning(f"Failed to validate risk usage: {e}")


# =============================================================================
# Main Validation Runner
# =============================================================================

def run_comprehensive_validation(profile: str = "kalshi_crypto_15m_v2", verbose: bool = False) -> ValidationResult:
    """
    Run comprehensive mathematical validation across the production stack.
    
    Args:
        profile: Profile name to validate
        verbose: Enable verbose output
        
    Returns:
        ValidationResult with all issues found
    """
    logger.info(f"Starting comprehensive mathematical validation for profile: {profile}")
    
    result = ValidationResult(
        timestamp=datetime.utcnow().isoformat(),
        profile=profile,
        total_issues=0,
        critical_issues=0,
        high_issues=0,
        medium_issues=0,
        low_issues=0,
    )
    
    # Run all validators
    validators = [
        KellyCriterionValidator(result),
        PositionSizingValidator(result),
        RiskManagementValidator(result),
        PerformanceMetricsValidator(result),
        CalibrationValidator(result),
        EdgeCalculationValidator(result),
        VelocityModelValidator(result),
        CorrelationTrackingValidator(result),
    ]
    
    for validator in validators:
        try:
            validator.validate()
        except Exception as e:
            logger.error(f"Validator {validator.__class__.__name__} failed: {e}")
            if verbose:
                import traceback
                traceback.print_exc()
    
    # Count issues by severity
    for issue in result.issues:
        result.total_issues += 1
        if issue.severity == "critical":
            result.critical_issues += 1
        elif issue.severity == "high":
            result.high_issues += 1
        elif issue.severity == "medium":
            result.medium_issues += 1
        elif issue.severity == "low":
            result.low_issues += 1
    
    logger.info(
        f"Validation complete: {result.total_issues} issues found "
        f"({result.critical_issues} critical, {result.high_issues} high, "
        f"{result.medium_issues} medium, {result.low_issues} low)"
    )
    
    return result


def print_validation_report(result: ValidationResult, verbose: bool = False) -> None:
    """Print validation report to console."""
    print("\n" + "=" * 80)
    print("COMPREHENSIVE MATHEMATICAL VALIDATION REPORT")
    print("=" * 80)
    print(f"Profile: {result.profile}")
    print(f"Timestamp: {result.timestamp}")
    print(f"Components Checked: {', '.join(result.components_checked)}")
    print("\n" + "-" * 80)
    print("SUMMARY")
    print("-" * 80)
    print(f"Total Issues: {result.total_issues}")
    print(f"  Critical: {result.critical_issues}")
    print(f"  High:     {result.high_issues}")
    print(f"  Medium:   {result.medium_issues}")
    print(f"  Low:      {result.low_issues}")
    
    if result.issues:
        print("\n" + "-" * 80)
        print("ISSUES")
        print("-" * 80)
        
        # Group by severity
        by_severity = {"critical": [], "high": [], "medium": [], "low": []}
        for issue in result.issues:
            by_severity[issue.severity].append(issue)
        
        for severity in ["critical", "high", "medium", "low"]:
            issues = by_severity[severity]
            if issues:
                print(f"\n{severity.upper()} ({len(issues)} issues):")
                for i, issue in enumerate(issues, 1):
                    print(f"\n  {i}. [{issue.category}] {issue.component}")
                    print(f"     Issue: {issue.issue}")
                    print(f"     Impact: {issue.impact}")
                    print(f"     Recommendation: {issue.recommendation}")
                    if verbose and issue.evidence:
                        print(f"     Evidence: {issue.evidence}")
    
    print("\n" + "=" * 80)


def save_validation_report(result: ValidationResult, output_path: Optional[str] = None) -> str:
    """Save validation report to JSON file."""
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = project_root / "output" / f"math_validation_report_{timestamp}.json"
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result.to_dict(), f, indent=2)
    
    logger.info(f"Validation report saved to: {output_path}")
    return str(output_path)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Comprehensive mathematical validation for MERID production stack"
    )
    parser.add_argument(
        "--profile",
        default="kalshi_crypto_15m_v2",
        help="Profile name to validate (default: kalshi_crypto_15m_v2)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--output",
        help="Output file path for JSON report (default: output/math_validation_report_*.json)"
    )
    
    args = parser.parse_args()
    
    # Run validation
    result = run_comprehensive_validation(profile=args.profile, verbose=args.verbose)
    
    # Print report
    print_validation_report(result, verbose=args.verbose)
    
    # Save report
    output_path = save_validation_report(result, output_path=args.output)
    
    # Exit with error code if critical issues found
    if result.critical_issues > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()

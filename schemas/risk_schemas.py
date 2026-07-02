"""
RiskPreview Schema - Canonical risk assessment structure.

Provides comprehensive risk analysis for any trading action
before execution.

Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class RiskLevel(Enum):
    """Overall risk level classification."""
    MINIMAL = "minimal"      # < 5% risk
    LOW = "low"              # 5-15% risk
    MODERATE = "moderate"    # 15-30% risk
    HIGH = "high"            # 30-50% risk
    EXTREME = "extreme"      # > 50% risk
    UNACCEPTABLE = "unacceptable"  # Should not proceed


class RiskCategory(Enum):
    """Categories of risk factors."""
    MARKET = "market"
    LIQUIDITY = "liquidity"
    EXECUTION = "execution"
    COUNTERPARTY = "counterparty"
    REGULATORY = "regulatory"
    TECHNICAL = "technical"
    CONCENTRATION = "concentration"
    LEVERAGE = "leverage"
    TIMING = "timing"
    CORRELATION = "correlation"


@dataclass
class RiskFactor:
    """A single risk factor in the assessment."""
    factor_id: str = field(default_factory=lambda: f"rf_{uuid.uuid4().hex[:8]}")
    
    # Classification
    category: RiskCategory = RiskCategory.MARKET
    name: str = ""
    description: str = ""
    
    # Scoring
    severity: float = 0.0      # 0-1, how bad if it occurs
    probability: float = 0.0   # 0-1, likelihood of occurrence
    impact_usd: float = 0.0    # Estimated USD impact
    
    # Risk score = severity * probability
    risk_score: float = 0.0
    
    # Mitigation
    mitigatable: bool = True
    mitigation_action: str = ""
    residual_risk: float = 0.0  # Risk after mitigation
    
    def calculate_score(self) -> float:
        """Calculate risk score."""
        self.risk_score = self.severity * self.probability
        return self.risk_score
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
            "probability": self.probability,
            "impact_usd": self.impact_usd,
            "risk_score": self.risk_score,
            "mitigatable": self.mitigatable,
            "mitigation_action": self.mitigation_action,
            "residual_risk": self.residual_risk,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskFactor":
        return cls(
            factor_id=data.get("factor_id", f"rf_{uuid.uuid4().hex[:8]}"),
            category=RiskCategory(data.get("category", "market")),
            name=data.get("name", ""),
            description=data.get("description", ""),
            severity=data.get("severity", 0.0),
            probability=data.get("probability", 0.0),
            impact_usd=data.get("impact_usd", 0.0),
            risk_score=data.get("risk_score", 0.0),
            mitigatable=data.get("mitigatable", True),
            mitigation_action=data.get("mitigation_action", ""),
            residual_risk=data.get("residual_risk", 0.0),
        )


@dataclass
class PositionRisk:
    """Risk metrics for position sizing."""
    current_exposure_usd: float = 0.0
    proposed_exposure_usd: float = 0.0
    total_exposure_usd: float = 0.0
    
    max_allowed_exposure_usd: float = 0.0
    exposure_utilization_pct: float = 0.0
    
    position_concentration_pct: float = 0.0  # % of portfolio in this position
    max_concentration_pct: float = 25.0
    
    leverage_used: int = 1
    max_leverage: int = 3  # STANDARDIZED: Production leverage limit (matches trading/execution.py, risk/risk_guard.py)
    
    margin_required: float = 0.0
    available_margin: float = 0.0
    margin_utilization_pct: float = 0.0
    
    liquidation_price: Optional[float] = None
    distance_to_liquidation_pct: float = 0.0
    
    def is_within_limits(self) -> bool:
        """Check if position is within risk limits."""
        return (
            self.exposure_utilization_pct <= 100 and
            self.position_concentration_pct <= self.max_concentration_pct and
            self.leverage_used <= self.max_leverage and
            self.margin_utilization_pct < 90
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_exposure_usd": self.current_exposure_usd,
            "proposed_exposure_usd": self.proposed_exposure_usd,
            "total_exposure_usd": self.total_exposure_usd,
            "max_allowed_exposure_usd": self.max_allowed_exposure_usd,
            "exposure_utilization_pct": self.exposure_utilization_pct,
            "position_concentration_pct": self.position_concentration_pct,
            "max_concentration_pct": self.max_concentration_pct,
            "leverage_used": self.leverage_used,
            "max_leverage": self.max_leverage,
            "margin_required": self.margin_required,
            "available_margin": self.available_margin,
            "margin_utilization_pct": self.margin_utilization_pct,
            "liquidation_price": self.liquidation_price,
            "distance_to_liquidation_pct": self.distance_to_liquidation_pct,
            "is_within_limits": self.is_within_limits(),
        }


@dataclass
class MarketRisk:
    """Market-specific risk metrics."""
    symbol: str = ""
    
    # Volatility
    current_volatility: float = 0.0
    avg_volatility: float = 0.0
    volatility_percentile: float = 0.0  # Where current vol sits historically
    
    # Liquidity
    bid_ask_spread_pct: float = 0.0
    order_book_depth_usd: float = 0.0
    avg_daily_volume_usd: float = 0.0
    volume_ratio: float = 0.0  # Current vs average
    
    # Price action
    price_change_24h_pct: float = 0.0
    distance_from_high_pct: float = 0.0
    distance_from_low_pct: float = 0.0
    
    # Correlation
    btc_correlation: float = 0.0
    market_beta: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "current_volatility": self.current_volatility,
            "avg_volatility": self.avg_volatility,
            "volatility_percentile": self.volatility_percentile,
            "bid_ask_spread_pct": self.bid_ask_spread_pct,
            "order_book_depth_usd": self.order_book_depth_usd,
            "avg_daily_volume_usd": self.avg_daily_volume_usd,
            "volume_ratio": self.volume_ratio,
            "price_change_24h_pct": self.price_change_24h_pct,
            "distance_from_high_pct": self.distance_from_high_pct,
            "distance_from_low_pct": self.distance_from_low_pct,
            "btc_correlation": self.btc_correlation,
            "market_beta": self.market_beta,
        }


@dataclass
class RiskPreview:
    """
    Complete risk assessment for a trading action.
    
    This is the canonical structure for risk analysis in MERID.
    Generated before any execution to inform decision-making.
    """
    
    # Identity
    preview_id: str = field(default_factory=lambda: f"risk_{uuid.uuid4().hex[:12]}")
    
    # Subject
    intent_id: Optional[str] = None
    intent_hash: Optional[str] = None
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    
    # Overall assessment
    risk_level: RiskLevel = RiskLevel.MODERATE
    overall_risk_score: float = 0.0  # 0-1
    
    # Risk factors
    factors: List[RiskFactor] = field(default_factory=list)
    
    # Detailed risk analysis
    position_risk: PositionRisk = field(default_factory=PositionRisk)
    market_risk: MarketRisk = field(default_factory=MarketRisk)
    
    # Value at Risk
    var_95_usd: float = 0.0
    var_99_usd: float = 0.0
    max_loss_usd: float = 0.0
    
    # Recommendations
    approved: bool = False
    approval_conditions: List[str] = field(default_factory=list)
    recommended_adjustments: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)  # Must be resolved
    
    # Kill switch status
    kill_switch_triggered: bool = False
    kill_switch_reason: str = ""
    
    # Timing
    created_at: float = field(default_factory=time.time)
    valid_until: float = field(default_factory=lambda: time.time() + 60)  # 1 min validity
    
    # Metadata
    assessed_by: str = "risk-agent-01"
    confidence: float = 0.0
    notes: str = ""
    
    def compute_hash(self) -> str:
        """Compute deterministic hash of the preview."""
        hash_data = {
            "preview_id": self.preview_id,
            "intent_id": self.intent_id,
            "symbol": self.symbol,
            "risk_level": self.risk_level.value,
            "overall_risk_score": self.overall_risk_score,
            "created_at": self.created_at,
        }
        json_str = json.dumps(hash_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(json_str.encode()).hexdigest()[:16]
    
    def add_factor(self, factor: RiskFactor) -> None:
        """Add a risk factor."""
        factor.calculate_score()
        self.factors.append(factor)
    
    def calculate_overall_risk(self) -> float:
        """Calculate overall risk score from factors."""
        if not self.factors:
            return 0.0
        
        # Weighted average with emphasis on high-severity factors
        total_weight = 0.0
        weighted_sum = 0.0
        
        for factor in self.factors:
            weight = 1.0 + factor.severity  # Higher severity = more weight
            weighted_sum += factor.risk_score * weight
            total_weight += weight
        
        self.overall_risk_score = weighted_sum / total_weight if total_weight > 0 else 0.0
        return self.overall_risk_score
    
    def determine_risk_level(self) -> RiskLevel:
        """Determine risk level from score."""
        self.calculate_overall_risk()
        
        # Check for blockers first
        if self.blockers:
            self.risk_level = RiskLevel.UNACCEPTABLE
            return self.risk_level
        
        if self.kill_switch_triggered:
            self.risk_level = RiskLevel.UNACCEPTABLE
            return self.risk_level
        
        # Score-based classification
        if self.overall_risk_score < 0.05:
            self.risk_level = RiskLevel.MINIMAL
        elif self.overall_risk_score < 0.15:
            self.risk_level = RiskLevel.LOW
        elif self.overall_risk_score < 0.30:
            self.risk_level = RiskLevel.MODERATE
        elif self.overall_risk_score < 0.50:
            self.risk_level = RiskLevel.HIGH
        else:
            self.risk_level = RiskLevel.EXTREME
        
        return self.risk_level
    
    def evaluate_approval(self) -> bool:
        """Evaluate if the action should be approved."""
        self.determine_risk_level()
        
        # Never approve unacceptable risk
        if self.risk_level == RiskLevel.UNACCEPTABLE:
            self.approved = False
            return False
        
        # Never approve with blockers
        if self.blockers:
            self.approved = False
            return False
        
        # Check position limits
        if not self.position_risk.is_within_limits():
            self.approved = False
            self.blockers.append("Position exceeds risk limits")
            return False
        
        # Approve with conditions for moderate/high risk
        if self.risk_level in [RiskLevel.HIGH, RiskLevel.EXTREME]:
            self.approved = False
            self.approval_conditions.append("Requires manual review")
            return False
        
        self.approved = True
        return True
    
    def is_valid(self) -> bool:
        """Check if preview is still valid."""
        return time.time() < self.valid_until
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "hash": self.compute_hash(),
            "intent_id": self.intent_id,
            "intent_hash": self.intent_hash,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "risk_level": self.risk_level.value,
            "overall_risk_score": self.overall_risk_score,
            "factors": [f.to_dict() for f in self.factors],
            "position_risk": self.position_risk.to_dict(),
            "market_risk": self.market_risk.to_dict(),
            "var_95_usd": self.var_95_usd,
            "var_99_usd": self.var_99_usd,
            "max_loss_usd": self.max_loss_usd,
            "approved": self.approved,
            "approval_conditions": self.approval_conditions,
            "recommended_adjustments": self.recommended_adjustments,
            "warnings": self.warnings,
            "blockers": self.blockers,
            "kill_switch_triggered": self.kill_switch_triggered,
            "kill_switch_reason": self.kill_switch_reason,
            "created_at": self.created_at,
            "valid_until": self.valid_until,
            "is_valid": self.is_valid(),
            "assessed_by": self.assessed_by,
            "confidence": self.confidence,
            "notes": self.notes,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskPreview":
        factors = [RiskFactor.from_dict(f) for f in data.get("factors", [])]
        
        position_data = data.get("position_risk", {})
        market_data = data.get("market_risk", {})
        
        return cls(
            preview_id=data.get("preview_id", f"risk_{uuid.uuid4().hex[:12]}"),
            intent_id=data.get("intent_id"),
            intent_hash=data.get("intent_hash"),
            symbol=data.get("symbol", ""),
            side=data.get("side", ""),
            quantity=data.get("quantity", 0.0),
            risk_level=RiskLevel(data.get("risk_level", "moderate")),
            overall_risk_score=data.get("overall_risk_score", 0.0),
            factors=factors,
            position_risk=PositionRisk(
                current_exposure_usd=position_data.get("current_exposure_usd", 0.0),
                proposed_exposure_usd=position_data.get("proposed_exposure_usd", 0.0),
                total_exposure_usd=position_data.get("total_exposure_usd", 0.0),
                max_allowed_exposure_usd=position_data.get("max_allowed_exposure_usd", 0.0),
                exposure_utilization_pct=position_data.get("exposure_utilization_pct", 0.0),
                position_concentration_pct=position_data.get("position_concentration_pct", 0.0),
                leverage_used=position_data.get("leverage_used", 1),
                margin_required=position_data.get("margin_required", 0.0),
                available_margin=position_data.get("available_margin", 0.0),
                margin_utilization_pct=position_data.get("margin_utilization_pct", 0.0),
                liquidation_price=position_data.get("liquidation_price"),
                distance_to_liquidation_pct=position_data.get("distance_to_liquidation_pct", 0.0),
            ),
            market_risk=MarketRisk(
                symbol=market_data.get("symbol", ""),
                current_volatility=market_data.get("current_volatility", 0.0),
                avg_volatility=market_data.get("avg_volatility", 0.0),
                volatility_percentile=market_data.get("volatility_percentile", 0.0),
                bid_ask_spread_pct=market_data.get("bid_ask_spread_pct", 0.0),
                order_book_depth_usd=market_data.get("order_book_depth_usd", 0.0),
                avg_daily_volume_usd=market_data.get("avg_daily_volume_usd", 0.0),
                volume_ratio=market_data.get("volume_ratio", 0.0),
                price_change_24h_pct=market_data.get("price_change_24h_pct", 0.0),
                btc_correlation=market_data.get("btc_correlation", 0.0),
                market_beta=market_data.get("market_beta", 0.0),
            ),
            var_95_usd=data.get("var_95_usd", 0.0),
            var_99_usd=data.get("var_99_usd", 0.0),
            max_loss_usd=data.get("max_loss_usd", 0.0),
            approved=data.get("approved", False),
            approval_conditions=data.get("approval_conditions", []),
            recommended_adjustments=data.get("recommended_adjustments", []),
            warnings=data.get("warnings", []),
            blockers=data.get("blockers", []),
            kill_switch_triggered=data.get("kill_switch_triggered", False),
            kill_switch_reason=data.get("kill_switch_reason", ""),
            created_at=data.get("created_at", time.time()),
            valid_until=data.get("valid_until", time.time() + 60),
            assessed_by=data.get("assessed_by", "risk-agent-01"),
            confidence=data.get("confidence", 0.0),
            notes=data.get("notes", ""),
        )
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "RiskPreview":
        return cls.from_dict(json.loads(json_str))

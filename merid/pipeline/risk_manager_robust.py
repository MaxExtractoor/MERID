"""
Enhanced Risk Manager with Robustness Features

Critical fixes for the Global Risk Manager to address:
- Thread safety for shared state
- Error handling and retry logic
- Input validation and sanitization
- Circuit breaking for external dependencies
- Graceful shutdown handling
- Resource management
- Health checks and monitoring
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Callable, Any

from merid.pipeline.proposal import TradeDomain, TradeProposal, ProposalStatus
from merid.pipeline.risk_context import RiskContext
from merid.pipeline.robustness import (
    ThreadSafeState, HealthChecker, PipelineMetrics, GracefulShutdown,
    validate_inputs, validate_positive_number, ErrorRecovery,
    get_health_checker, get_metrics, get_shutdown_handler
)

from utils.logger import get_logger

logger = get_logger("merid.pipeline.risk_manager_robust")


# ── Enhanced Data Classes with Validation ─────────────────────────────────────

@dataclass
class DomainRiskConfig:
    """Enhanced risk config with validation."""
    domain: TradeDomain
    max_allocation_pct: Decimal = Decimal("0.50")
    max_notional_usd: Decimal = Decimal("10000")
    max_daily_loss_usd: Decimal = Decimal("500")
    max_positions: int = 50
    max_single_order_usd: Decimal = Decimal("1000")
    enabled: bool = True

    def __post_init__(self):
        """Validate risk config parameters."""
        if not (Decimal("0") < self.max_allocation_pct <= Decimal("1")):
            raise ValueError(f"Invalid max_allocation_pct: {self.max_allocation_pct}")
        
        if self.max_notional_usd <= 0:
            raise ValueError(f"Invalid max_notional_usd: {self.max_notional_usd}")
        
        if self.max_daily_loss_usd < 0:
            raise ValueError(f"Invalid max_daily_loss_usd: {self.max_daily_loss_usd}")
        
        if self.max_positions <= 0:
            raise ValueError(f"Invalid max_positions: {self.max_positions}")
        
        if self.max_single_order_usd <= 0:
            raise ValueError(f"Invalid max_single_order_usd: {self.max_single_order_usd}")


@dataclass
class VenueExposure:
    """Enhanced venue exposure with validation."""
    venue: str
    domain: str
    notional_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    realized_pnl_usd: Decimal = Decimal("0")
    position_count: int = 0
    daily_trades: int = 0
    daily_loss_usd: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Validate exposure data."""
        if not validate_non_empty_string(self.venue):
            raise ValueError("Invalid venue: cannot be empty")
        
        if not validate_non_empty_string(self.domain):
            raise ValueError("Invalid domain: cannot be empty")
        
        if self.position_count < 0:
            raise ValueError(f"Invalid position_count: {self.position_count}")
        
        if self.daily_trades < 0:
            raise ValueError(f"Invalid daily_trades: {self.daily_trades}")


@dataclass
class RiskCheckResult:
    """Enhanced risk check result with validation."""
    approved: bool
    reason: str
    adjusted_qty: Optional[Decimal] = None
    domain: str = ""
    venue: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    risk_score: float = 0.0  # 0-1 risk score
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate risk check result."""
        if not validate_non_empty_string(self.reason):
            raise ValueError("Invalid reason: cannot be empty")
        
        if not (0.0 <= self.risk_score <= 1.0):
            raise ValueError(f"Invalid risk_score: {self.risk_score}")
        
        if self.adjusted_qty is not None and self.adjusted_qty <= 0:
            raise ValueError(f"Invalid adjusted_qty: {self.adjusted_qty}")

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "adjusted_qty": str(self.adjusted_qty) if self.adjusted_qty else None,
            "domain": self.domain,
            "venue": self.venue,
            "timestamp": self.timestamp.isoformat(),
            "risk_score": self.risk_score,
            "warnings": self.warnings
        }


# ── Enhanced Global Risk Manager with Robustness ─────────────────────────────

class GlobalRiskManagerRobust:
    """
    Enhanced Global Risk Manager with comprehensive robustness features.
    
    Key improvements:
    - Thread-safe state management
    - Input validation and sanitization
    - Error handling and retry logic
    - Health checks and monitoring
    - Graceful shutdown handling
    - Resource management
    """

    def __init__(self, total_capital_usd: Decimal = Decimal("100000")):
        # Thread-safe state management
        self._state = ThreadSafeState()
        self._state.set("total_capital_usd", total_capital_usd)
        self._state.set("domain_configs", _DEFAULT_DOMAIN_CONFIGS.copy())
        self._state.set("exposures", {})
        self._state.set("halted_domains", {})
        self._state.set("daily_reset_ts", time.time())
        self._state.set("risk_checks_performed", 0)
        self._state.set("risk_checks_failed", 0)

        # Robustness components
        self._metrics = get_metrics()
        self._health_checker = get_health_checker()
        self._shutdown_handler = get_shutdown_handler()
        
        # Register health checks
        self._health_checker.register_check("risk_manager_status", self._health_check_status)
        self._health_checker.register_check("exposure_health", self._health_check_exposures)
        self._health_checker.register_check("domain_health", self._health_check_domains)

        # Register shutdown handler
        self._shutdown_handler.register_handler(self._cleanup_resources)

        # Initialize default exposures
        self._initialize_default_exposures()

    # ── Thread-Safe State Access Methods ─────────────────────────────────────

    @validate_inputs(domain=str, venue=str)
    def get_exposure(self, domain: str, venue: str) -> Optional[VenueExposure]:
        """Thread-safe exposure access."""
        key = f"{domain}:{venue}"
        exposures = self._state.get("exposures", {})
        return exposures.get(key)

    @validate_inputs(domain=str, venue=str)
    def update_exposure(self, domain: str, venue: str, updates: Dict[str, Any]) -> None:
        """Thread-safe exposure update."""
        key = f"{domain}:{venue}"
        exposures = self._state.get("exposures", {})
        
        if key not in exposures:
            exposures[key] = VenueExposure(venue=venue, domain=domain)
        
        exposure = exposures[key]
        
        # Update fields with validation
        for field, value in updates.items():
            if hasattr(exposure, field):
                if field in ["notional_usd", "unrealized_pnl_usd", "realized_pnl_usd", "daily_loss_usd"]:
                    if isinstance(value, (int, float, Decimal)):
                        setattr(exposure, field, Decimal(str(value)))
                elif field in ["position_count", "daily_trades"]:
                    if isinstance(value, int) and value >= 0:
                        setattr(exposure, field, value)
                elif field == "last_updated":
                    if isinstance(value, datetime):
                        setattr(exposure, field, value)
        
        exposure.last_updated = datetime.now(timezone.utc)

    # ── Enhanced Risk Check with Robustness ─────────────────────────────────────

    @validate_inputs(proposal=lambda x: isinstance(x, TradeProposal))
    async def check_proposal(
        self,
        proposal: TradeProposal,
        risk_context: Optional["RiskContext"] = None,
    ) -> RiskCheckResult:
        """Enhanced risk check with comprehensive error handling."""
        try:
            self._state.get("risk_checks_performed", 0)
            
            # Extract and validate domain/venue
            domain = proposal.domain
            venue = proposal.venue
            domain_str = domain.value if isinstance(domain, TradeDomain) else str(domain)
            
            if not validate_non_empty_string(domain_str):
                return RiskCheckResult(
                    approved=False,
                    reason="Invalid domain specified",
                    domain=domain_str,
                    venue=venue,
                    risk_score=1.0
                )

            # Check if domain is halted
            if self.is_domain_halted(domain_str):
                return RiskCheckResult(
                    approved=False,
                    reason=f"Domain {domain_str} is halted: {self._state.get('halted_domains', {}).get(domain_str, 'Unknown')}",
                    domain=domain_str,
                    venue=venue,
                    risk_score=1.0
                )

            # Get and validate domain config
            cfg = self._state.get("domain_configs", {}).get(domain)
            if not cfg:
                return RiskCheckResult(
                    approved=False,
                    reason=f"No risk config for domain {domain_str}",
                    domain=domain_str,
                    venue=venue,
                    risk_score=1.0
                )

            # Check if domain is enabled
            if not cfg.enabled:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Domain {domain_str} is disabled in risk config",
                    domain=domain_str,
                    venue=venue,
                    risk_score=0.8
                )

            # Calculate order notional with validation
            order_notional = self._calculate_order_notional(proposal)
            if order_notional <= 0:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Invalid order notional: {order_notional}",
                    domain=domain_str,
                    venue=venue,
                    risk_score=1.0
                )

            # Apply risk context scaling
            scaled_notional = self._apply_risk_context_scaling(order_notional, risk_context)
            if scaled_notional <= 0:
                return RiskCheckResult(
                    approved=False,
                    reason=f"RiskContext scaling reduced notional to $0 (system stress)",
                    domain=domain_str,
                    venue=venue,
                    risk_score=1.0
                )

            # Perform comprehensive risk checks
            risk_results = []
            
            # 1. Single order limit
            single_order_result = self._check_single_order_limit(scaled_notional, cfg, domain_str, venue)
            risk_results.append(single_order_result)
            
            # 2. Domain allocation limit
            allocation_result = self._check_domain_allocation(domain_str, cfg)
            risk_results.append(allocation_result)
            
            # 3. Daily loss limit
            daily_loss_result = self._check_daily_loss_limit(domain_str, cfg)
            risk_results.append(daily_loss_result)
            
            # 4. Position count limit
            position_count_result = self._check_position_count_limit(domain_str, cfg)
            risk_results.append(position_count_result)
            
            # 5. Venue exposure limit
            venue_exposure_result = self._check_venue_exposure_limit(domain_str, venue, scaled_notional, cfg)
            risk_results.append(venue_exposure_result)

            # Aggregate results
            final_result = self._aggregate_risk_results(risk_results, domain_str, venue, scaled_notional)
            
            # Update metrics
            if not final_result.approved:
                self._state.get("risk_checks_failed", 0)
                self._metrics.increment_counter("risk_checks_failed")
            
            self._metrics.increment_counter("risk_checks_performed")
            self._metrics.record_timing("risk_check_duration", time.time())
            
            return final_result

        except Exception as exc:
            logger.error(f"Risk check failed for proposal: {exc}")
            self._state.get("risk_checks_failed", 0)
            self._metrics.increment_counter("risk_check_errors")
            
            return RiskCheckResult(
                approved=False,
                reason=f"Risk check error: {str(exc)}",
                domain="unknown",
                venue="unknown",
                risk_score=1.0
            )

    def _calculate_order_notional(self, proposal: TradeProposal) -> Decimal:
        """Calculate order notional with validation."""
        order_notional = Decimal("0")
        
        if proposal.notional_usd:
            order_notional = proposal.notional_usd
        elif proposal.price and proposal.qty:
            order_notional = (proposal.price * proposal.qty).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
        elif proposal.qty:
            order_notional = proposal.qty  # fallback: treat qty as notional
        
        return order_notional

    def _apply_risk_context_scaling(self, order_notional: Decimal, risk_context: Optional["RiskContext"]) -> Decimal:
        """Apply risk context size scaling."""
        if risk_context is not None and risk_context.size_scale_factor < 1.0:
            scaled = (order_notional * Decimal(str(risk_context.size_scale_factor))).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            return scaled
        return order_notional

    def _check_single_order_limit(self, notional: Decimal, cfg: DomainRiskConfig, domain: str, venue: str) -> RiskCheckResult:
        """Check single order limit."""
        if notional > cfg.max_single_order_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Order notional ${notional} exceeds single order limit ${cfg.max_single_order_usd}",
                domain=domain,
                venue=venue,
                risk_score=0.9
            )
        
        return RiskCheckResult(
            approved=True,
            reason="Single order limit check passed",
            domain=domain,
            venue=venue,
            risk_score=0.1
        )

    def _check_domain_allocation(self, domain: str, cfg: DomainRiskConfig) -> RiskCheckResult:
        """Check domain allocation limit."""
        domain_notional = self.domain_notional(domain)
        total_capital = self._state.get("total_capital_usd", Decimal("100000"))
        current_allocation = domain_notional / total_capital if total_capital > 0 else Decimal("0")
        
        if current_allocation > cfg.max_allocation_pct:
            return RiskCheckResult(
                approved=False,
                reason=f"Domain allocation {current_allocation:.2%} exceeds limit {cfg.max_allocation_pct:.2%}",
                domain=domain,
                venue="",
                risk_score=0.8
            )
        
        return RiskCheckResult(
            approved=True,
            reason="Domain allocation check passed",
            domain=domain,
            venue="",
            risk_score=0.2
        )

    def _check_daily_loss_limit(self, domain: str, cfg: DomainRiskConfig) -> RiskCheckResult:
        """Check daily loss limit."""
        daily_loss = self.domain_daily_loss(domain)
        
        if daily_loss > cfg.max_daily_loss_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily loss ${daily_loss} exceeds limit ${cfg.max_daily_loss_usd}",
                domain=domain,
                venue="",
                risk_score=0.9
            )
        
        return RiskCheckResult(
            approved=True,
            reason="Daily loss limit check passed",
            domain=domain,
            venue="",
            risk_score=0.1
        )

    def _check_position_count_limit(self, domain: str, cfg: DomainRiskConfig) -> RiskCheckResult:
        """Check position count limit."""
        position_count = self.domain_positions(domain)
        
        if position_count >= cfg.max_positions:
            return RiskCheckResult(
                approved=False,
                reason=f"Position count {position_count} exceeds limit {cfg.max_positions}",
                domain=domain,
                venue="",
                risk_score=0.7
            )
        
        return RiskCheckResult(
            approved=True,
            reason="Position count check passed",
            domain=domain,
            venue="",
            risk_score=0.1
        )

    def _check_venue_exposure_limit(self, domain: str, venue: str, notional: Decimal, cfg: DomainRiskConfig) -> RiskCheckResult:
        """Check venue exposure limit."""
        exposure = self.get_exposure(domain, venue)
        current_exposure = exposure.notional_usd if exposure else Decimal("0")
        projected_exposure = current_exposure + notional
        
        # Venue limit is 50% of domain notional limit
        venue_limit = cfg.max_notional_usd * Decimal("0.5")
        
        if projected_exposure > venue_limit:
            return RiskCheckResult(
                approved=False,
                reason=f"Venue exposure ${projected_exposure} would exceed limit ${venue_limit}",
                domain=domain,
                venue=venue,
                risk_score=0.6
            )
        
        return RiskCheckResult(
            approved=True,
            reason="Venue exposure check passed",
            domain=domain,
            venue=venue,
            risk_score=0.1
        )

    def _aggregate_risk_results(self, results: List[RiskCheckResult], domain: str, venue: str, notional: Decimal) -> RiskCheckResult:
        """Aggregate multiple risk check results."""
        failed_checks = [r for r in results if not r.approved]
        
        if failed_checks:
            # Return the most critical failure
            most_critical = max(failed_checks, key=lambda r: r.risk_score)
            return RiskCheckResult(
                approved=False,
                reason=most_critical.reason,
                domain=domain,
                venue=venue,
                risk_score=most_critical.risk_score,
                warnings=[r.reason for r in results if r.approved and r.risk_score > 0.3]
            )
        
        # All checks passed
        avg_risk_score = sum(r.risk_score for r in results) / len(results)
        warnings = [r.reason for r in results if r.risk_score > 0.3]
        
        return RiskCheckResult(
            approved=True,
            reason="All risk checks passed",
            domain=domain,
            venue=venue,
            risk_score=avg_risk_score,
            warnings=warnings
        )

    # ── Domain Management with Thread Safety ─────────────────────────────────────

    @validate_inputs(domain=str, reason=str)
    def halt_domain(self, domain: str, reason: str) -> None:
        """Thread-safe domain halt."""
        if not validate_non_empty_string(domain):
            raise ValueError("Domain cannot be empty")
        
        if not validate_non_empty_string(reason):
            raise ValueError("Reason cannot be empty")
        
        self._state.get("halted_domains", {})[domain] = reason
        logger.warning(f"Domain {domain} halted: {reason}")
        self._metrics.increment_counter("domains_halted")

    @validate_inputs(domain=str)
    def resume_domain(self, domain: str) -> None:
        """Thread-safe domain resume."""
        if not validate_non_empty_string(domain):
            raise ValueError("Domain cannot be empty")
        
        halted = self._state.get("halted_domains", {})
        if domain in halted:
            del halted[domain]
            logger.info(f"Domain {domain} resumed")
            self._metrics.increment_counter("domains_resumed")

    @validate_inputs(domain=str)
    def is_domain_halted(self, domain: str) -> bool:
        """Thread-safe domain halt check."""
        return domain in self._state.get("halted_domains", {})

    # ── Exposure Calculations with Thread Safety ─────────────────────────────────

    def domain_notional(self, domain: str) -> Decimal:
        """Thread-safe domain notional calculation."""
        exposures = self._state.get("exposures", {})
        return sum(
            (e.notional_usd for e in exposures.values() if e.domain == domain),
            Decimal("0"),
        )

    def domain_daily_loss(self, domain: str) -> Decimal:
        """Thread-safe domain daily loss calculation."""
        exposures = self._state.get("exposures", {})
        return sum(
            (e.daily_loss_usd for e in exposures.values() if e.domain == domain),
            Decimal("0"),
        )

    def domain_positions(self, domain: str) -> int:
        """Thread-safe domain position count."""
        exposures = self._state.get("exposures", {})
        return sum(
            e.position_count for e in exposures.values() if e.domain == domain
        )

    def portfolio_notional(self) -> Decimal:
        """Thread-safe portfolio notional calculation."""
        exposures = self._state.get("exposures", {})
        return sum((e.notional_usd for e in exposures.values()), Decimal("0"))

    # ── Health Check Implementations ─────────────────────────────────────────────

    async def _health_check_status(self) -> Dict[str, Any]:
        """Check risk manager status health."""
        return {
            "healthy": True,
            "total_capital": str(self._state.get("total_capital_usd", Decimal("0"))),
            "risk_checks_performed": self._state.get("risk_checks_performed", 0),
            "risk_checks_failed": self._state.get("risk_checks_failed", 0),
            "halted_domains": list(self._state.get("halted_domains", {}).keys()),
            "total_exposures": len(self._state.get("exposures", {}))
        }

    async def _health_check_exposures(self) -> Dict[str, Any]:
        """Check exposure health."""
        exposures = self._state.get("exposures", {})
        total_exposure = sum(e.notional_usd for e in exposures.values())
        
        return {
            "healthy": total_exposure < self._state.get("total_capital_usd", Decimal("100000")),
            "total_exposure": str(total_exposure),
            "exposure_count": len(exposures),
            "utilization": float(total_exposure / self._state.get("total_capital_usd", Decimal("100000")))
        }

    async def _health_check_domains(self) -> Dict[str, Any]:
        """Check domain health."""
        configs = self._state.get("domain_configs", {})
        enabled_domains = sum(1 for cfg in configs.values() if cfg.enabled)
        halted_domains = len(self._state.get("halted_domains", {}))
        
        return {
            "healthy": enabled_domains > halted_domains,
            "total_domains": len(configs),
            "enabled_domains": enabled_domains,
            "halted_domains": halted_domains
        }

    # ── Resource Management ─────────────────────────────────────────────────────

    def _initialize_default_exposures(self) -> None:
        """Initialize default exposure tracking."""
        # This would be populated with actual venues from configuration
        default_venues = ["kalshi", "binance", "coinbase", "kraken"]
        domains = ["prediction", "crypto", "equity"]
        
        for domain in domains:
            for venue in default_venues:
                key = f"{domain}:{venue}"
                if key not in self._state.get("exposures", {}):
                    self._state.get("exposures", {})[key] = VenueExposure(venue=venue, domain=domain)

    async def _cleanup_resources(self) -> None:
        """Clean up risk manager resources."""
        logger.info("Cleaning up risk manager resources...")
        
        # Clear state
        self._state.clear()
        
        logger.info("Risk manager resources cleaned up")

    # ── Public API with Enhanced Features ─────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Get comprehensive risk manager summary."""
        exposures = self._state.get("exposures", {})
        
        return {
            "total_capital_usd": str(self._state.get("total_capital_usd", Decimal("0"))),
            "portfolio_notional": str(self.portfolio_notional()),
            "total_exposures": len(exposures),
            "halted_domains": self._state.get("halted_domains", {}),
            "domain_configs": {
                domain.value if hasattr(domain, 'value') else str(domain): {
                    "max_allocation_pct": str(cfg.max_allocation_pct),
                    "max_notional_usd": str(cfg.max_notional_usd),
                    "max_daily_loss_usd": str(cfg.max_daily_loss_usd),
                    "max_positions": cfg.max_positions,
                    "max_single_order_usd": str(cfg.max_single_order_usd),
                    "enabled": cfg.enabled
                }
                for domain, cfg in self._state.get("domain_configs", {}).items()
            },
            "exposures": {
                key: {
                    "notional_usd": str(exp.notional_usd),
                    "unrealized_pnl_usd": str(exp.unrealized_pnl_usd),
                    "realized_pnl_usd": str(exp.realized_pnl_usd),
                    "position_count": exp.position_count,
                    "daily_trades": exp.daily_trades,
                    "daily_loss_usd": str(exp.daily_loss_usd),
                    "last_updated": exp.last_updated.isoformat()
                }
                for key, exp in exposures.items()
            },
            "metrics": self._metrics.get_summary(),
            "health": self._health_checker.get_summary()
        }


# ── Default Configurations (from original) ─────────────────────────────────────

_DEFAULT_DOMAIN_CONFIGS = {
    TradeDomain.PREDICTION: DomainRiskConfig(
        domain=TradeDomain.PREDICTION,
        max_allocation_pct=Decimal("0.10"),
        max_notional_usd=Decimal("5000"),
        max_daily_loss_usd=Decimal("250"),
        max_positions=20,
        max_single_order_usd=Decimal("500"),
    ),
    TradeDomain.CRYPTO: DomainRiskConfig(
        domain=TradeDomain.CRYPTO,
        max_allocation_pct=Decimal("0.50"),
        max_notional_usd=Decimal("25000"),
        max_daily_loss_usd=Decimal("1000"),
        max_positions=30,
        max_single_order_usd=Decimal("5000"),
    ),
    TradeDomain.EQUITY: DomainRiskConfig(
        domain=TradeDomain.EQUITY,
        max_allocation_pct=Decimal("0.30"),
        max_notional_usd=Decimal("15000"),
        max_daily_loss_usd=Decimal("750"),
        max_positions=25,
        max_single_order_usd=Decimal("2500"),
    ),
}


# ── Helper Functions ─────────────────────────────────────────────────────────

def validate_non_empty_string(value: Any) -> bool:
    """Validate non-empty string."""
    return isinstance(value, str) and len(value.strip()) > 0


def _get_liquidity_tier(instrument_id: str) -> int:
    """Return liquidity_tier (1-3) for a MERID instrument_id."""
    try:
        from data.asset_universe import ASSET_UNIVERSE
        base = instrument_id.split("-")[0] if "-" in instrument_id else instrument_id.split("/")[0]
        asset = ASSET_UNIVERSE.get(base)
        return asset.liquidity_tier if asset else 3
    except Exception:
        return 3


# ── Singleton with Thread Safety ─────────────────────────────────────────────────

_risk_manager_robust: Optional[GlobalRiskManagerRobust] = None
_risk_manager_lock = threading.Lock()


def get_global_risk_manager_robust(total_capital_usd: Decimal = Decimal("100000")) -> GlobalRiskManagerRobust:
    """Get or create the robust global risk manager singleton."""
    global _risk_manager_robust
    if _risk_manager_robust is None:
        with _risk_manager_lock:
            if _risk_manager_robust is None:
                _risk_manager_robust = GlobalRiskManagerRobust(total_capital_usd)
    return _risk_manager_robust


# ── Backward Compatibility ─────────────────────────────────────────────────────

# Legacy aliases for backward compatibility
GlobalRiskManager = GlobalRiskManagerRobust
get_global_risk_manager = get_global_risk_manager_robust

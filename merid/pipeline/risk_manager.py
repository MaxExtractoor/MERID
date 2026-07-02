"""§4 Global Risk Manager — Cross-domain limits, capital routing, domain PnL.

Tracks total exposures and PnL across prediction markets, crypto, and
equities.  Enforces per-domain and per-venue limits.  Decides allowed
size for new proposals based on available capital and current exposures.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

from merid.pipeline.proposal import TradeDomain, TradeProposal, ProposalStatus

from utils.logger import get_logger

_LIQUIDITY_TIER_SCALE: dict = {1: Decimal("1.00"), 2: Decimal("0.75"), 3: Decimal("0.50")}


def _get_liquidity_tier(instrument_id: str) -> int:
    """Return liquidity_tier (1-3) for a MERID instrument_id like 'BTC-USD'."""
    try:
        from data.asset_universe import ASSET_UNIVERSE
        base = instrument_id.split("-")[0] if "-" in instrument_id else instrument_id.split("/")[0]
        asset = ASSET_UNIVERSE.get(base)
        return asset.liquidity_tier if asset else 3
    except Exception:
        return 3

logger = get_logger("merid.pipeline.risk_manager")


@dataclass
class DomainRiskConfig:
    """Risk limits for a single domain."""
    domain: TradeDomain
    max_allocation_pct: Decimal = Decimal("0.50")   # Max % of total capital
    max_notional_usd: Decimal = Decimal("10000")
    max_daily_loss_usd: Decimal = Decimal("500")
    max_positions: int = 50
    max_single_order_usd: Decimal = Decimal("1000")
    enabled: bool = True


@dataclass
class VenueExposure:
    """Tracks exposure for a single venue."""
    venue: str
    domain: str
    notional_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    realized_pnl_usd: Decimal = Decimal("0")
    position_count: int = 0
    daily_trades: int = 0
    daily_loss_usd: Decimal = Decimal("0")


@dataclass
class RiskCheckResult:
    """Result of a global risk check on a proposal."""
    approved: bool
    reason: str
    adjusted_qty: Optional[Decimal] = None
    domain: str = ""
    venue: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "adjusted_qty": str(self.adjusted_qty) if self.adjusted_qty else None,
            "domain": self.domain,
            "venue": self.venue,
            "timestamp": self.timestamp.isoformat(),
        }


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
        max_allocation_pct=Decimal("0.40"),
        max_notional_usd=Decimal("20000"),
        max_daily_loss_usd=Decimal("500"),
        max_positions=50,
        max_single_order_usd=Decimal("2000"),
    ),
    TradeDomain.MACRO: DomainRiskConfig(
        domain=TradeDomain.MACRO,
        max_allocation_pct=Decimal("0.20"),
        max_notional_usd=Decimal("10000"),
        max_daily_loss_usd=Decimal("300"),
        max_positions=20,
        max_single_order_usd=Decimal("1000"),
    ),
}


class GlobalRiskManager:
    """Cross-domain risk manager for the unified pipeline.

    Checks (in order):
    1. Domain enabled?
    2. Single order size limit.
    3. Domain notional limit.
    4. Domain daily loss limit.
    5. Domain position count limit.
    6. Portfolio-wide notional limit.
    7. Capital allocation % per domain.
    """

    def __init__(
        self,
        total_capital_usd: Optional[Decimal] = None,
        max_portfolio_notional_usd: Optional[Decimal] = None,
        domain_configs: Optional[Dict[TradeDomain, DomainRiskConfig]] = None,
    ):
        # CRITICAL: No hardcoded defaults - must fetch from settings or Kalshi balance
        if total_capital_usd is None:
            try:
                from merid.settings import settings
                total_capital_usd = Decimal(str(settings.MERID_TOTAL_CAPITAL_USD))
                logger.info("[RISK_MANAGER] Loaded total_capital_usd from settings: $%s", total_capital_usd)
            except Exception as exc:
                logger.error("[RISK_MANAGER] Failed to load total_capital_usd from settings: %s", exc)
                raise RuntimeError(
                    "GlobalRiskManager requires total_capital_usd - either provide explicitly "
                    "or ensure settings.MERID_TOTAL_CAPITAL_USD is configured (fetched from Kalshi balance)"
                ) from exc
        
        if max_portfolio_notional_usd is None:
            # Default to 100% of total capital (portfolio notional = total capital deployed)
            max_portfolio_notional_usd = total_capital_usd
            logger.info("[RISK_MANAGER] Set max_portfolio_notional_usd = total_capital_usd: $%s", max_portfolio_notional_usd)
        
        self.total_capital_usd = total_capital_usd
        self.max_portfolio_notional_usd = max_portfolio_notional_usd
        self._domain_configs = domain_configs or self._build_default_domain_configs(total_capital_usd)
        self._exposures: Dict[str, VenueExposure] = {}  # venue -> exposure
        self._halted_domains: Dict[str, str] = {}  # domain -> reason
        self._proposal_log: List[dict] = []

    # ── Exposure tracking ────────────────────────────────────────────

    def __init_lock__(self):
        """Initialize the exposure lock. Called from __post_init__ or lazily."""
        if not hasattr(self, '_exposure_lock'):
            self._exposure_lock = threading.Lock()

    @property
    def _lock(self) -> threading.Lock:
        """Lazy-init lock for thread safety (T-014)."""
        if not hasattr(self, '_exposure_lock'):
            self._exposure_lock = threading.Lock()
        return self._exposure_lock

    def _build_default_domain_configs(
        self, 
        total_capital_usd: Decimal,
        allocation_pcts: Optional[Dict[TradeDomain, Decimal]] = None,
        daily_loss_pcts: Optional[Dict[TradeDomain, Decimal]] = None,
        single_order_pcts: Optional[Dict[TradeDomain, Decimal]] = None,
    ) -> Dict[TradeDomain, DomainRiskConfig]:
        """
        Build domain risk configs DYNAMICALLY from actual capital.
        
        CRITICAL: Replaces hardcoded $5K/$25K/$20K/$10K defaults with bankroll-derived values.
        All percentages remain the same, but absolute USD values now scale with actual capital.
        
        Args:
            total_capital_usd: Total capital in USD
            allocation_pcts: Optional custom allocation percentages per domain
            daily_loss_pcts: Optional custom daily loss percentages per domain (as % of domain allocation)
            single_order_pcts: Optional custom single order percentages per domain (as % of domain allocation)
        
        Returns:
            Dictionary of DomainRiskConfig per domain
        """
        # Domain allocation percentages (configurable with defaults)
        allocations = allocation_pcts or {
            TradeDomain.PREDICTION: Decimal("0.10"),   # 10% of capital
            TradeDomain.CRYPTO: Decimal("0.50"),       # 50% of capital
            TradeDomain.EQUITY: Decimal("0.40"),       # 40% of capital
            TradeDomain.MACRO: Decimal("0.20"),        # 20% of capital
        }
        
        # Daily loss as % of domain allocation (configurable with defaults)
        daily_loss_pcts = daily_loss_pcts or {
            TradeDomain.PREDICTION: Decimal("0.05"),   # 5% of domain allocation
            TradeDomain.CRYPTO: Decimal("0.04"),         # 4% of domain allocation
            TradeDomain.EQUITY: Decimal("0.025"),        # 2.5% of domain allocation
            TradeDomain.MACRO: Decimal("0.03"),          # 3% of domain allocation
        }
        
        # Single order as % of domain allocation (configurable with defaults)
        single_order_pcts = single_order_pcts or {
            TradeDomain.PREDICTION: Decimal("0.10"),   # 10% of domain allocation per order
            TradeDomain.CRYPTO: Decimal("0.20"),       # 20% of domain allocation per order
            TradeDomain.EQUITY: Decimal("0.10"),       # 10% of domain allocation per order
            TradeDomain.MACRO: Decimal("0.10"),        # 10% of domain allocation per order
        }
        
        configs = {}
        for domain in TradeDomain:
            allocation_pct = allocations.get(domain, Decimal("0.10"))
            domain_capital = total_capital_usd * allocation_pct
            
            configs[domain] = DomainRiskConfig(
                domain=domain,
                max_allocation_pct=allocation_pct,
                max_notional_usd=domain_capital,  # 100% of domain allocation
                max_daily_loss_usd=domain_capital * daily_loss_pcts.get(domain, Decimal("0.05")),
                max_positions=50 if domain != TradeDomain.PREDICTION else 20,
                max_single_order_usd=domain_capital * single_order_pcts.get(domain, Decimal("0.10")),
                enabled=True,
            )
            logger.info(
                "[RISK_MANAGER] Domain %s configured: max_notional=$%s, max_daily_loss=$%s, max_single_order=$%s",
                domain.value, configs[domain].max_notional_usd, 
                configs[domain].max_daily_loss_usd, configs[domain].max_single_order_usd
            )
        
        return configs

    def _get_exposure(self, venue: str, domain: str) -> VenueExposure:
        # Must be called under self._lock
        if venue not in self._exposures:
            self._exposures[venue] = VenueExposure(venue=venue, domain=domain)
        return self._exposures[venue]

    def record_fill(
        self,
        venue: str,
        domain: str,
        notional_usd: Decimal,
        fee_usd: Decimal = Decimal("0"),
    ) -> None:
        with self._lock:
            exp = self._get_exposure(venue, domain)
            exp.notional_usd += notional_usd
            exp.position_count += 1
            exp.daily_trades += 1

    def record_close(
        self,
        venue: str,
        domain: str,
        notional_usd: Decimal,
        pnl_usd: Decimal,
    ) -> None:
        with self._lock:
            exp = self._get_exposure(venue, domain)
            exp.notional_usd = max(Decimal("0"), exp.notional_usd - notional_usd)
            exp.realized_pnl_usd += pnl_usd
            exp.position_count = max(0, exp.position_count - 1)
            if pnl_usd < Decimal("0"):
                exp.daily_loss_usd += abs(pnl_usd)

    def update_unrealized(self, venue: str, unrealized_pnl_usd: Decimal) -> None:
        with self._lock:
            if venue in self._exposures:
                self._exposures[venue].unrealized_pnl_usd = unrealized_pnl_usd

    # ── Domain aggregation ───────────────────────────────────────────

    def domain_notional(self, domain: str) -> Decimal:
        return sum(
            (e.notional_usd for e in self._exposures.values() if e.domain == domain),
            Decimal("0"),
        )

    def domain_daily_loss(self, domain: str) -> Decimal:
        return sum(
            (e.daily_loss_usd for e in self._exposures.values() if e.domain == domain),
            Decimal("0"),
        )

    def domain_positions(self, domain: str) -> int:
        return sum(
            e.position_count for e in self._exposures.values() if e.domain == domain
        )

    def portfolio_notional(self) -> Decimal:
        return sum((e.notional_usd for e in self._exposures.values()), Decimal("0"))

    # ── Kill switch per domain ───────────────────────────────────────

    def halt_domain(self, domain: str, reason: str) -> None:
        self._halted_domains[domain] = reason
        logger.warning(f"Domain {domain} halted: {reason}")

    def resume_domain(self, domain: str) -> None:
        self._halted_domains.pop(domain, None)
        logger.info(f"Domain {domain} resumed")

    def is_domain_halted(self, domain: str) -> bool:
        return domain in self._halted_domains

    # ── Risk check ───────────────────────────────────────────────────

    def check_proposal(
        self,
        proposal: TradeProposal,
        risk_context: Optional["RiskContext"] = None,
    ) -> RiskCheckResult:
        """Run all risk checks on a proposal.  Returns RiskCheckResult.

        If *risk_context* is supplied, the order notional is scaled down by
        ``risk_context.size_scale_factor`` before limit checks.  This allows
        system-level stress (poor CQI, drawdown, high exposure) to reduce
        position sizing automatically.
        """
        domain = proposal.domain
        venue = proposal.venue
        domain_str = domain.value if isinstance(domain, TradeDomain) else str(domain)

        # 0. Domain halted?
        if self.is_domain_halted(domain_str):
            return RiskCheckResult(
                approved=False,
                reason=f"Domain {domain_str} is halted: {self._halted_domains[domain_str]}",
                domain=domain_str, venue=venue,
            )

        cfg = self._domain_configs.get(domain)
        if not cfg:
            return RiskCheckResult(
                approved=False,
                reason=f"No risk config for domain {domain_str}.",
                domain=domain_str, venue=venue,
            )

        # 1. Domain enabled?
        if not cfg.enabled:
            return RiskCheckResult(
                approved=False,
                reason=f"Domain {domain_str} is disabled in risk config.",
                domain=domain_str, venue=venue,
            )

        # Compute order notional
        order_notional = Decimal("0")
        if proposal.notional_usd:
            order_notional = proposal.notional_usd
        elif proposal.price and proposal.qty:
            order_notional = (proposal.price * proposal.qty).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
        elif proposal.qty:
            order_notional = proposal.qty  # fallback: treat qty as notional

        # Apply RiskContext size scaling (system-level stress reduction)
        if risk_context is not None and risk_context.size_scale_factor < 1.0:
            scaled = (order_notional * Decimal(str(risk_context.size_scale_factor))).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            if scaled <= 0:
                return RiskCheckResult(
                    approved=False,
                    reason=f"RiskContext size_scale_factor={risk_context.size_scale_factor:.2f} "
                           f"reduced notional to $0 (system stress).",
                    domain=domain_str, venue=venue,
                )
            order_notional = scaled

        # Apply liquidity_tier scale: tier-1=100%, tier-2=75%, tier-3=50%
        if domain == TradeDomain.CRYPTO and proposal.instrument_id:
            tier = _get_liquidity_tier(proposal.instrument_id)
            tier_scale = _LIQUIDITY_TIER_SCALE.get(tier, Decimal("0.50"))
            if tier_scale < Decimal("1.00"):
                order_notional = (order_notional * tier_scale).quantize(
                    Decimal("0.01"), ROUND_HALF_UP
                )
                logger.debug(
                    "liquidity_tier=%d scale=%.2f applied to %s: notional=$%.2f",
                    tier, float(tier_scale), proposal.instrument_id, float(order_notional),
                )

        # 2. Single order size
        if order_notional > cfg.max_single_order_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Order notional ${order_notional} exceeds domain max ${cfg.max_single_order_usd}.",
                domain=domain_str, venue=venue,
            )

        # 3. Domain notional limit
        current_domain = self.domain_notional(domain_str)
        if current_domain + order_notional > cfg.max_notional_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Domain {domain_str} notional ${current_domain + order_notional} "
                       f"would exceed max ${cfg.max_notional_usd}.",
                domain=domain_str, venue=venue,
            )

        # 4. Domain daily loss
        daily_loss = self.domain_daily_loss(domain_str)
        if daily_loss >= cfg.max_daily_loss_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Domain {domain_str} daily loss ${daily_loss} "
                       f"exceeds max ${cfg.max_daily_loss_usd}.",
                domain=domain_str, venue=venue,
            )

        # 5. Domain position count
        pos_count = self.domain_positions(domain_str)
        if pos_count >= cfg.max_positions:
            return RiskCheckResult(
                approved=False,
                reason=f"Domain {domain_str} has {pos_count} positions, max is {cfg.max_positions}.",
                domain=domain_str, venue=venue,
            )

        # 6. Portfolio-wide notional
        total = self.portfolio_notional()
        if total + order_notional > self.max_portfolio_notional_usd:
            return RiskCheckResult(
                approved=False,
                reason=f"Portfolio notional ${total + order_notional} "
                       f"would exceed max ${self.max_portfolio_notional_usd}.",
                domain=domain_str, venue=venue,
            )

        # 7. Capital allocation %
        if self.total_capital_usd > Decimal("0"):
            domain_pct = (current_domain + order_notional) / self.total_capital_usd
            if domain_pct > cfg.max_allocation_pct:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Domain {domain_str} allocation {domain_pct:.1%} "
                           f"would exceed max {cfg.max_allocation_pct:.1%}.",
                    domain=domain_str, venue=venue,
                )

        return RiskCheckResult(
            approved=True,
            reason="All global risk checks passed.",
            domain=domain_str, venue=venue,
        )

    # ── Capital routing ──────────────────────────────────────────────

    def available_capital(self, domain: TradeDomain) -> Decimal:
        """How much capital is available for a domain given current exposures."""
        cfg = self._domain_configs.get(domain)
        if not cfg:
            return Decimal("0")

        max_by_alloc = self.total_capital_usd * cfg.max_allocation_pct
        max_by_limit = cfg.max_notional_usd
        cap = min(max_by_alloc, max_by_limit)
        current = self.domain_notional(domain.value)
        return max(Decimal("0"), cap - current)

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        domain_summaries = {}
        for domain in TradeDomain:
            d = domain.value
            cfg = self._domain_configs.get(domain)
            domain_summaries[d] = {
                "notional_usd": str(self.domain_notional(d)),
                "daily_loss_usd": str(self.domain_daily_loss(d)),
                "positions": self.domain_positions(d),
                "available_capital_usd": str(self.available_capital(domain)),
                "halted": self.is_domain_halted(d),
                "max_notional_usd": str(cfg.max_notional_usd) if cfg else "N/A",
                "max_allocation_pct": str(cfg.max_allocation_pct) if cfg else "N/A",
            }

        return {
            "total_capital_usd": str(self.total_capital_usd),
            "portfolio_notional_usd": str(self.portfolio_notional()),
            "max_portfolio_notional_usd": str(self.max_portfolio_notional_usd),
            "halted_domains": dict(self._halted_domains),
            "domains": domain_summaries,
            "venue_exposures": [
                {
                    "venue": e.venue,
                    "domain": e.domain,
                    "notional_usd": str(e.notional_usd),
                    "unrealized_pnl_usd": str(e.unrealized_pnl_usd),
                    "realized_pnl_usd": str(e.realized_pnl_usd),
                    "positions": e.position_count,
                    "daily_trades": e.daily_trades,
                }
                for e in self._exposures.values()
            ],
        }


# Module-level singleton
_manager: Optional[GlobalRiskManager] = None
_manager_lock = threading.Lock()


def get_global_risk_manager() -> GlobalRiskManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = GlobalRiskManager()
    return _manager

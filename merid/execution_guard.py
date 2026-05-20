"""§H3 Execution Guard — CQI-based throttle, per-domain caps, kill switch.

Sits between the loop's plan approval and actual venue submission.
Every trade must pass through `guard.pre_trade_check(plan)` before execution.

Safety layers (checked in order):
  1. Global kill switch — blocks ALL execution
  2. Per-domain kill switch — blocks a single domain
  3. CQI throttle — shrinks or blocks trades when quality degrades
  4. Per-domain daily caps — max notional per domain per day
  5. Cooldown — min time between executions

Usage:
    guard = get_execution_guard()
    verdict = guard.pre_trade_check(plan, domain="crypto")
    if verdict.allowed:
        execute(plan, size=verdict.adjusted_size_usd)
"""

from __future__ import annotations

import threading
import json
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger


def _get_risk_kill_switch_path() -> str:
    """Return the canonical kill-switch file path.

    Uses MERID_RISK_KS_FILE env var if set, otherwise the same resolver as
    ``merid.risk.kill_switches._get_kill_switch_path`` (lazy, test-friendly).
    """
    env_override = os.environ.get("MERID_RISK_KS_FILE", "")
    if env_override:
        return env_override
    from merid.risk.kill_switches import _get_kill_switch_path

    return str(_get_kill_switch_path())


logger = get_logger("merid.execution_guard")


# ── Verdict ───────────────────────────────────────────────────────────

@dataclass
class TradeVerdict:
    """Result of a pre-trade safety check."""
    allowed: bool
    reason: str
    original_size_usd: float = 0.0
    adjusted_size_usd: float = 0.0
    throttle_pct: float = 1.0       # 1.0 = full size, 0.5 = halved, 0.0 = blocked
    cqi_score: float = 0.0
    domain: str = ""
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "original_size_usd": self.original_size_usd,
            "adjusted_size_usd": round(self.adjusted_size_usd, 2),
            "throttle_pct": round(self.throttle_pct, 4),
            "cqi_score": round(self.cqi_score, 4),
            "domain": self.domain,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
        }


# ── Domain caps ───────────────────────────────────────────────────────

@dataclass
class DomainCap:
    """Per-domain execution limits.
    
    PRODUCTION SAFETY: Defaults are 0. Limits must be configured explicitly
    from live bankroll - never use hardcoded values.
    """
    domain: str
    max_daily_notional_usd: float = 0.0  # No default - configure from bankroll
    max_single_trade_usd: float = 0.0  # No default - configure from bankroll
    max_daily_trades: int = 50
    enabled: bool = True
    kill_switch: bool = False

    # Runtime counters (reset daily)
    daily_notional_usd: float = 0.0
    daily_trade_count: int = 0
    last_reset_date: str = ""

    def reset_if_new_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.last_reset_date:
            self.daily_notional_usd = 0.0
            self.daily_trade_count = 0
            self.last_reset_date = today

    def record_trade(self, notional_usd: float):
        self.reset_if_new_day()
        self.daily_notional_usd += notional_usd
        self.daily_trade_count += 1

    def remaining_notional(self) -> float:
        self.reset_if_new_day()
        return max(0, self.max_daily_notional_usd - self.daily_notional_usd)

    def to_dict(self) -> Dict[str, Any]:
        self.reset_if_new_day()
        return {
            "domain": self.domain,
            "enabled": self.enabled,
            "kill_switch": self.kill_switch,
            "max_daily_notional_usd": self.max_daily_notional_usd,
            "daily_notional_usd": round(self.daily_notional_usd, 2),
            "remaining_notional_usd": round(self.remaining_notional(), 2),
            "daily_trade_count": self.daily_trade_count,
            "max_daily_trades": self.max_daily_trades,
        }


# ── Per-venue exposure caps ──────────────────────────────────────────

@dataclass
class VenueExposureCap:
    """Per-venue maximum total exposure (sum of open position notional)."""
    venue: str
    max_exposure_usd: float = 25000.0
    current_exposure_usd: float = 0.0

    def would_breach(self, additional_usd: float) -> bool:
        return (self.current_exposure_usd + additional_usd) > self.max_exposure_usd

    def remaining(self) -> float:
        return max(0.0, self.max_exposure_usd - self.current_exposure_usd)

    def record(self, notional_usd: float):
        self.current_exposure_usd += notional_usd

    def release(self, notional_usd: float):
        self.current_exposure_usd = max(0.0, self.current_exposure_usd - notional_usd)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "max_exposure_usd": self.max_exposure_usd,
            "current_exposure_usd": round(self.current_exposure_usd, 2),
            "remaining_usd": round(self.remaining(), 2),
            "utilization_pct": round(self.current_exposure_usd / self.max_exposure_usd * 100, 1) if self.max_exposure_usd > 0 else 0.0,
        }


# ── Per-asset exposure caps ───────────────────────────────────────────

@dataclass
class AssetCap:
    """Per-asset daily notional limits for crypto trading.
    
    PRODUCTION SAFETY: Defaults are 0. Limits must be configured explicitly
    from live bankroll - never use hardcoded values.
    """
    asset: str
    max_daily_notional_usd: float = 0.0  # No default - configure from bankroll
    max_single_trade_usd: float = 0.0  # No default - configure from bankroll

    # Runtime counters (reset daily)
    daily_notional_usd: float = 0.0
    last_reset_date: str = ""

    def reset_if_new_day(self) -> None:
        """Reset daily counter if it's a new day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self.last_reset_date:
            self.daily_notional_usd = 0.0
            self.last_reset_date = today

    def record_trade(self, notional_usd: float) -> None:
        """Record a trade against this asset's daily cap."""
        self.reset_if_new_day()
        self.daily_notional_usd += notional_usd

    def remaining_notional(self) -> float:
        """Calculate remaining daily notional capacity."""
        self.reset_if_new_day()
        return max(0.0, self.max_daily_notional_usd - self.daily_notional_usd)

    def utilization_pct(self) -> float:
        """Calculate percentage of daily cap used."""
        if self.max_daily_notional_usd <= 0:
            return 0.0
        self.reset_if_new_day()
        return round(self.daily_notional_usd / self.max_daily_notional_usd * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API response."""
        self.reset_if_new_day()
        return {
            "asset": self.asset,
            "max_daily_notional_usd": self.max_daily_notional_usd,
            "max_single_trade_usd": self.max_single_trade_usd,
            "daily_notional_usd": round(self.daily_notional_usd, 2),
            "remaining_notional_usd": round(self.remaining_notional(), 2),
            "utilization_pct": self.utilization_pct(),
            "last_reset_date": self.last_reset_date,
        }


# ── CQI Throttle config ──────────────────────────────────────────────

@dataclass
class CQIThrottleConfig:
    """CQI-based execution throttling thresholds."""
    full_execution_above: float = 0.65   # CQI > 0.65: trade at full size
    throttle_start: float = 0.65         # CQI < 0.65: start shrinking
    block_below: float = 0.35            # CQI < 0.35: block all trades
    min_throttle_pct: float = 0.25       # Never shrink below 25% of original size

    def compute_throttle(self, cqi: float) -> float:
        """Returns a throttle factor (0.0 to 1.0) based on CQI."""
        if cqi >= self.full_execution_above:
            return 1.0
        if cqi <= self.block_below:
            return 0.0
        # Linear interpolation between block_below and full_execution_above
        range_width = self.full_execution_above - self.block_below
        if range_width <= 0:
            return 1.0
        raw = (cqi - self.block_below) / range_width
        return max(self.min_throttle_pct, raw)


# ── Execution Guard ──────────────────────────────────────────────────

class ExecutionGuard:
    """Central safety gate for all trade execution.

    The MeridLoop calls `pre_trade_check()` before every trade.
    The UI calls `activate_kill_switch()` / `deactivate_kill_switch()`.
    """

    def __init__(self):
        self._global_kill_switch = False
        self._global_kill_reason = ""
        self._cqi_config = CQIThrottleConfig()

        # BUG-9: Load domain and venue caps from merid.settings so risk limit
        # changes propagate via env var without a redeploy, and so there is a
        # single source of truth shared with PredictionRiskConfig.
        try:
            from merid.settings import settings as _s
            _pm_total = _s.MERID_PM_MAX_TOTAL_NOTIONAL
            _pm_per_market = _s.MERID_PM_MAX_NOTIONAL_PER_MARKET
            _pm_daily_loss = _s.MERID_PM_MAX_DAILY_LOSS
            _crypto_total = _s.MERID_CRYPTO_MAX_NOTIONAL_USD
            _crypto_per = _s.MERID_MAX_POSITION_SIZE_USD
            _eq_venue_cap = _s.MERID_EQUITY_MAX_NOTIONAL_USD
        except Exception:
            _pm_total = 5000.0
            _pm_per_market = 500.0
            _pm_daily_loss = 250.0
            _crypto_total = 25000.0
            _crypto_per = 1000.0
            _eq_venue_cap = 20000.0

        self._domain_caps: Dict[str, DomainCap] = {
            "prediction": DomainCap(domain="prediction", max_daily_notional_usd=_pm_total, max_single_trade_usd=_pm_per_market),
            "crypto": DomainCap(domain="crypto", max_daily_notional_usd=_crypto_total, max_single_trade_usd=_crypto_per),
        }
        # Separate caps per venue so Alpaca equity flow never shares Kalshi PM limits.
        self._venue_caps: Dict[str, VenueExposureCap] = {
            "kalshi": VenueExposureCap(venue="kalshi", max_exposure_usd=_pm_total),
            "alpaca": VenueExposureCap(venue="alpaca", max_exposure_usd=_eq_venue_cap),
        }
        self._asset_caps: Dict[str, AssetCap] = {}  # Per-asset caps, populated on demand
        self._last_cqi: Dict[str, float] = {}
        self._cooldown_seconds = 5.0
        self._last_execution_at = 0.0
        self._trade_log: List[Dict[str, Any]] = []

        self._load_persisted_kill_switch()

        # Promotion enforcement: when True, live trades are blocked for
        # domains that are not eligible in the latest promotion report.
        self.enforce_promotion = True
        self._promotion_eligible_domains: Optional[set] = None
        self._promotion_blocked_agents: Optional[set] = None
        self._promotion_report_ts: float = 0.0
        # Maximum age (seconds) of a promotion report before it is considered
        # stale.  In live mode a stale report causes a fail-closed block.
        self._promotion_report_max_age_s: float = 600.0
        # BUG-9 fix: time at which this guard was instantiated (for grace window).
        self._init_ts: float = time.time()
        # Grace window (seconds) after startup during which paper-mode trading is
        # allowed even when no promotion report has loaded yet.  After this window
        # expires, an absent report causes a fail-closed block even in paper mode.
        self._promotion_report_grace_s: float = float(
            __import__("os").environ.get("MERID_PROMOTION_GRACE_S", "300")
        )

        # C3/RISK-10: lock prevents concurrent refresh calls from piling up.
        self._promotion_refresh_lock = threading.Lock()

        # BUG-5 fix: Load promotion report, but do NOT block startup with
        # the 100s+ report generation.  Fire a background thread so the guard
        # is populated before the first trade, but the event loop isn't blocked.
        def _bg_promo():
            try:
                self.sync_promotion_report()
            except Exception as e:
                logger.debug(f"Promotion report sync failed: {e}")
        threading.Thread(target=_bg_promo, daemon=True, name="guard-promo-init").start()

    # ── Kill switch ───────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "manual"):
        """Block ALL execution immediately."""
        self._global_kill_switch = True
        self._global_kill_reason = reason
        self._persist_kill_switch()
        logger.warning(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Re-enable execution."""
        self._global_kill_switch = False
        self._global_kill_reason = ""
        self._persist_kill_switch()
        logger.info("Kill switch deactivated")

    def _persist_kill_switch(self):
        """Write kill switch state to disk so it survives restarts."""
        try:
            ks_path = Path(_get_risk_kill_switch_path())
            ks_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "active": self._global_kill_switch,
                "reason": self._global_kill_reason,
                "activated_at": time.time() if self._global_kill_switch else None,
            }
            ks_path.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            logger.error(f"Failed to persist kill switch state: {exc}")

    def _load_persisted_kill_switch(self):
        """Reload kill switch state from disk on startup.

        M1: Also checks the RiskController persistence file
        (``data/risk_kill_switch.json``) so a kill-switch triggered through
        ``KalshiRiskManager`` or ``RiskController.emergency_stop()`` is
        honoured here on the next restart, not just within its own module.
        """
        # Primary: ExecutionGuard's own file
        try:
            ks_path = Path(_get_risk_kill_switch_path())
            if ks_path.exists():
                data = json.loads(ks_path.read_text(encoding="utf-8"))
                if data.get("active"):
                    self._global_kill_switch = True
                    self._global_kill_reason = data.get("reason", "persisted")
                    logger.warning(
                        f"Kill switch restored from disk: {self._global_kill_reason}"
                    )
                    return  # Own file wins — no need to check secondary
        except Exception as exc:
            logger.error(f"Failed to load persisted kill switch: {exc}")

        # Secondary: M1 — also check RiskController's file via canonical path helper.
        # Both modules now share the same path (_get_risk_kill_switch_path()), but
        # the RiskController schema uses {"state": "triggered"} / {"kill_switch_active": true}
        # while ExecutionGuard uses {"active": true}.  Read here to honour whichever
        # field was written by a RiskController-triggered kill on this restart.
        try:
            _rc_file = Path(_get_risk_kill_switch_path())
            if _rc_file.exists():
                _rc_data = json.loads(_rc_file.read_text())
                if _rc_data.get("state") == "triggered" or _rc_data.get("kill_switch_active"):
                    _rc_reason = _rc_data.get("reason") or _rc_data.get("kill_details") or "risk_controller_persisted"
                    self._global_kill_switch = True
                    self._global_kill_reason = f"risk_controller: {_rc_reason}"
                    logger.warning(
                        "Kill switch restored from RiskController persistence: %s",
                        _rc_reason,
                    )
        except Exception as exc:
            logger.debug("Failed to load RiskController kill switch file (non-fatal): %s", exc)

    def activate_domain_kill_switch(self, domain: str, reason: str = "manual"):
        cap = self._domain_caps.get(domain)
        if cap:
            cap.kill_switch = True
            logger.warning(f"Domain kill switch activated for {domain}: {reason}")

    def deactivate_domain_kill_switch(self, domain: str):
        cap = self._domain_caps.get(domain)
        if cap:
            cap.kill_switch = False
            logger.info(f"Domain kill switch deactivated for {domain}")

    @property
    def kill_switch_active(self) -> bool:
        return self._global_kill_switch

    # ── Promotion enforcement ────────────────────────────────────────

    def sync_promotion_report(self):
        """Pull eligible domains/agents from the cached promotion report.

        Called periodically by the loop or on-demand.  Does NOT regenerate
        the report — it reads whatever is cached.
        """
        try:
            from merid.promotion_report import get_cached_promotion_report
            report = get_cached_promotion_report(gauntlet_cycles=5)
            self._promotion_eligible_domains = set(report.eligible_domains)
            self._promotion_blocked_agents = set(report.blocked_agents)
            self._promotion_report_ts = report.timestamp
            logger.info(
                f"Promotion sync: {len(self._promotion_eligible_domains)} eligible domains, "
                f"{len(self._promotion_blocked_agents)} blocked agents"
            )
        except Exception as exc:
            logger.warning(f"Promotion sync failed (enforcement unchanged): {exc}")

    def _refresh_promotion_report_bg(self) -> None:
        """Trigger a non-blocking background refresh of the promotion report.

        C3/RISK-10: Called from is_domain_promoted() when the cached report is
        stale.  Uses trylock so only one refresh thread runs at a time — all
        concurrent callers get the existing cached value immediately.
        """
        if not self._promotion_refresh_lock.acquire(blocking=False):
            return  # Another thread is already refreshing — skip
        def _do_refresh():
            try:
                self.sync_promotion_report()
            finally:
                self._promotion_refresh_lock.release()
        t = threading.Thread(target=_do_refresh, daemon=True, name="promotion-refresh")
        t.start()

    def is_domain_promoted(self, domain: str) -> bool:
        """Check if a domain is eligible per the latest promotion report.

        BUG-5 fix: If no report has ever been loaded, or the report is stale
        (older than _promotion_report_max_age_s) and we are in live mode,
        fail-closed so un-gauntleted agents cannot trade live capital.

        C3/RISK-10: When the report is stale the caller immediately gets the
        cached value (stale-while-revalidate) and a background thread fires to
        refresh it.  This prevents sync_promotion_report() from blocking the
        hot pre_trade_check() path.
        """
        report_missing = self._promotion_eligible_domains is None
        report_stale = (
            self._promotion_report_ts > 0
            and (time.time() - self._promotion_report_ts) > self._promotion_report_max_age_s
        )

        if report_stale:
            # Trigger background refresh but do NOT block — return cached value now.
            self._refresh_promotion_report_bg()

        if report_missing:
            # No cached data at all: fire a synchronous refresh once then decide.
            self.sync_promotion_report()
            if self._promotion_eligible_domains is None:
                is_live = False
                try:
                    from trading.mode_controller import get_trading_mode_controller
                    is_live = get_trading_mode_controller().is_live
                except Exception as e:
                    logger.debug(f"Trading mode controller unavailable: {e}")
                if is_live:
                    logger.warning(
                        "is_domain_promoted: promotion report unavailable — "
                        "blocking domain '%s' in live mode (fail-closed)", domain
                    )
                    return False
                elapsed_since_start = time.time() - self._init_ts
                if elapsed_since_start <= self._promotion_report_grace_s:
                    return True  # Still within grace window — allow paper trading
                logger.warning(
                    "is_domain_promoted: promotion report missing after grace window "
                    "(%.0fs) — blocking domain '%s' in paper mode (fail-closed post-grace)",
                    self._promotion_report_grace_s, domain,
                )
                return False

        return domain in self._promotion_eligible_domains

    def is_agent_promoted(self, agent_id: str) -> bool:
        """Check if an agent is promoted per the latest promotion report.

        Fail-open only within the initial grace window (same policy as
        is_domain_promoted).  After the grace window, an absent report
        means no agents are considered promoted.
        """
        if self._promotion_blocked_agents is None:
            elapsed_since_start = time.time() - self._init_ts
            if elapsed_since_start <= self._promotion_report_grace_s:
                return True  # Grace window — allow
            return False  # Post-grace, no report → fail-closed
        return agent_id not in self._promotion_blocked_agents

    # ── CQI updates ───────────────────────────────────────────────────

    def update_cqi(self, domain: str, cqi_score: float):
        """Called by the loop after CQI computation to update throttle state."""
        self._last_cqi[domain] = cqi_score
        if cqi_score < self._cqi_config.block_below:
            logger.warning(
                f"CQI for {domain} dropped to {cqi_score:.3f} — "
                f"execution BLOCKED (threshold: {self._cqi_config.block_below})"
            )

    def get_cqi(self, domain: str) -> float:
        # C4/RISK-06: warn if this domain has never had a CQI value pushed so
        # operators know the throttle is running on a stale default, not a
        # real measurement.
        if domain not in self._last_cqi:
            logger.warning(
                "[execution_guard] get_cqi('%s') called but no CQI has ever been pushed "
                "for this domain — returning default 0.5. Check that update_cqi() is "
                "wired in the loop for this domain.", domain,
            )
        return self._last_cqi.get(domain, 0.5)  # Default neutral

    # ── Pre-trade check ───────────────────────────────────────────────

    def get_venue_cap(self, venue: str) -> Optional[VenueExposureCap]:
        return self._venue_caps.get(venue)

    def set_venue_cap(self, venue: str, max_exposure_usd: float):
        if venue in self._venue_caps:
            self._venue_caps[venue].max_exposure_usd = max_exposure_usd
        else:
            self._venue_caps[venue] = VenueExposureCap(venue=venue, max_exposure_usd=max_exposure_usd)

    def sync_venue_exposure(self, venue: str, current_exposure_usd: float):
        """Called by the loop/reconciliation to sync actual venue exposure."""
        if venue in self._venue_caps:
            self._venue_caps[venue].current_exposure_usd = current_exposure_usd
        else:
            self._venue_caps[venue] = VenueExposureCap(venue=venue, current_exposure_usd=current_exposure_usd)

    # ── Per-asset cap methods ───────────────────────────────────────────

    def set_asset_cap(self, asset: str, max_daily_notional_usd: float, max_single_trade_usd: float):
        """Set or update per-asset risk cap (case-normalized)."""
        asset_upper = asset.upper()
        self._asset_caps[asset_upper] = AssetCap(
            asset=asset_upper,
            max_daily_notional_usd=max_daily_notional_usd,
            max_single_trade_usd=max_single_trade_usd,
        )
        logger.info(f"Asset cap set: {asset_upper} daily=${max_daily_notional_usd}, single=${max_single_trade_usd}")

    def get_asset_cap(self, asset: str) -> Optional[AssetCap]:
        """Get cap for a specific asset (case-normalized)."""
        return self._asset_caps.get(asset.upper())

    def get_asset_cap_status(self) -> Dict[str, Any]:
        """Return full utilization snapshot for all asset caps."""
        return {
            "assets": {k: v.to_dict() for k, v in self._asset_caps.items()},
            "total_assets": len(self._asset_caps),
            "assets_at_limit": [
                k for k, v in self._asset_caps.items()
                if v.utilization_pct() >= 95
            ],
        }

    def apply_asset_caps_from_config(self, risk_config: Any) -> None:
        """Populate asset caps from existing risk config (source of truth).

        Args:
            risk_config: Object with asset_caps attribute or get_dynamic_asset_caps() method
                        containing per-asset max_daily_notional_usd and max_single_trade_usd.

        Example:
            guard.apply_asset_caps_from_config(settings.risk)
            guard.apply_asset_caps_from_config(settings)  # New dynamic method
        """
        try:
            asset_caps = None

            # Handle new dynamic method (preferred)
            if hasattr(risk_config, 'get_dynamic_asset_caps') and callable(risk_config.get_dynamic_asset_caps):
                asset_caps = risk_config.get_dynamic_asset_caps()
                logger.debug("Using dynamic asset caps from get_dynamic_asset_caps()")
            # Handle dict-style config
            elif hasattr(risk_config, 'get') and callable(risk_config.get):
                asset_caps = risk_config.get('asset_caps', {})
            # Handle object-style config with asset_caps attribute
            elif hasattr(risk_config, 'asset_caps'):
                asset_caps = risk_config.asset_caps

            if asset_caps is None:
                logger.warning("risk_config has no asset_caps attribute or get_dynamic_asset_caps method")
                return

            for asset, cfg in asset_caps.items():
                asset_upper = asset.upper()
                # Support both dict and dataclass-style configs
                daily = cfg.get('max_daily_notional_usd') if isinstance(cfg, dict) else getattr(cfg, 'max_daily_notional_usd', None)
                single = cfg.get('max_single_trade_usd') if isinstance(cfg, dict) else getattr(cfg, 'max_single_trade_usd', None)

                if daily is not None and single is not None:
                    self.set_asset_cap(asset_upper, float(daily), float(single))
                    logger.debug(f"Asset cap synced from config: {asset_upper}")

            logger.info(f"Synced {len(asset_caps)} asset caps from config")

        except Exception as exc:
            logger.error(f"Failed to apply asset caps from config: {exc}")

    def ensure_core_assets_caps(self, required_assets: Optional[List[str]] = None) -> None:
        """Fail fast if core assets are missing from caps.

        Args:
            required_assets: List of required asset symbols. Defaults to
                           ["BTC", "ETH", "SOL", "XRP", "DOGE"].

        Raises:
            RuntimeError: If any required asset has no configured cap.
        """
        if required_assets is None:
            required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

        missing = []
        for asset in required_assets:
            asset_upper = asset.upper()
            if asset_upper not in self._asset_caps:
                missing.append(asset_upper)

        if missing:
            msg = f"Core asset caps missing: {missing}. Trading blocked until configured."
            logger.critical(msg)
            # Activate kill switch to prevent trading without risk limits
            self.activate_kill_switch(reason=f"missing_asset_caps: {missing}")
            raise RuntimeError(msg)

        logger.info(f"All {len(required_assets)} core assets have configured caps")

    def pre_trade_check(
        self,
        plan_id: str,
        symbol: str,
        domain: str,
        size_usd: float,
        direction: str = "long",
        venue: str = "",
        order_group_id: str = "",
        order_contracts: int = 0,
        now: Optional[float] = None,
        agent_id: str = "",
        asset: str = "",
    ) -> TradeVerdict:
        """Run all safety checks before execution. Returns a TradeVerdict."""
        now = now or time.time()
        passed: List[str] = []
        failed: List[str] = []

        verdict = TradeVerdict(
            allowed=True,
            reason="all checks passed",
            original_size_usd=size_usd,
            adjusted_size_usd=size_usd,
            domain=domain,
        )

        # 0. Unified risk controller — covers daily-loss, error-threshold,
        #    consecutive-rejection, and position-limit kill switches.
        #    Must be checked before the local kill switch so that a
        #    risk_controller.emergency_stop() is always honoured here.
        try:
            from merid.risk.kill_switches import risk_controller as _rc
            if not _rc.can_trade():
                logger.warning(
                    "[EXECUTION-GUARD] can_trade DENIED by risk_controller: reason=%s domain=%s plan_id=%s",
                    _rc.get_kill_reason() or 'kill_switch_active', domain, plan_id
                )
                verdict.allowed = False
                verdict.reason = f"risk_controller: {_rc.get_kill_reason() or 'kill_switch_active'}"
                verdict.adjusted_size_usd = 0
                failed.append("risk_controller_kill")
                verdict.checks_passed = passed
                verdict.checks_failed = failed
                self._log_verdict(plan_id, verdict)
                return verdict
            passed.append("risk_controller_kill")
        except Exception as _rc_exc:
            logger.warning("[EXECUTION-GUARD] risk_controller check failed (fail-closed): %s", _rc_exc)
            verdict.allowed = False
            verdict.reason = f"risk_controller_unavailable: {_rc_exc}"
            verdict.adjusted_size_usd = 0
            failed.append("risk_controller_unavailable")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict

        # 1. Global kill switch
        if self._global_kill_switch:
            logger.warning(
                "[EXECUTION-GUARD] can_trade DENIED by global kill switch: reason=%s domain=%s plan_id=%s",
                self._global_kill_reason, domain, plan_id
            )
            verdict.allowed = False
            verdict.reason = f"global kill switch: {self._global_kill_reason}"
            verdict.adjusted_size_usd = 0
            failed.append("global_kill_switch")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("global_kill_switch")

        # 2. Per-domain kill switch
        cap = self._domain_caps.get(domain)
        if cap and cap.kill_switch:
            logger.warning(
                "[EXECUTION-GUARD] can_trade DENIED by domain kill switch: domain=%s plan_id=%s",
                domain, plan_id
            )
            verdict.allowed = False
            verdict.reason = f"domain kill switch active for {domain}"
            verdict.adjusted_size_usd = 0
            failed.append("domain_kill_switch")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("domain_kill_switch")

        # 3. Domain enabled
        if cap and not cap.enabled:
            logger.warning(
                "[EXECUTION-GUARD] can_trade DENIED by domain disabled: domain=%s plan_id=%s",
                domain, plan_id
            )
            verdict.allowed = False
            verdict.reason = f"domain {domain} is disabled"
            verdict.adjusted_size_usd = 0
            failed.append("domain_enabled")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("domain_enabled")

        # 3.5 Promotion eligibility (only enforced for live execution)
        is_live = False
        try:
            from trading.mode_controller import get_trading_mode_controller
            is_live = get_trading_mode_controller().is_live
        except Exception as exc:
            logger.debug("data_fetch_suppressed", error=str(exc))

        if self.enforce_promotion and is_live and not self.is_domain_promoted(domain):
            verdict.allowed = False
            verdict.reason = (
                f"domain {domain} not eligible for live execution "
                f"(promotion report rings not all passing)"
            )
            verdict.adjusted_size_usd = 0
            failed.append("promotion_eligibility")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("promotion_eligibility")

        # 3.6 Per-agent promotion check (live only) — blocks agents that failed gauntlet
        if self.enforce_promotion and is_live and agent_id and not self.is_agent_promoted(agent_id):
            verdict.allowed = False
            verdict.reason = (
                f"agent {agent_id} is not promotion-eligible for live execution "
                f"(blocked in latest promotion report)"
            )
            verdict.adjusted_size_usd = 0
            failed.append("agent_promotion_eligibility")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("agent_promotion_eligibility")

        # 4. CQI throttle
        cqi = self.get_cqi(domain)
        verdict.cqi_score = cqi
        throttle = self._cqi_config.compute_throttle(cqi)
        verdict.throttle_pct = throttle
        if throttle <= 0:
            verdict.allowed = False
            verdict.reason = f"CQI too low ({cqi:.3f} < {self._cqi_config.block_below})"
            verdict.adjusted_size_usd = 0
            failed.append("cqi_throttle")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        verdict.adjusted_size_usd = size_usd * throttle
        passed.append("cqi_throttle")

        # 4.5 Per-venue exposure cap
        if venue and venue in self._venue_caps:
            vcap = self._venue_caps[venue]
            if vcap.would_breach(verdict.adjusted_size_usd):
                remaining_venue = vcap.remaining()
                if remaining_venue <= 0:
                    verdict.allowed = False
                    verdict.reason = f"venue exposure cap exhausted for {venue}"
                    verdict.adjusted_size_usd = 0
                    failed.append("venue_exposure_cap")
                    verdict.checks_passed = passed
                    verdict.checks_failed = failed
                    self._log_verdict(plan_id, verdict)
                    return verdict
                else:
                    verdict.adjusted_size_usd = min(verdict.adjusted_size_usd, remaining_venue)
                    passed.append("venue_exposure_cap_clamped")
            else:
                passed.append("venue_exposure_cap")

        # 4.6 Per-asset daily cap (if asset specified)
        if asset:
            asset_upper = asset.upper()
            acap = self._asset_caps.get(asset_upper)
            if acap:
                acap.reset_if_new_day()
                remaining_asset = acap.remaining_notional()
                if verdict.adjusted_size_usd > remaining_asset:
                    if remaining_asset <= 0:
                        verdict.allowed = False
                        verdict.reason = f"daily asset notional cap exhausted for {asset_upper}"
                        verdict.adjusted_size_usd = 0
                        failed.append("asset_notional_cap")
                        verdict.checks_passed = passed
                        verdict.checks_failed = failed
                        self._log_verdict(plan_id, verdict)
                        return verdict
                    else:
                        verdict.adjusted_size_usd = min(verdict.adjusted_size_usd, remaining_asset)
                        passed.append("asset_notional_cap_clamped")
                else:
                    passed.append("asset_notional_cap")

                # Single trade ceiling per asset
                if verdict.adjusted_size_usd > acap.max_single_trade_usd:
                    verdict.adjusted_size_usd = acap.max_single_trade_usd
                    passed.append("asset_single_trade_cap_clamped")
                else:
                    passed.append("asset_single_trade_cap")

        # 5. Per-domain daily cap
        if cap:
            cap.reset_if_new_day()
            if cap.daily_trade_count >= cap.max_daily_trades:
                verdict.allowed = False
                verdict.reason = f"daily trade limit reached for {domain} ({cap.daily_trade_count}/{cap.max_daily_trades})"
                verdict.adjusted_size_usd = 0
                failed.append("daily_trade_count")
                verdict.checks_passed = passed
                verdict.checks_failed = failed
                self._log_verdict(plan_id, verdict)
                return verdict
            passed.append("daily_trade_count")

            remaining = cap.remaining_notional()
            if verdict.adjusted_size_usd > remaining:
                if remaining <= 0:
                    verdict.allowed = False
                    verdict.reason = f"daily notional cap exhausted for {domain}"
                    verdict.adjusted_size_usd = 0
                    failed.append("daily_notional_cap")
                else:
                    verdict.adjusted_size_usd = min(verdict.adjusted_size_usd, remaining)
                    passed.append("daily_notional_cap_clamped")
            else:
                passed.append("daily_notional_cap")

            if verdict.adjusted_size_usd > cap.max_single_trade_usd:
                verdict.adjusted_size_usd = cap.max_single_trade_usd
                passed.append("single_trade_cap_clamped")
            else:
                passed.append("single_trade_cap")

        # 6. Cooldown
        if now - self._last_execution_at < self._cooldown_seconds:
            verdict.allowed = False
            verdict.reason = f"cooldown ({self._cooldown_seconds}s between trades)"
            failed.append("cooldown")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("cooldown")

        # BUG-AA fix: Layer 7 order group check removed.
        # OrderGroupRiskManager has no singleton/shared cache — constructing it
        # with None produced an empty groups dict so get_group() always returned
        # None, permanently bypassing this check. Order group limits are already
        # enforced by order_router.py via its own OrderGroupRiskManager(client)
        # instance before placement, so this check was redundant and broken.

        verdict.checks_passed = passed
        verdict.checks_failed = failed
        self._log_verdict(plan_id, verdict)
        return verdict

    def record_execution(self, domain: str, notional_usd: float, asset: str = ""):
        """Called after a successful execution to update caps and cooldown."""
        self._last_execution_at = time.time()
        cap = self._domain_caps.get(domain)
        if cap:
            cap.record_trade(notional_usd)
        # Also record against asset cap if specified
        if asset:
            asset_upper = asset.upper()
            acap = self._asset_caps.get(asset_upper)
            if acap:
                acap.record_trade(notional_usd)

    # ── Logging ───────────────────────────────────────────────────────

    def _log_verdict(self, plan_id: str, verdict: TradeVerdict):
        entry = {
            "plan_id": plan_id,
            "ts": time.time(),
            **verdict.to_dict(),
        }
        self._trade_log.append(entry)
        # Keep last 1000 entries
        if len(self._trade_log) > 1000:
            self._trade_log = self._trade_log[-500:]

        log_fn = logger.info if verdict.allowed else logger.warning
        log_fn(
            f"TradeVerdict [{plan_id}] {'ALLOWED' if verdict.allowed else 'BLOCKED'}: "
            f"${verdict.original_size_usd:.0f}->${verdict.adjusted_size_usd:.0f} "
            f"throttle={verdict.throttle_pct:.0%} CQI={verdict.cqi_score:.3f} "
            f"reason={verdict.reason}"
        )

    # ── Status ────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        return {
            "global_kill_switch": self._global_kill_switch,
            "global_kill_reason": self._global_kill_reason,
            "cqi_throttle_config": {
                "full_above": self._cqi_config.full_execution_above,
                "block_below": self._cqi_config.block_below,
                "min_throttle": self._cqi_config.min_throttle_pct,
            },
            "last_cqi": {k: round(v, 4) for k, v in self._last_cqi.items()},
            "domain_caps": {k: v.to_dict() for k, v in self._domain_caps.items()},
            "venue_caps": {k: v.to_dict() for k, v in self._venue_caps.items()},
            "asset_caps": {k: v.to_dict() for k, v in self._asset_caps.items()},
            "cooldown_seconds": self._cooldown_seconds,
            "recent_verdicts": len(self._trade_log),
            "promotion_enforcement": {
                "enabled": self.enforce_promotion,
                "eligible_domains": sorted(self._promotion_eligible_domains) if self._promotion_eligible_domains else [],
                "blocked_agents": sorted(self._promotion_blocked_agents) if self._promotion_blocked_agents else [],
                "report_ts": self._promotion_report_ts,
                "sync_age_s": round(time.time() - self._promotion_report_ts, 1) if self._promotion_report_ts else None,
                "stale": (time.time() - self._promotion_report_ts > 600) if self._promotion_report_ts else True,
            },
        }

    def recent_verdicts(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._trade_log[-limit:]


# ── Singleton ─────────────────────────────────────────────────────────

_guard: Optional[ExecutionGuard] = None
_guard_lock = threading.Lock()


def get_execution_guard() -> ExecutionGuard:
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = ExecutionGuard()
    return _guard

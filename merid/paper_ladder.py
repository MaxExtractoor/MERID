"""Paper Trading Ladder — seed capital + milestone-based progression.

Gives agents and the swarm paper money to trade with, organized into
tiers. Each tier has a seed balance, profit target, max drawdown, and
minimum trade count. Hitting the profit target promotes to the next
tier (more capital, tighter risk). Breaching drawdown demotes.

Tiers:
    0  Sandbox    $1,000   — prove you can place orders without blowing up
    1  Rookie     $5,000   — show consistent edge over 50+ trades
    2  Contender  $15,000  — scale up, tighter drawdown
    3  Pro        $50,000  — full paper allocation, pre-live validation
    4  Live-Ready $100,000 — passed all benchmarks, ready for real capital
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_PERSIST_FILE = Path("data/paper_ladder_state.json")


# ════════════════════════════════════════════════════════════════════
# Tier definitions
# ════════════════════════════════════════════════════════════════════

@dataclass
class LadderTier:
    """Definition of a single ladder tier."""
    level: int
    name: str
    seed_usd: float
    profit_target_pct: float       # % gain to promote
    max_drawdown_pct: float        # % loss to demote
    min_trades: int                # minimum trades before promotion eligible
    min_win_rate_pct: float        # minimum win rate to promote
    description: str = ""


DEFAULT_TIERS: List[LadderTier] = [
    LadderTier(
        level=0, name="Sandbox", seed_usd=1_000,
        profit_target_pct=10.0, max_drawdown_pct=20.0,
        min_trades=10, min_win_rate_pct=0.0,
        description="Prove you can place orders without blowing up",
    ),
    LadderTier(
        level=1, name="Rookie", seed_usd=5_000,
        profit_target_pct=8.0, max_drawdown_pct=10.0,
        min_trades=50, min_win_rate_pct=45.0,
        description="Show consistent edge over 50+ trades",
    ),
    LadderTier(
        level=2, name="Contender", seed_usd=15_000,
        profit_target_pct=6.0, max_drawdown_pct=8.0,
        min_trades=100, min_win_rate_pct=48.0,
        description="Scale up with tighter risk controls",
    ),
    LadderTier(
        level=3, name="Pro", seed_usd=50_000,
        profit_target_pct=5.0, max_drawdown_pct=5.0,
        min_trades=200, min_win_rate_pct=50.0,
        description="Full paper allocation, pre-live validation",
    ),
    LadderTier(
        level=4, name="Live-Ready", seed_usd=100_000,
        profit_target_pct=0.0, max_drawdown_pct=3.0,
        min_trades=0, min_win_rate_pct=50.0,
        description="Passed all milestones — ready for real capital",
    ),
]


# ════════════════════════════════════════════════════════════════════
# Portfolio progress tracker
# ════════════════════════════════════════════════════════════════════

@dataclass
class LadderProgress:
    """Tracks a single portfolio's progress through the ladder."""
    portfolio_id: str
    current_tier: int = 0
    seed_balance: float = 0.0
    high_water_mark: float = 0.0
    current_equity: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    promoted_at: float = 0.0       # timestamp of last promotion
    demoted_at: float = 0.0        # timestamp of last demotion
    tier_history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def win_rate_pct(self) -> float:
        total = self.winning_trades + self.losing_trades
        return (self.winning_trades / total * 100) if total > 0 else 0.0

    @property
    def roi_pct(self) -> float:
        if self.seed_balance <= 0:
            return 0.0
        return ((self.current_equity - self.seed_balance) / self.seed_balance) * 100

    @property
    def drawdown_pct(self) -> float:
        if self.high_water_mark <= 0:
            return 0.0
        return ((self.high_water_mark - self.current_equity) / self.high_water_mark) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "win_rate_pct": round(self.win_rate_pct, 1),
            "roi_pct": round(self.roi_pct, 2),
            "drawdown_pct": round(self.drawdown_pct, 2),
        }


# ════════════════════════════════════════════════════════════════════
# Ladder engine
# ════════════════════════════════════════════════════════════════════

class PaperLadder:
    """Manages paper trading capital ladder for all portfolios."""

    def __init__(self, tiers: Optional[List[LadderTier]] = None):
        self.tiers = tiers or DEFAULT_TIERS
        self._progress: Dict[str, LadderProgress] = {}
        self._load_state()

    def get_tier(self, level: int) -> LadderTier:
        if 0 <= level < len(self.tiers):
            return self.tiers[level]
        return self.tiers[-1]

    # ── Portfolio management ──────────────────────────────────────

    def seed_portfolio(self, portfolio_id: str, tier_override: Optional[int] = None) -> LadderProgress:
        """Seed a portfolio with capital from its current (or specified) tier."""
        if portfolio_id in self._progress:
            progress = self._progress[portfolio_id]
            if tier_override is not None:
                progress.current_tier = tier_override
        else:
            progress = LadderProgress(
                portfolio_id=portfolio_id,
                current_tier=tier_override if tier_override is not None else 0,
            )
            self._progress[portfolio_id] = progress

        tier = self.get_tier(progress.current_tier)
        progress.seed_balance = tier.seed_usd
        progress.current_equity = tier.seed_usd
        progress.high_water_mark = tier.seed_usd
        progress.total_trades = 0
        progress.winning_trades = 0
        progress.losing_trades = 0

        # Apply to paper trading engine
        self._apply_to_paper_engine(portfolio_id, tier.seed_usd)

        progress.tier_history.append({
            "event": "seeded",
            "tier": progress.current_tier,
            "tier_name": tier.name,
            "seed_usd": tier.seed_usd,
            "timestamp": time.time(),
        })

        logger.info(
            f"[ladder] Seeded {portfolio_id} at Tier {progress.current_tier} "
            f"({tier.name}) with ${tier.seed_usd:,.0f}"
        )
        self._save_state()
        return progress

    def update_equity(self, portfolio_id: str, equity: float, trades: int = 0,
                      wins: int = 0, losses: int = 0) -> Optional[str]:
        """Update equity and check for promotion/demotion.

        Returns: 'promoted', 'demoted', or None.
        """
        if portfolio_id not in self._progress:
            return None

        p = self._progress[portfolio_id]
        p.current_equity = equity
        p.total_trades += trades
        p.winning_trades += wins
        p.losing_trades += losses

        if equity > p.high_water_mark:
            p.high_water_mark = equity

        tier = self.get_tier(p.current_tier)
        result = None

        # Check demotion (drawdown breach)
        if tier.max_drawdown_pct > 0 and p.drawdown_pct >= tier.max_drawdown_pct:
            result = self._demote(p)

        # Check promotion (profit target + min trades + win rate)
        elif (tier.profit_target_pct > 0
              and p.roi_pct >= tier.profit_target_pct
              and p.total_trades >= tier.min_trades
              and p.win_rate_pct >= tier.min_win_rate_pct
              and p.current_tier < len(self.tiers) - 1):
            result = self._promote(p)

        self._save_state()
        return result

    def _promote(self, p: LadderProgress) -> str:
        old_tier = p.current_tier
        p.current_tier = min(p.current_tier + 1, len(self.tiers) - 1)
        new_tier = self.get_tier(p.current_tier)
        p.promoted_at = time.time()

        p.tier_history.append({
            "event": "promoted",
            "from_tier": old_tier,
            "to_tier": p.current_tier,
            "tier_name": new_tier.name,
            "roi_pct": round(p.roi_pct, 2),
            "trades": p.total_trades,
            "win_rate": round(p.win_rate_pct, 1),
            "timestamp": time.time(),
        })

        # Re-seed with new tier capital
        p.seed_balance = new_tier.seed_usd
        p.current_equity = new_tier.seed_usd
        p.high_water_mark = new_tier.seed_usd
        p.total_trades = 0
        p.winning_trades = 0
        p.losing_trades = 0
        self._apply_to_paper_engine(p.portfolio_id, new_tier.seed_usd)

        logger.info(
            f"[ladder] PROMOTED {p.portfolio_id}: "
            f"Tier {old_tier} → {p.current_tier} ({new_tier.name}, ${new_tier.seed_usd:,.0f})"
        )
        try:
            from core.session_log import set_session_bracket
            set_session_bracket(f"{new_tier.name} (${new_tier.seed_usd:,.0f})")
        except Exception:
            pass
        return "promoted"

    def _demote(self, p: LadderProgress) -> str:
        old_tier = p.current_tier
        p.current_tier = max(p.current_tier - 1, 0)
        new_tier = self.get_tier(p.current_tier)
        p.demoted_at = time.time()

        p.tier_history.append({
            "event": "demoted",
            "from_tier": old_tier,
            "to_tier": p.current_tier,
            "tier_name": new_tier.name,
            "drawdown_pct": round(p.drawdown_pct, 2),
            "timestamp": time.time(),
        })

        # Re-seed at lower tier
        p.seed_balance = new_tier.seed_usd
        p.current_equity = new_tier.seed_usd
        p.high_water_mark = new_tier.seed_usd
        p.total_trades = 0
        p.winning_trades = 0
        p.losing_trades = 0
        self._apply_to_paper_engine(p.portfolio_id, new_tier.seed_usd)

        logger.warning(
            f"[ladder] DEMOTED {p.portfolio_id}: "
            f"Tier {old_tier} → {p.current_tier} ({new_tier.name}, ${new_tier.seed_usd:,.0f})"
        )
        try:
            from core.session_log import set_session_bracket
            set_session_bracket(f"{new_tier.name} (${new_tier.seed_usd:,.0f})")
        except Exception:
            pass
        return "demoted"

    def _apply_to_paper_engine(self, portfolio_id: str, balance: float) -> None:
        """Push the seed balance into the paper trading engine."""
        try:
            from trading.paper_trading import get_paper_engine
            engine = get_paper_engine()
            portfolio = engine.get_portfolio(portfolio_id)
            portfolio.starting_balance = balance
            portfolio.current_balance = balance
            portfolio.total_pnl = 0.0
            portfolio.total_fees = 0.0
            portfolio.total_trades = 0
            portfolio.winning_trades = 0
            portfolio.losing_trades = 0
        except Exception as e:
            logger.warning(f"[ladder] Could not apply balance to paper engine: {e}")

    # ── Status ────────────────────────────────────────────────────

    def get_progress(self, portfolio_id: str) -> Optional[LadderProgress]:
        return self._progress.get(portfolio_id)

    def get_all_progress(self) -> Dict[str, LadderProgress]:
        return dict(self._progress)

    def summary(self) -> Dict[str, Any]:
        portfolios = {}
        for pid, p in self._progress.items():
            tier = self.get_tier(p.current_tier)
            portfolios[pid] = {
                **p.to_dict(),
                "tier_name": tier.name,
                "next_goal": self._next_goal(p),
            }
        return {
            "tiers": [asdict(t) for t in self.tiers],
            "portfolios": portfolios,
            "total_portfolios": len(self._progress),
        }

    def _next_goal(self, p: LadderProgress) -> Dict[str, Any]:
        tier = self.get_tier(p.current_tier)
        if p.current_tier >= len(self.tiers) - 1:
            return {"status": "max_tier", "message": "Live-Ready — maintain performance"}

        goals = []
        if p.roi_pct < tier.profit_target_pct:
            goals.append(f"ROI {p.roi_pct:.1f}% → {tier.profit_target_pct}%")
        if p.total_trades < tier.min_trades:
            goals.append(f"Trades {p.total_trades} → {tier.min_trades}")
        if p.win_rate_pct < tier.min_win_rate_pct:
            goals.append(f"Win rate {p.win_rate_pct:.1f}% → {tier.min_win_rate_pct}%")

        if not goals:
            return {"status": "ready", "message": "All goals met — promotion pending"}

        next_tier = self.get_tier(p.current_tier + 1)
        return {
            "status": "in_progress",
            "remaining": goals,
            "next_tier": next_tier.name,
            "next_seed_usd": next_tier.seed_usd,
        }

    # ── Persistence ───────────────────────────────────────────────

    def _save_state(self) -> None:
        try:
            _PERSIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            state = {
                pid: p.to_dict() for pid, p in self._progress.items()
            }
            _PERSIST_FILE.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.warning(f"[ladder] Failed to save state: {e}")

    def _load_state(self) -> None:
        if not _PERSIST_FILE.exists():
            return
        try:
            data = json.loads(_PERSIST_FILE.read_text())
            for pid, pdata in data.items():
                self._progress[pid] = LadderProgress(
                    portfolio_id=pid,
                    current_tier=pdata.get("current_tier", 0),
                    seed_balance=pdata.get("seed_balance", 0),
                    high_water_mark=pdata.get("high_water_mark", 0),
                    current_equity=pdata.get("current_equity", 0),
                    total_trades=pdata.get("total_trades", 0),
                    winning_trades=pdata.get("winning_trades", 0),
                    losing_trades=pdata.get("losing_trades", 0),
                    promoted_at=pdata.get("promoted_at", 0),
                    demoted_at=pdata.get("demoted_at", 0),
                    tier_history=pdata.get("tier_history", []),
                )
            logger.info(f"[ladder] Restored {len(self._progress)} portfolio(s) from state")
        except Exception as e:
            logger.warning(f"[ladder] Failed to load state: {e}")


# ════════════════════════════════════════════════════════════════════
# Singleton
# ════════════════════════════════════════════════════════════════════

_ladder: Optional[PaperLadder] = None


def get_paper_ladder() -> PaperLadder:
    global _ladder
    if _ladder is None:
        _ladder = PaperLadder()
    return _ladder

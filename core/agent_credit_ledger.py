"""
Agent Credit Ledger — per-agent internal accounting and budget enforcement.

Tracks credits (work units) per agent with:
- Initial allocation and top-ups
- Deductions per task execution
- Transfer between agents
- Budget enforcement (reject task if insufficient credits)
- Ledger history for audit

Usage:
    ledger = AgentCreditLedger(default_credits=1000.0)
    ledger.allocate("agent-1", 500.0)
    ledger.deduct("agent-1", 10.0, reason="backtest task")
    ledger.transfer("agent-1", "agent-2", 50.0)
    balance = ledger.balance("agent-1")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.agent_credit_ledger")


@dataclass
class LedgerEntry:
    """Single ledger transaction."""
    entry_id: int
    agent_id: str
    entry_type: str  # "allocate", "deduct", "transfer_in", "transfer_out", "top_up"
    amount: float
    balance_after: float
    reason: str = ""
    counterparty: str = ""  # for transfers
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "agent_id": self.agent_id,
            "entry_type": self.entry_type,
            "amount": self.amount,
            "balance_after": self.balance_after,
            "reason": self.reason,
            "counterparty": self.counterparty,
            "timestamp": self.timestamp,
        }


class InsufficientCreditsError(Exception):
    """Raised when an agent lacks credits for an operation."""


class AgentCreditLedger:
    """Per-agent credit tracking with budget enforcement."""

    def __init__(self, default_credits: float = 1000.0) -> None:
        self._balances: Dict[str, float] = {}
        self._history: List[LedgerEntry] = []
        self._entry_counter: int = 0
        self._default_credits = default_credits
        self._daily_spend: Dict[str, float] = {}  # agent_id -> today's spend
        self._daily_limit: Dict[str, float] = {}  # agent_id -> daily cap

    def _next_id(self) -> int:
        self._entry_counter += 1
        return self._entry_counter

    def _record(
        self,
        agent_id: str,
        entry_type: str,
        amount: float,
        reason: str = "",
        counterparty: str = "",
    ) -> LedgerEntry:
        entry = LedgerEntry(
            entry_id=self._next_id(),
            agent_id=agent_id,
            entry_type=entry_type,
            amount=amount,
            balance_after=self._balances.get(agent_id, 0.0),
            reason=reason,
            counterparty=counterparty,
        )
        self._history.append(entry)
        return entry

    # ── Core operations ────────────────────────────────────────────

    def allocate(self, agent_id: str, amount: Optional[float] = None) -> float:
        """Allocate initial credits to an agent.

        Args:
            agent_id: Agent identifier.
            amount: Credits to allocate (default: self._default_credits).

        Returns:
            New balance.
        """
        credits = amount if amount is not None else self._default_credits
        if credits < 0:
            raise ValueError("Cannot allocate negative credits")
        self._balances[agent_id] = self._balances.get(agent_id, 0.0) + credits
        self._record(agent_id, "allocate", credits, reason="initial allocation")
        logger.info(f"Allocated {credits} credits to {agent_id}")
        return self._balances[agent_id]

    def top_up(self, agent_id: str, amount: float, reason: str = "top-up") -> float:
        """Add credits to an existing agent.

        Returns:
            New balance.
        """
        if amount <= 0:
            raise ValueError("Top-up amount must be positive")
        if agent_id not in self._balances:
            raise KeyError(f"Agent {agent_id} not in ledger")
        self._balances[agent_id] += amount
        self._record(agent_id, "top_up", amount, reason=reason)
        return self._balances[agent_id]

    def deduct(self, agent_id: str, amount: float, reason: str = "") -> float:
        """Deduct credits from an agent.

        Args:
            agent_id: Agent identifier.
            amount: Credits to deduct.
            reason: Human-readable reason.

        Returns:
            New balance.

        Raises:
            InsufficientCreditsError: If agent lacks sufficient credits.
        """
        if amount < 0:
            raise ValueError("Deduction amount must be non-negative")
        balance = self._balances.get(agent_id, 0.0)
        if balance < amount:
            raise InsufficientCreditsError(
                f"Agent {agent_id} has {balance} credits, needs {amount}"
            )
        self._balances[agent_id] = balance - amount
        self._daily_spend[agent_id] = self._daily_spend.get(agent_id, 0.0) + amount
        self._record(agent_id, "deduct", -amount, reason=reason)
        return self._balances[agent_id]

    def transfer(self, from_agent: str, to_agent: str, amount: float, reason: str = "transfer") -> None:
        """Transfer credits between agents.

        Raises:
            InsufficientCreditsError: If sender lacks sufficient credits.
        """
        if amount <= 0:
            raise ValueError("Transfer amount must be positive")
        if from_agent == to_agent:
            raise ValueError("Cannot transfer to self")

        from_balance = self._balances.get(from_agent, 0.0)
        if from_balance < amount:
            raise InsufficientCreditsError(
                f"Agent {from_agent} has {from_balance} credits, needs {amount}"
            )

        self._balances[from_agent] -= amount
        self._balances[to_agent] = self._balances.get(to_agent, 0.0) + amount

        self._record(from_agent, "transfer_out", -amount, reason=reason, counterparty=to_agent)
        self._record(to_agent, "transfer_in", amount, reason=reason, counterparty=from_agent)

        logger.info(f"Transferred {amount} credits: {from_agent} → {to_agent}")

    # ── Budget enforcement ─────────────────────────────────────────

    def set_daily_limit(self, agent_id: str, limit: float) -> None:
        """Set a daily spending limit for an agent."""
        self._daily_limit[agent_id] = limit

    def check_budget(self, agent_id: str, cost: float) -> bool:
        """Check if agent can afford a task without exceeding daily limit.

        Returns:
            True if the agent has sufficient credits and is within daily limit.
        """
        balance = self._balances.get(agent_id, 0.0)
        if balance < cost:
            return False
        limit = self._daily_limit.get(agent_id)
        if limit is not None:
            spent = self._daily_spend.get(agent_id, 0.0)
            if spent + cost > limit:
                return False
        return True

    def reset_daily_spend(self) -> None:
        """Reset daily spend counters (call at midnight)."""
        self._daily_spend.clear()

    # ── Queries ────────────────────────────────────────────────────

    def balance(self, agent_id: str) -> float:
        """Get current balance for an agent."""
        return self._balances.get(agent_id, 0.0)

    def all_balances(self) -> Dict[str, float]:
        """Get all agent balances."""
        return dict(self._balances)

    def history(self, agent_id: Optional[str] = None) -> List[LedgerEntry]:
        """Get ledger history, optionally filtered by agent."""
        if agent_id:
            return [e for e in self._history if e.agent_id == agent_id]
        return list(self._history)

    def total_credits_in_system(self) -> float:
        """Total credits across all agents."""
        return sum(self._balances.values())

    def summary(self) -> Dict[str, Any]:
        """Ledger summary."""
        return {
            "agent_count": len(self._balances),
            "total_credits": self.total_credits_in_system(),
            "total_transactions": len(self._history),
            "balances": dict(self._balances),
            "daily_spend": dict(self._daily_spend),
        }

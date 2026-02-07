"""
Agent credit ledger tests (S3-01 hardening).

Validates:
- Initial allocation and default credits
- Deduction with balance tracking
- Insufficient credits rejection
- Agent-to-agent transfers
- Daily spending limits and budget checks
- Daily spend reset
- Ledger history and audit trail
- Edge cases (negative amounts, self-transfer, unknown agents)
"""

import unittest

from core.agent_credit_ledger import (
    AgentCreditLedger,
    InsufficientCreditsError,
    LedgerEntry,
)


class TestAllocation(unittest.TestCase):
    """Credit allocation."""

    def test_allocate_default(self):
        ledger = AgentCreditLedger(default_credits=1000.0)
        balance = ledger.allocate("agent-1")
        self.assertEqual(balance, 1000.0)

    def test_allocate_custom_amount(self):
        ledger = AgentCreditLedger()
        balance = ledger.allocate("agent-1", 500.0)
        self.assertEqual(balance, 500.0)

    def test_allocate_adds_to_existing(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        balance = ledger.allocate("agent-1", 200.0)
        self.assertEqual(balance, 300.0)

    def test_allocate_negative_raises(self):
        ledger = AgentCreditLedger()
        with self.assertRaises(ValueError):
            ledger.allocate("agent-1", -100.0)

    def test_balance_unknown_agent_is_zero(self):
        ledger = AgentCreditLedger()
        self.assertEqual(ledger.balance("nonexistent"), 0.0)


class TestTopUp(unittest.TestCase):
    """Credit top-ups."""

    def test_top_up(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        balance = ledger.top_up("agent-1", 50.0)
        self.assertEqual(balance, 150.0)

    def test_top_up_zero_raises(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        with self.assertRaises(ValueError):
            ledger.top_up("agent-1", 0.0)

    def test_top_up_unknown_agent_raises(self):
        ledger = AgentCreditLedger()
        with self.assertRaises(KeyError):
            ledger.top_up("nonexistent", 50.0)


class TestDeduction(unittest.TestCase):
    """Credit deductions."""

    def test_deduct(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        balance = ledger.deduct("agent-1", 30.0, reason="backtest")
        self.assertEqual(balance, 70.0)

    def test_deduct_to_zero(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 50.0)
        balance = ledger.deduct("agent-1", 50.0)
        self.assertEqual(balance, 0.0)

    def test_deduct_insufficient_raises(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 10.0)
        with self.assertRaises(InsufficientCreditsError):
            ledger.deduct("agent-1", 20.0)

    def test_deduct_negative_raises(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        with self.assertRaises(ValueError):
            ledger.deduct("agent-1", -10.0)

    def test_deduct_from_unallocated_raises(self):
        ledger = AgentCreditLedger()
        with self.assertRaises(InsufficientCreditsError):
            ledger.deduct("agent-1", 10.0)


class TestTransfer(unittest.TestCase):
    """Agent-to-agent transfers."""

    def test_transfer(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        ledger.allocate("agent-2", 50.0)
        ledger.transfer("agent-1", "agent-2", 30.0)
        self.assertEqual(ledger.balance("agent-1"), 70.0)
        self.assertEqual(ledger.balance("agent-2"), 80.0)

    def test_transfer_insufficient_raises(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 10.0)
        ledger.allocate("agent-2", 50.0)
        with self.assertRaises(InsufficientCreditsError):
            ledger.transfer("agent-1", "agent-2", 20.0)

    def test_transfer_to_self_raises(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        with self.assertRaises(ValueError):
            ledger.transfer("agent-1", "agent-1", 10.0)

    def test_transfer_zero_raises(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        ledger.allocate("agent-2", 100.0)
        with self.assertRaises(ValueError):
            ledger.transfer("agent-1", "agent-2", 0.0)

    def test_transfer_creates_recipient_if_needed(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        ledger.transfer("agent-1", "agent-new", 25.0)
        self.assertEqual(ledger.balance("agent-new"), 25.0)

    def test_transfer_conserves_total(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        ledger.allocate("agent-2", 200.0)
        total_before = ledger.total_credits_in_system()
        ledger.transfer("agent-1", "agent-2", 50.0)
        self.assertEqual(ledger.total_credits_in_system(), total_before)


class TestBudgetEnforcement(unittest.TestCase):
    """Daily spending limits and budget checks."""

    def test_check_budget_sufficient(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        self.assertTrue(ledger.check_budget("agent-1", 50.0))

    def test_check_budget_insufficient(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 10.0)
        self.assertFalse(ledger.check_budget("agent-1", 50.0))

    def test_daily_limit_blocks_overspend(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 1000.0)
        ledger.set_daily_limit("agent-1", 100.0)
        ledger.deduct("agent-1", 80.0)
        # 80 spent, 30 more would exceed 100 limit
        self.assertFalse(ledger.check_budget("agent-1", 30.0))

    def test_daily_limit_allows_within_budget(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 1000.0)
        ledger.set_daily_limit("agent-1", 100.0)
        ledger.deduct("agent-1", 50.0)
        self.assertTrue(ledger.check_budget("agent-1", 40.0))

    def test_reset_daily_spend(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 1000.0)
        ledger.set_daily_limit("agent-1", 100.0)
        ledger.deduct("agent-1", 90.0)
        self.assertFalse(ledger.check_budget("agent-1", 20.0))
        ledger.reset_daily_spend()
        self.assertTrue(ledger.check_budget("agent-1", 20.0))


class TestLedgerHistory(unittest.TestCase):
    """Ledger history and audit trail."""

    def test_history_records_allocations(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        history = ledger.history("agent-1")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].entry_type, "allocate")

    def test_history_records_deductions(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        ledger.deduct("agent-1", 30.0, reason="task-xyz")
        history = ledger.history("agent-1")
        deductions = [e for e in history if e.entry_type == "deduct"]
        self.assertEqual(len(deductions), 1)
        self.assertEqual(deductions[0].reason, "task-xyz")

    def test_history_records_transfers(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        ledger.allocate("agent-2", 50.0)
        ledger.transfer("agent-1", "agent-2", 25.0)
        h1 = ledger.history("agent-1")
        h2 = ledger.history("agent-2")
        self.assertTrue(any(e.entry_type == "transfer_out" for e in h1))
        self.assertTrue(any(e.entry_type == "transfer_in" for e in h2))

    def test_full_history(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        ledger.allocate("agent-2", 100.0)
        ledger.deduct("agent-1", 10.0)
        all_history = ledger.history()
        self.assertEqual(len(all_history), 3)

    def test_entry_to_dict(self):
        ledger = AgentCreditLedger()
        ledger.allocate("agent-1", 100.0)
        entry = ledger.history("agent-1")[0]
        d = entry.to_dict()
        self.assertIn("entry_id", d)
        self.assertIn("timestamp", d)


class TestLedgerSummary(unittest.TestCase):
    """Ledger summary and queries."""

    def test_all_balances(self):
        ledger = AgentCreditLedger()
        ledger.allocate("a", 100.0)
        ledger.allocate("b", 200.0)
        balances = ledger.all_balances()
        self.assertEqual(balances["a"], 100.0)
        self.assertEqual(balances["b"], 200.0)

    def test_total_credits(self):
        ledger = AgentCreditLedger()
        ledger.allocate("a", 100.0)
        ledger.allocate("b", 200.0)
        self.assertEqual(ledger.total_credits_in_system(), 300.0)

    def test_summary(self):
        ledger = AgentCreditLedger()
        ledger.allocate("a", 100.0)
        s = ledger.summary()
        self.assertEqual(s["agent_count"], 1)
        self.assertEqual(s["total_credits"], 100.0)
        self.assertIn("balances", s)


if __name__ == "__main__":
    unittest.main()

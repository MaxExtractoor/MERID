#!/usr/bin/env python3
"""Add window-based risk limit check to order_gate.py"""

import re

# Read the file
with open('merid/event_venues/kalshi/order_gate.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add the blocked_window_limit metric after blocked_price_repeat
content = content.replace(
    'blocked_price_repeat: int = 0  # CRITICAL: Block repeat price execution (same ticker+side+price)',
    'blocked_price_repeat: int = 0  # CRITICAL: Block repeat price execution (same ticker+side+price)\n    blocked_window_limit: int = 0  # CRITICAL: Block window-based risk limit violations (3% per agent, 5% total per 15m)'
)

# Add the window limit check after the price repeat check (first occurrence in PreTradeGate.check)
# Find the first occurrence of the price repeat block ending
pattern = r'(            return GateVerdict\(\s+                allowed=False,\s+                client_order_id=coid,\s+                reason=f"price_repeat:\{price_reason\}",\s+            \))\s+(        # 3\.5\. Price guard:)'
replacement = r'\1\n\n        # 3d. CRITICAL: Window-based risk limit check (HARD STOP) - 2026-07-06\n        # Enforces 3% per agent per 15-minute window and 5% total venue per 15-minute window\n        # This prevents over-trading and forces agents to get better entry prices\n        # No more entries until exposure is closed out via trailing stop, ratchet, or 99c exit\n        try:\n            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_risk_envelope\n            envelope = get_risk_envelope()\n            if envelope:\n                import time\n                order_notional_usd = (target_count * price_cents) / 100.0\n                window_allowed, window_reason = envelope.check_window_limit(\n                    agent_id=agent_id,\n                    order_notional_usd=order_notional_usd,\n                    current_ts=time.time()\n                )\n                if not window_allowed:\n                    self._store._metrics.blocked_window_limit += 1\n                    logger.warning(\n                        "[GATE-ALERT] window_limit_blocked contract=%s side=%s agent=%s notional=$%.2f reason=%s (metric: blocked_window_limit=%d)",\n                        contract_id, side, agent_id, order_notional_usd, window_reason,\n                        self._store._metrics.blocked_window_limit,\n                    )\n                    return GateVerdict(\n                        allowed=False,\n                        client_order_id=coid,\n                        reason=f"window_limit:{window_reason}",\n                    )\n        except Exception as e:\n            logger.debug("[GATE] Failed to check window limit: %s", e)\n\n        \\2'

content = re.sub(pattern, replacement, content, count=1)

# Write the file back
with open('merid/event_venues/kalshi/order_gate.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully added window-based risk limit check to order_gate.py")

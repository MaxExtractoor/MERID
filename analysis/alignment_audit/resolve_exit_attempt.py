"""Resolve exit attempt 836789d3 (KXETH15M-26NOV011930-30) with exchange evidence.

Evidence gathered 19:37Z via REST:
- GET /portfolio/fills?ticker: exactly 1 fill (entry 0727ff23 @78c maker); no exit fill exists.
- GET /portfolio/orders (resting): empty; IOC exits cannot rest regardless.
- GET /markets/{ticker}: status=finalized; market closed 00:30Z — Kalshi cancels all
  resting orders at close; nothing can bind further exposure.
=> The exit order provably never bound exposure: NOT_ACCEPTED_CONFIRMED is the
correct terminal (same verdict shape as sibling XRP exit via position_closed).
"""
import sqlite3, json, sys
sys.path.insert(0, r'C:\Dev\MERID')
from merid.event_venues.kalshi.order_attempt_store import (
    OrderAttemptStore, ExitOrderAttemptState,
)

ATTEMPT_ID = '836789d3-d582-4b7a-9a88-4bccff6028a7'

store = OrderAttemptStore()
rec = store.get_exit_attempt(ATTEMPT_ID)
print('before:', rec.state if rec else None, 'version', rec.state_version if rec else None)

evidence = {
    'recovery': 'operator_evidence_backed',
    'ticker': 'KXETH15M-26NOV011930-30',
    'fills_on_ticker': ['0727ff23-9891-b29c-199d-af7c5df3e320'],
    'exit_fill_found': False,
    'resting_orders': 0,
    'market_status': 'finalized',
    'verified_at_utc': '2026-11-01T19:37Z',
    'verdict': 'no exit order present on exchange; market closed; no residual exposure possible',
}

new = store.transition_exit_attempt(
    ATTEMPT_ID,
    ExitOrderAttemptState.NOT_ACCEPTED_CONFIRMED.value,
    actor='operator_recovery',
    reason='position_closed:market_finalized_no_exchange_presence',
    raw_payload=evidence,
)
print('after:', new.state if new else None, 'version', new.state_version if new else None)

# confirm preflight-facing counts now
db = sqlite3.connect('data/kalshi_order_attempts.db', timeout=10)
n = db.execute(
    "SELECT COUNT(*) FROM exit_order_attempts WHERE state IN "
    "('SUBMITTING','SUBMISSION_UNKNOWN','RESOLVING_ON_EXCHANGE')").fetchone()[0]
print('blocking exit attempts now:', n)

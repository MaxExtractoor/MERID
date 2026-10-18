# Exit-architecture acceptance suite — freeze manifest

Frozen with implementation commits `e8986370` (arbiter + enforcing path)
and `abfee65c` (submit revalidation, latency, reconcile liveness,
paired-side telemetry). Entries remain halted; no live order submission is
performed by any suite (all transport is stubbed).

## How to run

Each file is a standalone script, not a pytest module (they manage their own
env isolation via `MERID_*` env vars and print a pass matrix). From repo root:

```powershell
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exit_arbiter.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exit_replay.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exit_state.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exit_faults.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exit_interception.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_approval_binding.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exit_integration.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exit_reconcile_liveness.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_submit_revalidation.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_exec_latency.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_side_swap.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_floor_payload.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_loss_cap_units.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_settlement_lifecycle.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_wire_payload.py
.\.venv\Scripts\python.exe tests\exit_acceptance\accept_shadow.py
```

Expected results at freeze:

| Suite | Expected |
|---|---|
| accept_exit_arbiter | 48/48 |
| accept_exit_replay | 7/7 |
| accept_exit_state | round-trip pass |
| accept_exit_faults | 22/22 |
| accept_exit_interception | 12/12 |
| accept_approval_binding | pass (all binding checks) |
| accept_exit_integration | 23/23 |
| accept_exit_reconcile_liveness | 8/8 |
| accept_submit_revalidation | 20/20 |
| accept_exec_latency | 15/15 |
| accept_side_swap | 22/22 |

## Environment

- Windows venv at `.\.venv` (repo-local); Python 3.11.
- No network or credentials required; suites stub transport and set their
  own `MERID_EXIT_STATE_PATH` / `MERID_EXIT_ATTEMPTS_PATH` temp dirs.
- `MERID_ENV=production` and `MERID_EXIT_ARBITER_REQUIRED=1` are set inside
  the enforcing suites.

## Historical input (cohort replay — NOT part of the frozen suites)

`scripts/cohort_policy_replay.py` consumes:

- `data/exit_decision_ledger_rows.jsonl` — 383 row cohort ledger,
  sha256 `45919de8be03fd964bb5912123415ce5267afbf45303b9a9db9527a8477f95c3`
  (private trading data; not committed).
- `data/kalshi_fills.db` — sha256
  `07d4786aa21b45c73a968ef170b59cd24f363eca45a7e6673df7eaa6709fd1dd`.

Row schema: see `scripts/exit_decision_ledger.py` (authoritative writer).
`realized_pnl_c` and `cf_hold_pnl_c` are already net of fees;
`exit_markout_settle_c` is a delta (exec − settle value), not a price.

Expected report invariants (enforced in the script; exit 1 on violation):

- `sum(realized_known) − sum(cf_hold_known) == delta_total`
- `benefit − cost == sum(deltas_early_known) == delta_total`
- all rows classified (`exit`/`settlement`/`open`)
- no threshold-fill modeling from marks, quotes, or settlement payouts —
  only real exit fills ≥ L count as confirmed executable evidence.

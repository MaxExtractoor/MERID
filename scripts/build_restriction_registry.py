"""Restriction registry builder — audits every active trading gate.

Merges three evidence sources into one versioned registry:
  1. ``.env`` MERID_* flags (effective configuration)
  2. AGENTS.md documented rationale/history (prose, hand-mapped families)
  3. runtime state files (probation/cooldown counters)

Every entry records: id, scope, trigger/release (where derivable),
rationale, linked defect/incident, deploy-date evidence, state/reset,
current evidence status, and an honest ``verification`` field —
``env_flag`` (config-level only), ``code_traced`` (gate located in code),
or ``needs_code_trace``.  Nothing here disables anything; this is the
decision table input for retain/modify/retire review.

CLI::

    py -3 scripts/build_restriction_registry.py --out reports/restriction_registry_2026-11-14.json
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Family map: prefix -> (family_name, category, documented_rationale,
#                        linked_defect_or_incident, deploy_evidence)
FAMILIES = {
    "MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS": (
        "per_asset_moneyness_caps",
        "economic_filter",
        "Per-asset audited entry-price caps on NO side; band changes require "
        "settled-fill + veto-counterfactual audit evidence (AGENTS.md §14).",
        "XRP-NO audited -9.54 USD unpriceable down-moves; 51-64c pockets "
        "blocked per asset",
        "AGENTS.md §14; .env comments"),
    "MERID_PRICE_CAP_EXCEPT": (
        "price_cap_exception_probes",
        "temporary_workaround",
        "Lets above-cap candidates through only when reserve-stacked net EV "
        "clears +2c inside 75<px<=89.99; armed per-asset to re-measure "
        "stale-evidence cohorts; each probe kills via flag->0.",
        "Stale-evidence cohort re-measurement post-2026-11-02 stack",
        "AGENTS.md §14 2026-11-06 note"),
    "MERID_PINNED_FAV": (
        "pinned_fav_lane",
        "bounded_sub_lane",
        "Maker-band lane for converged favorites; floor history 90->92->94 "
        "after toxic pockets; per-asset moneyness mirrors at 98/99.",
        "90-91c pocket toxic (-1405c/82); >=92c 100%/+611c/103",
        "AGENTS.md §14 floor history + 2026-10-27/31 notes"),
    "MERID_SETTLEMENT_LANE": (
        "settlement_convergence_lane",
        "bounded_sub_lane",
        "Converged-favorite lane near settlement; NO-side moneyness mirror "
        "99c so converged NO favorites aren't vetoed by normal-path caps.",
        "Normal-path caps never measured >=90c maker band",
        "AGENTS.md §14"),
    "MERID_CHEAP_NO": (
        "cheap_no_lane",
        "bounded_sub_lane",
        "Cheap-NO entries 25-40c with negative-EV floor -10c; bounded daily "
        "and per-ticker caps.",
        "Documented lane audit domain",
        "AGENTS.md §14 lane list"),
    "MERID_MBAND": (
        "marginal_band_lane",
        "bounded_sub_lane",
        "Marginal-band rescue lane 50-89c with daily caps per asset.",
        "Band-rescue evidence cohort",
        "AGENTS.md §14 lane list"),
    "MERID_DRIFT": (
        "drift_lane",
        "bounded_sub_lane",
        "Drift-following lane with price/TTE bounds, scope-release rule "
        "(n>=20 and trailing EV>=+1c).",
        "Scope probation until release criteria met",
        "AGENTS.md §14 + .env comments"),
    "MERID_LATE_TAKER": (
        "late_taker_lane",
        "bounded_sub_lane",
        "Late-window taker lane, sides=no, TTE 120-240s, 1 contract max.",
        "Late-window execution evidence",
        ".env flags"),
    "MERID_LATE_EDGE_PROBE": (
        "late_edge_probe",
        "probe_lane",
        "Edge probe 10-69.99c both sides, min EV +3c, daily max 24.",
        "Probe measurement cohort",
        ".env flags"),
    "MERID_EV_PROBE": (
        "ev_probe_band",
        "probe_lane",
        "EV probe band 70-89.99c, min gross +2c, neg floor +1.5c.",
        "Probe measurement cohort",
        ".env flags"),
    "MERID_TAIL": (
        "tail_loss_and_calibration",
        "economic_filter+stateful",
        "Tail-loss drop/floor/retry family + tail-LCB gate >=80c + "
        "calibration cap full-range with fitted NO curve.",
        "Tail calibration scope per loaded artifact",
        "AGENTS.md §14 tail calibration paragraph"),
    "MERID_CBP_PROBATION": (
        "cbp_probation",
        "stateful_throttle",
        "Counterfactual-band probation: max 4 submissions, mech pause 900s, "
        "timeout 1800s, reset cooldown 7200s, EQ cooldown 3600s.",
        "Probation state machine for degraded bands",
        ".env flags"),
    "MERID_THRESHOLD_CELL_PROBATION": (
        "threshold_cell_probation",
        "stateful_throttle",
        "Threshold-cell probation mirror of CBP family with suspend/release "
        "rules.",
        "Cell-level probation state machine",
        ".env flags"),
    "MERID_SIDE_THROTTLE": (
        "side_throttle",
        "stateful_throttle",
        "Side-level throttle: caution/suspend counts (999=effectively "
        "disabled), suspend 900s.",
        "Loss-streak side containment",
        ".env flags"),
    "MERID_VETO": (
        "veto_release",
        "stateful_throttle",
        "Veto release mode=auto, min n=20, min EV +2c — vetoes lift only "
        "after evidence accrues.",
        "Vetoed-band re-entry evidence gate",
        ".env flags"),
    "MERID_DRIFT_SCOPE": (
        "drift_scope_release",
        "stateful_throttle",
        "Drift scope stays restricted until n>=20 and trailing EV>=+1c.",
        "Unproven drift scope containment",
        ".env flags"),
    "MERID_FADE_GATE": (
        "fade_gate",
        "stateful_throttle",
        "Fade gate trips at EV -2c, releases at 0c, stale 7d.",
        "Adverse-fade containment",
        ".env flags"),
    "MERID_BANKROLL": (
        "bankroll_limits",
        "exposure_containment",
        "Consecutive-loss ticks (1e6=off), max drawdown 100%, stale 180s, "
        "refresh 60s.",
        "Capital protection",
        ".env flags"),
    "MERID_FIXED_EXPOSURE_CAP": (
        "fixed_exposure_cap",
        "exposure_containment",
        "Per-order/position USD cap $6.00 shared with shard sizing.",
        "Account-size bound",
        ".env + AGENTS.md §6a"),
    "MERID_MAX_CONTRACTS_PER_ORDER": (
        "max_contracts_per_order",
        "exposure_containment",
        "6 contracts per order bound.",
        "Account-size bound",
        ".env + AGENTS.md §14"),
    "MERID_WINDOW_PLAN": (
        "window_plan",
        "exposure_containment",
        "Per-window/per-asset USD caps $6, max contracts 6, order cap $6, "
        "lift-sizing flag.",
        "Window-level capital allocation",
        ".env flags"),
    "MERID_WINDOW_QUOTA": (
        "window_quota",
        "stateful_throttle",
        "Consensus-age 120s, TTE 120-780s, max contracts 3, spread cap 8c, "
        "min net EV 0, book-drop veto 6c.",
        "Window quota consensus gate",
        ".env flags"),
    "MERID_BASKET": (
        "basket_concentration",
        "exposure_containment",
        "Same-side max 2, leader max-age 900s/90s live.",
        "Correlated-exposure containment",
        ".env flags"),
    "MERID_STRIP_CONC": (
        "strip_concentration",
        "exposure_containment",
        "Max 3 open same-side, EV margin -5c.",
        "Strip-level concentration",
        ".env flags"),
    "MERID_EDGE_MIDWIN": (
        "edge_midwin_relief",
        "economic_filter",
        "Mid-window edge relief bands 180-660s TTE, price>=35c, relief "
        "+8c YES/+8c NO, BTC-YES exclusion removed 2026-11-12.",
        "Mid-window edge evidence",
        ".env comments (2026-10-20 recut, 2026-11-12 removal)"),
    "MERID_COUNTER_REGIME": (
        "counter_regime_edge",
        "economic_filter",
        "Counter-regime min edge +4c / NO +2c.",
        "Regime-conditional edge floor",
        ".env flags"),
    "MERID_EDGE_BIAS": (
        "edge_bias_correction",
        "economic_filter",
        "Edge bias cap 8c, rebate cap 4c, min neff 12, prior k=8.",
        "Systematic edge overstatement correction",
        ".env flags"),
    "MERID_EVIDENCE": (
        "evidence_gates",
        "economic_filter",
        "Stale-after 345600s/28800s, hard-sparse EV 6c, degraded max "
        "contracts 6, LCB q=0.25.",
        "Evidence-freshness gating",
        ".env flags"),
    "MERID_LIVE_ENTRY_MAX_TTE": (
        "live_entry_tte",
        "timing",
        "Max TTE 840s for live entries; lane-specific floors elsewhere.",
        "Entry-window bound",
        ".env flags"),
    "MERID_EXECUTION": (
        "execution_freshness",
        "timing+integrity",
        "Decision max age 12000ms, spot 12s, book exec 5000ms, RTI exec "
        "3000ms, hard-lock quote 2500ms.",
        "Stale-data protection (integrity)",
        ".env flags"),
    "MERID_EXIT": (
        "exit_protection",
        "integrity_safety",
        "Envelope TTE 120s, inflight stale 30s, reconcile stuck 180s, "
        "firewall observe flag, EV exit gate.",
        "Protective exits (retain)",
        ".env flags"),
    "MERID_INTEGRITY": (
        "integrity_gates",
        "integrity_safety",
        "Circuit breaker, observe-only, submission-unknown reconcile 10s, "
        "inflight reconcile 30s.",
        "Fail-closed integrity (retain)",
        ".env flags"),
    "MERID_AUTO_FUND_TRADING_SHARD": (
        "shard_collateral",
        "exposure_containment",
        "Auto intra-account transfer to fund shard-2 collateral.",
        "Shard collateral requirement (AGENTS.md §6a)",
        ".env + AGENTS.md §6a"),
    "MERID_POSITION_EXPIRY": (
        "position_expiry_grace",
        "timing",
        "60s grace before expired-position quarantine.",
        "Expired-position handling",
        ".env flags"),
    "MERID_RISK_SCALED_SIZING": (
        "risk_scaled_sizing",
        "exposure_containment",
        "Sizing scaled to shard cash with parabolic fee reserve.",
        "Bankroll-proportional sizing (AGENTS.md §6a)",
        ".env + AGENTS.md §6a"),
    "MERID_MAKER": (
        "maker_lane_gates",
        "bounded_sub_lane",
        "Maker bid lane enabled, min spread 1c, taker-drift veto 3c.",
        "Maker execution evidence",
        ".env flags"),
    "MERID_TREND_YES_HI": (
        "trend_yes_hi",
        "economic_filter",
        "Disabled (0); max TTE 600s, min breadth 3 when enabled.",
        "Trend filter (currently off)",
        ".env flags"),
    "MERID_PROVISIONAL_MIN_EV": (
        "provisional_min_ev",
        "economic_filter",
        "Per-asset-side provisional EV floors all 0.0 (disabled).",
        "Provisional-cell EV floor (off)",
        ".env flags"),
    "MERID_MAX_SLIPPAGE": (
        "max_slippage",
        "execution_cost",
        "Entry slippage cap 15c, stop 8c.",
        "Execution-cost bound",
        ".env flags"),
    "MERID_OBSERVE_ONLY": (
        "observe_only",
        "integrity_safety",
        "Emergency read-only switch (=0 live).",
        "Operator emergency brake (retain)",
        ".env + AGENTS.md"),
    "MERID_LIVE_CANARY": (
        "live_canary",
        "probe_lane",
        "Exploration overlay — must stay off (AGENTS.md §14).",
        "Exploration overlay (off by policy)",
        "AGENTS.md §14"),
    "MERID_CHEAP_TAIL_CANARY": (
        "cheap_tail_canary",
        "probe_lane",
        "Exploration overlay — must stay off (=0).",
        "Exploration overlay (off by policy)",
        "AGENTS.md §14"),
    "MERID_CANARY_4C_LCB": (
        "canary_4c_lcb",
        "probe_lane",
        "Exploration overlay — must stay off (=0).",
        "Exploration overlay (off by policy)",
        "AGENTS.md §14"),
}


def _load_flags() -> dict:
    flags = {}
    for ln in (REPO / ".env").read_text(
            encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        if k.strip().startswith("MERID_"):
            flags[k.strip()] = v.strip()
    return flags


def _family_for(key: str) -> str:
    for prefix in FAMILIES:
        if key.startswith(prefix):
            return prefix
    return ""


def build() -> dict:
    flags = _load_flags()
    entries = []
    for key in sorted(flags):
        fam = _family_for(key)
        meta = FAMILIES.get(fam)
        entries.append({
            "flag": key, "value": flags[key],
            "family": meta[0] if meta else "unclassified",
            "category": meta[1] if meta else "unclassified",
            "scope": "see family doc",
            "trigger_release": "see family doc",
            "rationale": meta[2] if meta else "",
            "linked_defect": meta[3] if meta else "",
            "deploy_evidence": meta[4] if meta else "",
            "state_reset": "n/a (config flag)",
            "current_evidence": "not_yet_evaluated",
            "verification": "env_flag",
            "review_date": None, "owner": None,
        })
    # state files
    state_files = {}
    for p in ("data/fade_gate_state.json", "data/drift_lane_state.json",
              "data/directional_regime_state.json",
              "data/live_runtime_state.json",
              "data/promotion_states.json",
              "data/position_exit_state.json"):
        fp = REPO / p
        if fp.exists():
            state_files[p] = {"bytes": fp.stat().st_size,
                              "mtime_utc": datetime.fromtimestamp(
                                  fp.stat().st_mtime, timezone.utc).isoformat()}
    return {
        "schema": "restriction_registry_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "n_flags": len(entries),
        "families": {k: {"name": v[0], "category": v[1],
                         "rationale": v[2], "linked_defect": v[3],
                         "deploy_evidence": v[4]}
                     for k, v in FAMILIES.items()},
        "entries": entries,
        "runtime_state_files": state_files,
        "notes": [
            "env_flag verification = configuration-level only; code_traced "
            "requires locating the gate in the decision path",
            "unclassified flags still gate behavior — they need family "
            "assignment before the ablation family is declared",
            "retain/modify/retire decisions require the stateful replay "
            "evidence, not this registry alone",
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rep = build()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    from collections import Counter
    cats = Counter(e["category"] for e in rep["entries"])
    print(f"wrote {out}: {rep['n_flags']} flags, "
          f"{len(rep['families'])} families")
    for c, n in cats.most_common():
        print(f"  {c}: {n}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

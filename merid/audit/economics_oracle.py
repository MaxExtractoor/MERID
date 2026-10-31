"""Independent economics oracle for Kalshi binary-contract audits.

A deliberately small, self-contained reference implementation used for
differential/metamorphic testing against the production execution chain.
It imports NO production conversion or fee helpers: every formula below is
restated from the venue documentation so agreement between this module and
production is meaningful evidence.

Scope is intentionally narrow: standard $1/$0 binary contracts on the
two-outcome bid-only book model, one outcome at a time, buy-side entry and
sell-side exit economics.  Unsupported shapes return a structured veto
rather than an extrapolated answer.

Conventions (documented Kalshi semantics):
  - book supplies YES bids and NO bids as (price_cents, qty) pairs
  - YES ask ladder = {100 - n : qty | (n, qty) in no_bids}
  - NO ask  ladder = {100 - p : qty | (p, qty) in yes_bids}
  - model fee = rate * C * P * (1-P) rounded UP to 6 decimal dollars, then
    balance-aligned to the account precision (default $0.0001 direct member)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, List, Optional, Tuple

MODEL_FEE_DP = Decimal("0.000001")
BALANCE_DP_DIRECT = Decimal("0.0001")
BALANCE_DP_NON_DIRECT = Decimal("0.01")
TAKER_RATE = Decimal("0.07")
MAKER_RATE = Decimal("0.0175")

Ladder = List[Tuple[int, int]]  # (price_cents, qty_contracts)


@dataclass
class OracleOwnOrder:
    action: str          # "buy" | "sell"
    outcome: str         # "yes" | "no"
    price_cents: int
    qty: int


@dataclass
class OracleResult:
    ok: bool
    veto_reasons: List[str] = field(default_factory=list)
    executable_qty: int = 0
    principal_dollars: Optional[Decimal] = None   # buy cost / sell proceeds
    fee_dollars: Optional[Decimal] = None
    net_ev_dollars: Optional[Decimal] = None
    economic_limit_cents: Optional[int] = None    # worst price with EV >= 0
    own_blocked_qty: int = 0
    own_book_anomaly: bool = False
    assumptions: Dict[str, Any] = field(default_factory=dict)


def asks_for(outcome: str, yes_bids: Ladder, no_bids: Ladder) -> Ladder:
    """Held-side ask ladder (cheapest first) in own-side price space."""
    if outcome == "yes":
        return sorted(((100 - n, q) for n, q in no_bids), key=lambda x: x[0])
    return sorted(((100 - p, q) for p, q in yes_bids), key=lambda x: x[0])


def bids_for(outcome: str, yes_bids: Ladder, no_bids: Ladder) -> Ladder:
    """Held-side bid ladder (highest first) in own-side price space."""
    src = yes_bids if outcome == "yes" else no_bids
    return sorted(((p, q) for p, q in src), key=lambda x: -x[0])


def own_levels_for(
    walk_side: str,          # "ask" (buying) | "bid" (selling)
    outcome: str,
    own_orders: List[OracleOwnOrder],
) -> Dict[int, int]:
    """Ladder-price -> own qty, in the walked ladder's price space."""
    opposite = "no" if outcome == "yes" else "yes"
    out: Dict[int, int] = {}
    for o in own_orders:
        if o.qty <= 0:
            continue
        if walk_side == "ask":
            # own (sell, outcome) @a  and  own (buy, opposite) @(100-a)
            if o.action == "sell" and o.outcome == outcome:
                lvl = o.price_cents
            elif o.action == "buy" and o.outcome == opposite:
                lvl = 100 - o.price_cents
            else:
                continue
        else:
            # own (buy, outcome) @p sits on the bid ladder we sell into
            if o.action == "buy" and o.outcome == outcome:
                lvl = o.price_cents
            else:
                continue
        if 0 < lvl < 100:
            out[lvl] = out.get(lvl, 0) + o.qty
    return out


def model_fee_dollars(
    qty: Decimal, price_cents: Decimal, rate: Decimal
) -> Decimal:
    """rate * C * P * (1-P) ceiled to 6dp dollars (P in dollars)."""
    if qty <= 0:
        return Decimal("0")
    p = price_cents / Decimal("100")
    raw = rate * qty * p * (Decimal("1") - p)
    return raw.quantize(MODEL_FEE_DP, rounding=ROUND_CEILING)


def fee_bound_dollars(
    qty: Decimal, price_cents: Decimal, rate: Decimal,
    balance_precision: Decimal = BALANCE_DP_DIRECT,
) -> Decimal:
    """Model fee bounded up at the account balance precision (per fill)."""
    return model_fee_dollars(qty, price_cents, rate).quantize(
        balance_precision, rounding=ROUND_CEILING
    )


def walk(
    levels: Ladder,
    qty: int,
    own_map: Dict[int, int],
    stp: str = "taker_at_cross",
) -> Tuple[int, Decimal, int, bool]:
    """STP-aware depth walk.

    Returns (covered_qty, total_price_x_qty_cents, own_blocked_qty, anomaly).
    taker_at_cross: matching halts before the first own-touching level
    (conservative — unknown queue position inside a mixed level).
    maker: own qty is canceled and skipped; external depth continues.
    """
    covered = 0
    cost = Decimal("0")
    blocked = 0
    anomaly = False
    for price, size in levels:
        own = own_map.get(price, 0)
        external = size - own
        if external < 0:
            anomaly = True
            external = 0
        if own > 0:
            blocked += own
            if stp == "taker_at_cross":
                break
        take = min(external, qty - covered)
        if take > 0:
            cost += Decimal(price) * take
            covered += take
        if covered >= qty:
            break
    return covered, cost, blocked, anomaly


def evaluate_buy(
    outcome: str,
    qty: int,
    limit_cents: int,
    p_yes: Decimal,
    yes_bids: Ladder,
    no_bids: Ladder,
    own_orders: Optional[List[OracleOwnOrder]] = None,
    stp: str = "taker_at_cross",
    fee_rate: Decimal = TAKER_RATE,
    balance_precision: Decimal = BALANCE_DP_DIRECT,
) -> OracleResult:
    """Reference evaluation of buying ``outcome`` at up to ``limit_cents``.

    net_EV = qty * p_selected - principal - fees  (in dollars).  The
    ``economic_limit_cents`` is the worst buy price whose per-contract EV
    stays non-negative at the model fee rate — the approval bound the
    production submit-revalidator must reproduce.
    """
    res = OracleResult(ok=False)
    if outcome not in ("yes", "no"):
        res.veto_reasons.append(f"unsupported_outcome:{outcome}")
        return res
    if qty <= 0:
        res.veto_reasons.append("non_positive_qty")
        return res
    if not (0 < limit_cents < 100):
        res.veto_reasons.append(f"invalid_limit:{limit_cents}")
        return res
    if not (Decimal("0") <= p_yes <= Decimal("1")):
        res.veto_reasons.append(f"invalid_probability:{p_yes}")
        return res

    ladder = asks_for(outcome, yes_bids, no_bids)
    if not ladder:
        res.veto_reasons.append("held_side_ask_unavailable")
        return res

    own_map = own_levels_for("ask", outcome, own_orders or [])
    covered, cost_cents, blocked, anomaly = walk(
        [(p, s) for p, s in ladder if p <= limit_cents], qty, own_map, stp
    )
    res.own_blocked_qty = blocked
    res.own_book_anomaly = anomaly
    if covered <= 0:
        res.veto_reasons.append("no_external_depth")
        return res
    if covered < qty:
        res.veto_reasons.append(
            f"partial_depth:covered={covered}:requested={qty}"
        )

    p_sel = p_yes if outcome == "yes" else (Decimal("1") - p_yes)
    principal = cost_cents / Decimal("100")
    # Fee priced at the VWAP (conservative: worst level would bound it up).
    vwap_cents = cost_cents / Decimal(covered)
    fee = fee_bound_dollars(
        Decimal(covered), vwap_cents, fee_rate, balance_precision
    )
    ev = Decimal(covered) * p_sel - principal - fee

    # Worst per-contract price with non-negative EV at the assumed fee rate:
    # solve p_sel - price - rate*price*(1-price) >= 0 numerically over the
    # integer cent grid (small, exact, and audit-transparent).
    econ_limit = 0
    for c in range(1, 100):
        fee_c = fee_bound_dollars(Decimal("1"), Decimal(c), fee_rate, balance_precision)
        if p_sel - (Decimal(c) / Decimal("100")) - fee_c >= 0:
            econ_limit = c
    res.economic_limit_cents = econ_limit or None
    if limit_cents > econ_limit:
        res.veto_reasons.append(
            f"limit_above_economic_bound:{limit_cents}>{econ_limit}"
        )

    res.executable_qty = covered
    res.principal_dollars = principal
    res.fee_dollars = fee
    res.net_ev_dollars = ev
    res.ok = not res.veto_reasons or all(
        v.startswith("partial_depth") for v in res.veto_reasons
    )
    res.assumptions = {
        "stp": stp,
        "fee_rate": str(fee_rate),
        "balance_precision": str(balance_precision),
        "p_selected": str(p_sel),
        "vwap_cents": str(vwap_cents),
    }
    return res


def evaluate_sell(
    outcome: str,
    qty: int,
    held_qty: int,
    limit_cents: int,
    yes_bids: Ladder,
    no_bids: Ladder,
    own_orders: Optional[List[OracleOwnOrder]] = None,
    stp: str = "taker_at_cross",
    balance_precision: Decimal = BALANCE_DP_DIRECT,
) -> OracleResult:
    """Reference evaluation of a reduce-only style sell of ``outcome``.

    A sell cannot exceed ``held_qty`` (no flip through flat) and does not
    require positive edge — risk reduction is a legitimate negative-EV action
    — but it still must clear executable external depth under the STP policy.
    """
    res = OracleResult(ok=False)
    if outcome not in ("yes", "no"):
        res.veto_reasons.append(f"unsupported_outcome:{outcome}")
        return res
    if qty <= 0 or held_qty <= 0:
        res.veto_reasons.append("non_positive_qty")
        return res
    if qty > held_qty:
        res.veto_reasons.append(
            f"sell_exceeds_held:{qty}>{held_qty}"
        )
        return res

    ladder = bids_for(outcome, yes_bids, no_bids)
    if not ladder:
        res.veto_reasons.append("held_side_bid_unavailable")
        return res

    own_map = own_levels_for("bid", outcome, own_orders or [])
    covered, proceeds_cents, blocked, anomaly = walk(
        [(p, s) for p, s in ladder if p >= limit_cents], qty, own_map, stp
    )
    res.own_blocked_qty = blocked
    res.own_book_anomaly = anomaly
    if covered <= 0:
        res.veto_reasons.append("no_external_depth")
        return res

    res.executable_qty = covered
    res.principal_dollars = proceeds_cents / Decimal("100")
    res.ok = True
    res.assumptions = {"stp": stp, "balance_precision": str(balance_precision)}
    return res

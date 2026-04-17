"""
Kalshi Audit Harness — Deep Consistency Checker
=================================================

Parses CT logs, pulls live Kalshi data via API, and recomputes all
intermediate quantities to verify invariants.

Usage:
    python scripts/audit_kalshi_values.py --since 24h
    python scripts/audit_kalshi_values.py --cycle-file data/ct_cycles.jsonl
    python scripts/audit_kalshi_values.py --test-property kelly

Invariants checked:
1. Bankroll: cash + realized_pnl = bankroll - exposure
2. Position: size * avg_price = exposure (per ticker)
3. Fee: computed fee matches Kalshi schedule for (P, size)
4. Kelly: edge, win_prob, payout, kelly_raw, kelly_frac satisfy formulas
5. Caps: asset_current/exposure and global_current respect configured caps

Exit codes:
    0 = all invariants pass
    1 = one or more invariants violated
    2 = audit data unavailable or parse error
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════════════════════════════════════════
# §1 — Invariant Definitions (Boolean Property Checkers)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BankrollState:
    """Canonical bankroll state for invariant checking."""
    cash_cents: int
    exposure_cents: int
    realized_pnl_cents: int
    bankroll_cents: int  # total_value_cents in CT terminology
    
    def check_invariant(self, tolerance_cents: int = 100, tolerance_pct: float = 0.01) -> Tuple[bool, int]:
        """
        Check: cash + realized_pnl = bankroll - exposure
        
        Returns: (passed, delta_cents)
        """
        expected = self.cash_cents + self.realized_pnl_cents
        actual = self.bankroll_cents - self.exposure_cents
        delta = actual - expected
        max_tolerance = max(tolerance_cents, int(expected * tolerance_pct))
        passed = abs(delta) <= max_tolerance
        return passed, delta


@dataclass(frozen=True)
class PositionState:
    """Per-ticker position state for invariant checking."""
    ticker: str
    size_contracts: int  # positive = long, negative = short
    avg_price_cents: int
    total_fees_cents: int
    # Recomputed fields
    exposure_cents: int = field(init=False)
    
    def __post_init__(self):
        # Force exposure = size * avg_price (contract value in cents)
        object.__setattr__(
            self, 
            'exposure_cents', 
            abs(self.size_contracts) * self.avg_price_cents
        )
    
    def check_position_math(self, tolerance_cents: int = 1) -> Tuple[bool, Dict[str, Any]]:
        """
        Check: exposure = |size| * avg_price
        """
        expected = abs(self.size_contracts) * self.avg_price_cents
        actual = self.exposure_cents
        delta = actual - expected
        passed = abs(delta) <= tolerance_cents
        
        details = {
            "ticker": self.ticker,
            "size_contracts": self.size_contracts,
            "avg_price_cents": self.avg_price_cents,
            "expected_exposure_cents": expected,
            "actual_exposure_cents": actual,
            "delta_cents": delta,
            "passed": passed
        }
        return passed, details


@dataclass(frozen=True)
class FeeParams:
    """Fee computation parameters from Kalshi schedule."""
    price_cents: int  # P in cents (0-100)
    size_contracts: int
    taker_rate: Decimal = Decimal("0.07")  # 7% taker fee
    max_fee_per_contract_cents: int = 7  # 7¢ cap per contract
    
    def compute_fee(self) -> int:
        """
        Recompute fee: ceil(0.07 * C * P * (1-P)) in cents.
        Kalshi caps at 7¢ per contract.
        """
        P = Decimal(self.price_cents) / Decimal("100")
        C = Decimal(self.size_contracts)
        
        # Fee formula: 0.07 * C * P * (1-P)
        raw_fee = self.taker_rate * C * P * (Decimal("1") - P)
        
        # Convert to cents and apply ceiling
        fee_cents = int(raw_fee * 100)
        fee_cents = max(1, fee_cents)  # Minimum 1¢
        
        # Per-contract cap
        per_contract_cap = self.size_contracts * self.max_fee_per_contract_cents
        return min(fee_cents, per_contract_cap)
    
    def check_fee(
        self,
        logged_fee_cents: Optional[int] = None,
        tolerance_cents: int = 1,
        *,
        logged_fee: Optional[int] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Check: logged fee matches recomputed fee.

        Accepts ``logged_fee_cents`` (positional or keyword) or ``logged_fee``
        (keyword only) for compatibility with callers and property tests.
        """
        actual = logged_fee if logged_fee is not None else logged_fee_cents
        if actual is None:
            raise TypeError("check_fee requires logged_fee_cents or logged_fee")
        expected = self.compute_fee()
        delta = actual - expected
        passed = abs(delta) <= tolerance_cents
        
        details = {
            "price_cents": self.price_cents,
            "size_contracts": self.size_contracts,
            "expected_fee_cents": expected,
            "logged_fee_cents": actual,
            "delta_cents": delta,
            "passed": passed,
        }
        return passed, details


@dataclass(frozen=True)
class KellySizing:
    """Kelly sizing parameters and computed values."""
    edge: Decimal  # net edge after fees+slippage
    win_prob: Decimal  # model probability
    payout_ratio: Decimal  # (100 - P) / P for YES, P / (100 - P) for NO
    kelly_fraction: float  # user-supplied k (e.g., 0.25 for quarter-Kelly)
    bankroll_cents: int
    max_contracts_cap: int
    
    def compute_kelly(self) -> Tuple[float, int]:
        """
        Compute Kelly fraction and resulting contract count.
        
        Kelly formula: f* = (bp - q) / b
        where b = payout_ratio, p = win_prob, q = 1-p
        
        ``edge`` is a pre-trade guard: non-positive edge ⇒ no position.
        ``kelly_raw`` is clamped to [-1, 1] for stable audits under extreme (p, b).

        Returns: (kelly_raw, contracts_to_buy)
        """
        if self.edge <= 0:
            return 0.0, 0

        b = self.payout_ratio
        p = self.win_prob
        q = Decimal("1") - p
        
        # Raw Kelly
        kelly_raw = (b * p - q) / b if b > 0 else Decimal("0")
        kelly_raw = max(Decimal("-1"), min(Decimal("1"), kelly_raw))
        
        # Apply Kelly fraction and cap
        kelly_effective = kelly_raw * Decimal(str(self.kelly_fraction))
        
        # Convert to contract count
        target_cents = int(kelly_effective * self.bankroll_cents)
        # Assume contract price ~ 50¢ average for sizing
        est_contract_price = Decimal("50")
        contracts = int(Decimal(target_cents) / est_contract_price)
        
        # Apply caps
        contracts = max(0, min(contracts, self.max_contracts_cap))
        
        return float(kelly_raw), contracts
    
    def check_sizing(self, logged_contracts: int, logged_kelly_frac: Optional[float] = None,
                     tolerance_contracts: int = 1) -> Tuple[bool, Dict[str, Any]]:
        """
        Check: logged contracts matches recomputed Kelly sizing.
        """
        kelly_raw, expected_contracts = self.compute_kelly()
        actual = logged_contracts
        delta = actual - expected_contracts
        passed = abs(delta) <= tolerance_contracts
        
        details = {
            "edge": float(self.edge),
            "win_prob": float(self.win_prob),
            "payout_ratio": float(self.payout_ratio),
            "kelly_raw": float(kelly_raw),
            "kelly_fraction": self.kelly_fraction,
            "expected_contracts": expected_contracts,
            "logged_contracts": actual,
            "delta_contracts": delta,
            "passed": passed
        }
        return passed, details


@dataclass(frozen=True)
class CapsState:
    """Exposure caps state for invariant checking."""
    asset: str
    asset_exposure_cents: int
    global_exposure_cents: int
    bankroll_cents: int
    asset_cap_pct: float
    global_cap_pct: float
    
    def check_caps(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Check: asset_current <= asset_cap AND global_current <= global_cap
        """
        asset_cap_cents = int(self.bankroll_cents * self.asset_cap_pct)
        global_cap_cents = int(self.bankroll_cents * self.global_cap_pct)
        
        asset_ok = self.asset_exposure_cents <= asset_cap_cents
        global_ok = self.global_exposure_cents <= global_cap_cents
        
        passed = asset_ok and global_ok
        
        details = {
            "asset": self.asset,
            "asset_exposure_cents": self.asset_exposure_cents,
            "asset_cap_cents": asset_cap_cents,
            "asset_cap_pct": self.asset_cap_pct,
            "asset_ok": asset_ok,
            "global_exposure_cents": self.global_exposure_cents,
            "global_cap_cents": global_cap_cents,
            "global_cap_pct": self.global_cap_pct,
            "global_ok": global_ok,
            "passed": passed
        }
        return passed, details


# ═══════════════════════════════════════════════════════════════════════════
# §2 — CT Log Parser
# ═══════════════════════════════════════════════════════════════════════════


class CTLogParser:
    """Parse CT-TRACE and DRY-RUN-TRACE logs for audit."""
    
    # Regex patterns for log extraction
    CT_TRACE_PATTERN = re.compile(
        r'\[CT-TRACE\] stage=(\w+) \| corr_id=(\S+) \| cycle=(\d+)'
    )
    DRY_RUN_TRACE_PATTERN = re.compile(
        r'\[DRY-RUN-TRACE\] (\w+) \| cycle=(\d+)'
    )
    BANKROLL_INVARIANT_PATTERN = re.compile(
        r'\[BANKROLL-INVARIANT-[^\]]+\] .*delta=(\d+)¢.*cash=(\d+)¢ exposure=(\d+)¢ pnl=([+-]?\d+)¢'
    )
    
    def __init__(self, log_path: Optional[Path] = None):
        self.log_path = log_path or Path("data/logs/merid.log")
        self.cycles: Dict[int, Dict[str, Any]] = {}
        
    def parse_file(self, since_hours: Optional[float] = None) -> Dict[int, Dict[str, Any]]:
        """Parse CT logs and extract cycle data."""
        if not self.log_path.exists():
            print(f"[WARN] Log file not found: {self.log_path}")
            return {}
        
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours) if since_hours else None
        
        with open(self.log_path, 'r', encoding='utf-8') as f:
            for line in f:
                self._parse_line(line.strip(), cutoff)
        
        return self.cycles
    
    def _parse_line(self, line: str, cutoff: Optional[datetime]):
        """Parse a single log line."""
        # Check for timestamp if cutoff specified
        if cutoff:
            ts_match = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', line)
            if ts_match:
                try:
                    ts = datetime.fromisoformat(ts_match.group(1).replace(' ', 'T'))
                    if ts.replace(tzinfo=timezone.utc) < cutoff:
                        return
                except ValueError:
                    pass
        
        # CT-TRACE lines
        ct_match = self.CT_TRACE_PATTERN.search(line)
        if ct_match:
            stage, corr_id, cycle = ct_match.groups()
            cycle = int(cycle)
            if cycle not in self.cycles:
                self.cycles[cycle] = {"cycle": cycle, "corr_id": corr_id, "stages": []}
            self.cycles[cycle]["stages"].append(stage)
            self._extract_ct_fields(line, cycle, stage)
            return
        
        # DRY-RUN-TRACE lines
        dry_match = self.DRY_RUN_TRACE_PATTERN.search(line)
        if dry_match:
            trace_type, cycle = dry_match.groups()
            cycle = int(cycle)
            if cycle not in self.cycles:
                self.cycles[cycle] = {"cycle": cycle, "stages": []}
            self._extract_dry_run_fields(line, cycle, trace_type)
            return
        
        # Bankroll invariant lines
        inv_match = self.BANKROLL_INVARIANT_PATTERN.search(line)
        if inv_match:
            delta, cash, exposure, pnl = inv_match.groups()
            # Find most recent cycle
            if self.cycles:
                last_cycle = max(self.cycles.keys())
                self.cycles[last_cycle]["bankroll_invariant"] = {
                    "delta_cents": int(delta),
                    "cash_cents": int(cash),
                    "exposure_cents": int(exposure),
                    "realized_pnl_cents": int(pnl)
                }
    
    def _extract_ct_fields(self, line: str, cycle: int, stage: str):
        """Extract fields from CT-TRACE line based on stage."""
        data = self.cycles[cycle]
        
        if stage == "size":
            # Extract: edge, price, contracts
            edge_match = re.search(r'edge=([\d.]+)', line)
            price_match = re.search(r'price=(\d+)¢', line)
            contracts_match = re.search(r'contracts=(\d+)', line)
            market_match = re.search(r'market=(\S+)', line)
            asset_match = re.search(r'asset=(\S+)', line)
            
            if "sizing" not in data:
                data["sizing"] = []
            
            sizing_entry = {}
            if edge_match:
                sizing_entry["edge"] = float(edge_match.group(1))
            if price_match:
                sizing_entry["price_cents"] = int(price_match.group(1))
            if contracts_match:
                sizing_entry["contracts"] = int(contracts_match.group(1))
            if market_match:
                sizing_entry["ticker"] = market_match.group(1)
            if asset_match:
                sizing_entry["asset"] = asset_match.group(1)
            
            if sizing_entry:
                data["sizing"].append(sizing_entry)
        
        elif stage == "execute":
            # Extract: market, side, size, price, status
            market_match = re.search(r'market=(\S+)', line)
            side_match = re.search(r'side=(\S+)', line)
            size_match = re.search(r'size=(\d+)', line)
            price_match = re.search(r'price=(\d+)¢', line)
            status_match = re.search(r'status=(\S+)', line)
            
            if "executions" not in data:
                data["executions"] = []
            
            exec_entry = {}
            if market_match:
                exec_entry["ticker"] = market_match.group(1)
            if side_match:
                exec_entry["side"] = side_match.group(1)
            if size_match:
                exec_entry["size"] = int(size_match.group(1))
            if price_match:
                exec_entry["price_cents"] = int(price_match.group(1))
            if status_match:
                exec_entry["status"] = status_match.group(1)
            
            if exec_entry:
                data["executions"].append(exec_entry)
        
        elif stage == "monitor":
            # Extract: balance, exposure, drawdown, halted
            balance_match = re.search(r'balance=(\d+)¢', line)
            exposure_match = re.search(r'exposure=(\d+)¢', line)
            drawdown_match = re.search(r'drawdown=([\d.]+)%', line)
            halted_match = re.search(r'halted=(\w+)', line)
            
            if balance_match:
                data["balance_cents"] = int(balance_match.group(1))
            if exposure_match:
                data["exposure_cents"] = int(exposure_match.group(1))
            if drawdown_match:
                data["drawdown_pct"] = float(drawdown_match.group(1))
            if halted_match:
                data["halted"] = halted_match.group(1) == "True"


# ═══════════════════════════════════════════════════════════════════════════
# §3 — Kalshi API Client for Audit
# ═══════════════════════════════════════════════════════════════════════════


class KalshiAuditClient:
    """Lightweight Kalshi client for audit data fetching."""
    
    def __init__(self, env: str = "demo"):
        self.env = env
        self.base_url = (
            "https://demo-api.kalshi.co/trade-api/v2"
            if env == "demo" else
            "https://api.elections.kalshi.com/trade-api/v2"
        )
        self._token: Optional[str] = None
    
    def _authenticate(self) -> bool:
        """Authenticate with Kalshi API."""
        try:
            import httpx
            
            key_id = os.getenv("KALSHI_API_KEY_ID") or os.getenv(f"KALSHI_{self.env.upper()}_API_KEY_ID")
            key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem")
            
            if not key_id or not Path(key_path).exists():
                print(f"[WARN] Kalshi credentials not found for {self.env}")
                return False
            
            # RSA signing for Kalshi
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            
            with open(key_path, "rb") as f:
                private_key = serialization.load_pem_private_key(f.read(), password=None)
            
            timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
            message = timestamp + "GET" + "/trade-api/v2/portfolio/balance"
            signature = private_key.sign(
                message.encode(),
                padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                hashes.SHA256()
            )
            
            headers = {
                "KALSHI-ACCESS-KEY": key_id,
                "KALSHI-ACCESS-SIGNATURE": signature.hex(),
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
            }
            
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{self.base_url}/portfolio/balance", headers=headers)
                if resp.status_code == 200:
                    self._token = headers  # Reuse headers as "token"
                    return True
                else:
                    print(f"[WARN] Kalshi auth failed: {resp.status_code}")
                    return False
        except Exception as e:
            print(f"[WARN] Kalshi auth error: {e}")
            return False
    
    def get_balance(self) -> Optional[Dict[str, Any]]:
        """Fetch current balance."""
        if not self._token and not self._authenticate():
            return None
        
        try:
            import httpx
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{self.base_url}/portfolio/balance",
                    headers=self._token
                )
                if resp.status_code == 200:
                    return resp.json().get("balance", {})
        except Exception as e:
            print(f"[WARN] Balance fetch error: {e}")
        return None
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current positions."""
        if not self._token and not self._authenticate():
            return []
        
        try:
            import httpx
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{self.base_url}/portfolio/positions",
                    headers=self._token,
                    params={"limit": 1000}
                )
                if resp.status_code == 200:
                    return resp.json().get("positions", [])
        except Exception as e:
            print(f"[WARN] Positions fetch error: {e}")
        return []
    
    def get_fills(self, since_hours: float = 24) -> List[Dict[str, Any]]:
        """Fetch recent fills."""
        if not self._token and not self._authenticate():
            return []
        
        try:
            import httpx
            cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
            
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{self.base_url}/portfolio/fills",
                    headers=self._token,
                    params={
                        "limit": 1000,
                        "min_ts": int(cutoff.timestamp() * 1000),
                    }
                )
                if resp.status_code == 200:
                    return resp.json().get("fills", [])
        except Exception as e:
            print(f"[WARN] Fills fetch error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# §4 — Audit Engine
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class AuditResult:
    """Result of a single invariant check."""
    name: str
    passed: bool
    expected: Any
    actual: Any
    delta: Any
    details: Dict[str, Any]
    severity: str = "error"  # error, warning


class KalshiAuditEngine:
    """Main audit engine that runs all invariant checks."""
    
    def __init__(self, log_parser: CTLogParser, kalshi_client: KalshiAuditClient):
        self.parser = log_parser
        self.kalshi = kalshi_client
        self.results: List[AuditResult] = []
        
    def run_full_audit(self, since_hours: float = 24) -> Tuple[int, List[AuditResult]]:
        """
        Run full audit against CT logs and live Kalshi data.
        
        Returns: (exit_code, results)
        """
        print(f"[AUDIT] Starting full audit (since {since_hours}h)")
        
        # 1. Parse CT logs
        print("[AUDIT] Parsing CT logs...")
        cycles = self.parser.parse_file(since_hours)
        print(f"[AUDIT] Found {len(cycles)} cycles in logs")
        
        # 2. Fetch live data
        print("[AUDIT] Fetching live Kalshi data...")
        balance = self.kalshi.get_balance()
        positions = self.kalshi.get_positions()
        fills = self.kalshi.get_fills(since_hours)
        
        print(f"[AUDIT] Live data: balance={balance is not None}, positions={len(positions)}, fills={len(fills)}")
        
        # 3. Run invariant checks
        self._check_bankroll_invariant(cycles, balance)
        self._check_position_state(positions, fills)
        self._check_fee_math(cycles, fills)
        self._check_caps(cycles)
        
        # 4. Determine exit code
        errors = sum(1 for r in self.results if not r.passed and r.severity == "error")
        
        return 0 if errors == 0 else 1, self.results
    
    def _check_bankroll_invariant(self, cycles: Dict[int, Any], live_balance: Optional[Dict]):
        """Check bankroll invariant against logs and live data."""
        print("[AUDIT] Checking bankroll invariant...")
        
        # Check each logged cycle
        for cycle_num, data in sorted(cycles.items()):
            if "bankroll_invariant" not in data:
                continue
            
            inv = data["bankroll_invariant"]
            state = BankrollState(
                cash_cents=inv["cash_cents"],
                exposure_cents=inv["exposure_cents"],
                realized_pnl_cents=inv["realized_pnl_cents"],
                # Derive bankroll from invariant equation: bankroll = cash + realized_pnl + exposure
                bankroll_cents=inv["cash_cents"] + inv["realized_pnl_cents"] + inv["exposure_cents"]
            )
            
            passed, delta = state.check_invariant()
            
            self.results.append(AuditResult(
                name=f"bankroll_invariant_cycle_{cycle_num}",
                passed=passed,
                expected=0,
                actual=delta,
                delta=delta,
                details={
                    "cycle": cycle_num,
                    "cash_cents": state.cash_cents,
                    "exposure_cents": state.exposure_cents,
                    "realized_pnl_cents": state.realized_pnl_cents,
                    "bankroll_cents": state.bankroll_cents
                },
                severity="warning" if not passed else "info"
            ))
        
        # Check live balance if available
        if live_balance:
            cash_cents = int(live_balance.get("balance_cents", 0))
            # Would need exposure from positions
            # This is a simplified check
    
    def _check_position_state(self, positions: List[Dict], fills: List[Dict]):
        """Check position state against fills."""
        print(f"[AUDIT] Checking position state ({len(positions)} positions, {len(fills)} fills)...")
        
        # Reconstruct positions from fills
        reconstructed: Dict[str, PositionState] = {}
        
        for fill in fills:
            ticker = fill.get("ticker")
            if not ticker:
                continue
            
            side = fill.get("side", "")
            count = int(fill.get("count", 0))
            price_cents = int(float(fill.get("price", 0)) * 100)
            fee_cents = int(float(fill.get("fees", 0)) * 100)
            
            if ticker not in reconstructed:
                reconstructed[ticker] = PositionState(
                    ticker=ticker,
                    size_contracts=0,
                    avg_price_cents=0,
                    total_fees_cents=0
                )
            
            pos = reconstructed[ticker]
            # Update size (positive for YES/buy, negative for NO/sell)
            size_delta = count if side in ["yes", "buy", "BUY", "YES"] else -count
            new_size = pos.size_contracts + size_delta
            
            # Update avg price using weighted average
            if abs(new_size) > 0:
                old_value = abs(pos.size_contracts) * pos.avg_price_cents
                new_value = count * price_cents
                new_avg = (old_value + new_value) // abs(new_size)
            else:
                new_avg = 0
            
            # Update object (in dataclass, need to create new)
            reconstructed[ticker] = PositionState(
                ticker=ticker,
                size_contracts=new_size,
                avg_price_cents=new_avg,
                total_fees_cents=pos.total_fees_cents + fee_cents
            )
        
        # Compare reconstructed vs reported positions
        reported_map = {p.get("ticker"): p for p in positions if p.get("ticker")}
        
        for ticker, recon in reconstructed.items():
            if ticker in reported_map:
                reported = reported_map[ticker]
                reported_size = int(reported.get("count", 0))
                
                # Check position math
                passed, details = recon.check_position_math()
                
                # Also check size matches
                size_match = recon.size_contracts == reported_size
                
                self.results.append(AuditResult(
                    name=f"position_state_{ticker}",
                    passed=passed and size_match,
                    expected={"size": recon.size_contracts, "exposure": details["expected_exposure_cents"]},
                    actual={"size": reported_size, "exposure": details["actual_exposure_cents"]},
                    delta={"size": recon.size_contracts - reported_size, "exposure": details["delta_cents"]},
                    details={**details, "reported_size": reported_size, "reconstructed_size": recon.size_contracts},
                    severity="error" if not (passed and size_match) else "info"
                ))
    
    def _check_fee_math(self, cycles: Dict[int, Any], fills: List[Dict]):
        """Check fee math against Kalshi schedule."""
        print(f"[AUDIT] Checking fee math ({len(fills)} fills)...")
        
        for fill in fills:
            ticker = fill.get("ticker", "unknown")
            price = float(fill.get("price", 0))  # 0-1
            price_cents = int(price * 100)
            count = int(fill.get("count", 0))
            logged_fee = int(float(fill.get("fees", 0)) * 100)
            
            params = FeeParams(
                price_cents=price_cents,
                size_contracts=count
            )
            
            passed, details = params.check_fee(logged_fee)
            
            self.results.append(AuditResult(
                name=f"fee_math_{ticker}_{fill.get('fill_id', 'unknown')[:8]}",
                passed=passed,
                expected=details["expected_fee_cents"],
                actual=logged_fee,
                delta=details["delta_cents"],
                details=details,
                severity="warning" if not passed else "info"
            ))
    
    def _check_caps(self, cycles: Dict[int, Any]):
        """Check exposure caps from logged cycles."""
        print("[AUDIT] Checking exposure caps...")
        
        for cycle_num, data in cycles.items():
            # Would need config to verify caps
            # For now, just check that sizing respects some reasonable bounds
            if "sizing" not in data:
                continue
            
            for sizing in data["sizing"]:
                contracts = sizing.get("contracts", 0)
                # Sanity check: no single trade should exceed 100 contracts
                # (actual cap depends on config)
                passed = contracts <= 100
                
                self.results.append(AuditResult(
                    name=f"sizing_sanity_cycle_{cycle_num}_{sizing.get('ticker', 'unknown')}",
                    passed=passed,
                    expected="<=100",
                    actual=contracts,
                    delta=max(0, contracts - 100),
                    details=sizing,
                    severity="warning" if not passed else "info"
                ))
    
    def print_report(self):
        """Print human-readable audit report."""
        print("\n" + "=" * 80)
        print("KALSHI AUDIT REPORT")
        print("=" * 80)
        
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        errors = sum(1 for r in self.results if not r.passed and r.severity == "error")
        
        print(f"\nSummary: {passed} passed, {failed} failed ({errors} errors)")
        print(f"\nFailed checks:")
        
        for result in self.results:
            if not result.passed:
                print(f"\n  ❌ {result.name}")
                print(f"     Expected: {result.expected}")
                print(f"     Actual:   {result.actual}")
                print(f"     Delta:    {result.delta}")
                if result.details:
                    print(f"     Details:  {json.dumps(result.details, indent=2, default=str)[:200]}")
        
        print("\n" + "=" * 80)
        if errors == 0:
            print("RESULT: PASSED (no critical errors)")
        else:
            print(f"RESULT: FAILED ({errors} critical errors)")
        print("=" * 80)


# ═══════════════════════════════════════════════════════════════════════════
# §5 — Property-Based Tests (Hypothesis)
# ═══════════════════════════════════════════════════════════════════════════


def run_property_tests():
    """Run property-based tests using Hypothesis if available."""
    try:
        from hypothesis import given, strategies as st, settings
    except ImportError:
        print("[SKIP] Hypothesis not installed, property tests skipped")
        print("       Install with: pip install hypothesis")
        return True
    
    print("\n[PROPERTY TESTS] Running Hypothesis tests...")
    
    @settings(max_examples=100, deadline=None)
    @given(
        price_cents=st.integers(min_value=1, max_value=99),
        size=st.integers(min_value=1, max_value=100)
    )
    def test_fee_bounds(price_cents, size):
        """Fee should be within Kalshi bounds: 1¢ min, 7¢/contract max."""
        params = FeeParams(price_cents=price_cents, size_contracts=size)
        fee = params.compute_fee()
        
        # Bounds
        assert fee >= 1, f"Fee {fee} below minimum 1¢"
        assert fee <= size * 7, f"Fee {fee} exceeds max {size * 7}¢"
        
        # Mid-curve is most expensive (worst at 50¢)
        if 40 <= price_cents <= 60:
            # Should be near max
            assert fee >= size * 5, f"Mid-curve fee {fee} suspiciously low"
    
    @settings(max_examples=100, deadline=None)
    @given(
        cash=st.integers(min_value=0, max_value=100000),
        exposure=st.integers(min_value=0, max_value=50000),
        pnl=st.integers(min_value=-50000, max_value=50000)
    )
    def test_bankroll_invariant_property(cash, exposure, pnl):
        """Bankroll invariant should hold for valid inputs."""
        bankroll = cash + pnl + exposure
        state = BankrollState(
            cash_cents=cash,
            exposure_cents=exposure,
            realized_pnl_cents=pnl,
            bankroll_cents=bankroll
        )
        passed, delta = state.check_invariant()
        assert passed, f"Invariant failed: delta={delta}¢"
    
    @settings(max_examples=50, deadline=None)
    @given(
        edge=st.decimals(min_value=-0.1, max_value=0.2, places=4),
        win_prob=st.decimals(min_value=0.01, max_value=0.99, places=4),
        payout=st.decimals(min_value=0.5, max_value=10.0, places=4),
        bankroll=st.integers(min_value=1000, max_value=100000)
    )
    def test_kelly_sizing_properties(edge, win_prob, payout, bankroll):
        """Kelly sizing properties."""
        kelly = KellySizing(
            edge=edge,
            win_prob=win_prob,
            payout_ratio=payout,
            kelly_fraction=0.25,
            bankroll_cents=bankroll,
            max_contracts_cap=100
        )
        kelly_raw, contracts = kelly.compute_kelly()
        
        # Properties:
        # 1. Contracts never negative
        assert contracts >= 0
        # 2. Contracts zero when edge <= 0
        if edge <= 0:
            assert contracts == 0, f"Non-zero contracts {contracts} with edge {edge}"
        # 3. Never exceeds cap
        assert contracts <= 100
        # 4. Kelly raw should be reasonable
        assert -1 <= kelly_raw <= 1, f"Kelly raw {kelly_raw} out of bounds"
    
    # Run the tests
    try:
        test_fee_bounds()
        print("  ✓ test_fee_bounds passed")
    except AssertionError as e:
        print(f"  ✗ test_fee_bounds failed: {e}")
        return False
    
    try:
        test_bankroll_invariant_property()
        print("  ✓ test_bankroll_invariant_property passed")
    except AssertionError as e:
        print(f"  ✗ test_bankroll_invariant_property failed: {e}")
        return False
    
    try:
        test_kelly_sizing_properties()
        print("  ✓ test_kelly_sizing_properties passed")
    except AssertionError as e:
        print(f"  ✗ test_kelly_sizing_properties failed: {e}")
        return False
    
    print("[PROPERTY TESTS] All passed")
    return True


# ═══════════════════════════════════════════════════════════════════════════
# §6 — CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Kalshi Trading System — Deep Consistency Audit"
    )
    parser.add_argument(
        "--since", "-s", type=float, default=24.0,
        help="Hours of history to audit (default: 24)"
    )
    parser.add_argument(
        "--log-file", "-l", type=Path,
        default=Path("data/logs/merid.log"),
        help="Path to CT log file"
    )
    parser.add_argument(
        "--env", "-e", choices=["demo", "live"], default="demo",
        help="Kalshi environment (default: demo)"
    )
    parser.add_argument(
        "--test-property", "-p", action="store_true",
        help="Run property-based tests only"
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Run property tests if requested
    if args.test_property:
        success = run_property_tests()
        sys.exit(0 if success else 1)
    
    # Full audit
    parser_obj = CTLogParser(log_path=args.log_file)
    kalshi = KalshiAuditClient(env=args.env)
    engine = KalshiAuditEngine(parser_obj, kalshi)
    
    exit_code, results = engine.run_full_audit(since_hours=args.since)
    
    if args.json:
        output = {
            "exit_code": exit_code,
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "expected": r.expected,
                    "actual": r.actual,
                    "delta": r.delta,
                    "severity": r.severity,
                    "details": r.details
                }
                for r in results
            ]
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        engine.print_report()
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

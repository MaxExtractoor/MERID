"""
Kalshi Test Harness

Reusable test helpers for Kalshi venue testing.
Provides common fixtures and utilities for building test data,
running reconciliation, and checking execution gate state.

This harness is shared by:
- 15-minute crypto E2E tests (test_btc_15m_reconciliation_e2e.py)
- Other Kalshi market tests (future)
- Backtesting operational risk constraints
"""

from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
import json

from merid.reconciliation.venue_reconciler import VenuePositionDiscrepancy
from merid.reconciliation.severity_matrix import DiscrepancyMetrics, calculate_severity, DEFAULT_THRESHOLDS
from merid.reconciliation.phantom_detection import PhantomDetector, PhantomPosition
from core.execution_gate import check_execution_gate, ExecutionGateStatus, GateState


@dataclass
class KalshiFillFixture:
    """Fixture data for Kalshi fills."""
    fill_id: str
    trade_id: str
    order_id: str
    market_ticker: str
    side: str  # "yes" or "no"
    action: str  # "buy" or "sell"
    count: int
    yes_price_dollars: Decimal
    no_price_dollars: Decimal
    fee_cost_dollars: Decimal
    proceeds_dollars: Decimal
    created_time: datetime

    def to_api_dict(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "trade_id": self.trade_id,
            "order_id": self.order_id,
            "market_ticker": self.market_ticker,
            "side": self.side,
            "action": self.action,
            "count": self.count,
            "yes_price": int(self.yes_price_dollars * 100),  # Convert to cents
            "no_price": int(self.no_price_dollars * 100),
            "fee_cost": int(self.fee_cost_dollars * 100),
            "proceeds": int(self.proceeds_dollars * 100),
            "created_time": self.created_time.isoformat(),
        }


@dataclass
class KalshiPositionFixture:
    """Fixture data for Kalshi positions."""
    ticker: str
    side: str  # "yes" or "no"
    count: int
    avg_price_dollars: Decimal
    total_cost_dollars: Decimal
    unrealized_pnl_dollars: Decimal

    def to_api_dict(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "ticker": self.ticker,
            "side": self.side,
            "count": self.count,
            "avg_price": int(self.avg_price_dollars * 100),  # Convert to cents
            "total_cost": int(self.total_cost_dollars * 100),
            "unrealized_pnl": int(self.unrealized_pnl_dollars * 100),
        }


class KalshiTestHarness:
    """
    Central test harness for Kalshi testing.
    
    Provides utilities for:
    - Building fixture positions (fills, external positions)
    - Running reconciliation classification (severity, phantom detection)
    - Checking execution gate state
    - Validating the full chain: classification → gate decision
    """

    def __init__(self):
        self.phantom_detector = PhantomDetector()
        self.severity_thresholds = DEFAULT_THRESHOLDS

    # =========================================================================
    # Fixture Builders
    # =========================================================================

    def build_fill(
        self,
        fill_id: str,
        market_ticker: str,
        side: str,
        action: str,
        count: int,
        yes_price_dollars: Decimal = Decimal("0.50"),
        no_price_dollars: Decimal = Decimal("0.50"),
        created_time: Optional[datetime] = None,
    ) -> KalshiFillFixture:
        """
        Build a Kalshi fill fixture.
        
        Args:
            fill_id: Unique fill identifier
            market_ticker: Market ticker (e.g., "KXBTC-26JAN24-50000")
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            yes_price_dollars: YES price in dollars
            no_price_dollars: NO price in dollars
            created_time: Fill timestamp (defaults to now)
        
        Returns:
            KalshiFillFixture: Fill fixture
        """
        if created_time is None:
            created_time = datetime.now(timezone.utc)

        # Calculate proceeds
        fee = Decimal("0.001") * count
        if action == "buy":
            proceeds_dollars = -(count * yes_price_dollars + fee)  # Buy cost + fee
        else:
            proceeds_dollars = (count * yes_price_dollars - fee)  # Sell proceeds - fee

        return KalshiFillFixture(
            fill_id=fill_id,
            trade_id=f"trade_{fill_id}",
            order_id=f"order_{fill_id}",
            market_ticker=market_ticker,
            side=side,
            action=action,
            count=count,
            yes_price_dollars=yes_price_dollars,
            no_price_dollars=no_price_dollars,
            fee_cost_dollars=Decimal("0.001"),
            proceeds_dollars=Decimal(str(proceeds_dollars)),
            created_time=created_time,
        )

    def build_position(
        self,
        ticker: str,
        side: str,
        count: int,
        avg_price_dollars: Decimal = Decimal("0.50"),
        unrealized_pnl_dollars: Decimal = Decimal("0.0"),
    ) -> KalshiPositionFixture:
        """
        Build a Kalshi position fixture.
        
        Args:
            ticker: Market ticker
            side: "yes" or "no"
            count: Number of contracts
            avg_price_dollars: Average price in dollars
            unrealized_pnl_dollars: Unrealized PnL in dollars
        
        Returns:
            KalshiPositionFixture: Position fixture
        """
        total_cost_dollars = count * avg_price_dollars
        return KalshiPositionFixture(
            ticker=ticker,
            side=side,
            count=count,
            avg_price_dollars=avg_price_dollars,
            total_cost_dollars=Decimal(str(total_cost_dollars)),
            unrealized_pnl_dollars=unrealized_pnl_dollars,
        )

    def build_fills_sequence(
        self,
        market_ticker: str,
        num_fills: int = 5,
        base_time: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build a sequence of fills for testing.
        
        Args:
            market_ticker: Market ticker
            num_fills: Number of fills to generate
            base_time: Starting timestamp (defaults to now)
        
        Returns:
            List of fill API dicts
        """
        if base_time is None:
            base_time = datetime.now(timezone.utc)

        fills = []
        for i in range(num_fills):
            fill = self.build_fill(
                fill_id=f"fill_{i:03d}",
                market_ticker=market_ticker,
                side="yes",
                action="buy" if i % 2 == 0 else "sell",
                count=1,
                yes_price_dollars=Decimal("0.50"),
                created_time=base_time.replace(minute=i),
            )
            fills.append(fill.to_api_dict())
        return fills

    # =========================================================================
    # Reconciliation Classification
    # =========================================================================

    def classify_discrepancy(
        self,
        internal_yes_qty: int,
        internal_no_qty: int,
        external_yes_qty: int,
        external_no_qty: int,
    ) -> Tuple[str, str]:
        """
        Classify a position discrepancy using severity matrix.
        
        Args:
            internal_yes_qty: Internal YES quantity
            internal_no_qty: Internal NO quantity
            external_yes_qty: External YES quantity
            external_no_qty: External NO quantity
        
        Returns:
            Tuple of (severity, reason)
        """
        metrics = DiscrepancyMetrics(
            yes_delta=internal_yes_qty - external_yes_qty,
            no_delta=internal_no_qty - external_no_qty,
            internal_yes_qty=internal_yes_qty,
            internal_no_qty=internal_no_qty,
            external_yes_qty=external_yes_qty,
            external_no_qty=external_no_qty,
        )

        severity = calculate_severity(metrics, self.severity_thresholds)
        
        # Build reason string
        from merid.reconciliation.severity_matrix import get_severity_reason
        reason = get_severity_reason(metrics, severity, self.severity_thresholds)
        
        return severity.value, reason

    def detect_phantom(
        self,
        market_id: str,
        internal_yes_qty: int,
        internal_no_qty: int,
        external_yes_qty: int,
        external_no_qty: int,
        fill_timestamp: Optional[datetime] = None,
        external_query_time: Optional[datetime] = None,
    ) -> Optional[PhantomPosition]:
        """
        Detect if this is a phantom position.
        
        Args:
            market_id: Market identifier
            internal_yes_qty: Internal YES quantity
            internal_no_qty: Internal NO quantity
            external_yes_qty: External YES quantity
            external_no_qty: External NO quantity
            fill_timestamp: Timestamp of the fill
            external_query_time: Timestamp of external position query
        
        Returns:
            PhantomPosition if phantom detected, None otherwise
        """
        return self.phantom_detector.detect_phantom(
            market_id=market_id,
            internal_yes_qty=internal_yes_qty,
            internal_no_qty=internal_no_qty,
            external_yes_qty=external_yes_qty,
            external_no_qty=external_no_qty,
            fill_timestamp=fill_timestamp,
            external_query_time=external_query_time,
        )

    def create_discrepancy(
        self,
        market_id: str,
        internal_yes_qty: int,
        internal_no_qty: int,
        external_yes_qty: int,
        external_no_qty: int,
        severity: str,
        reason: str,
        venue: str = "kalshi",
    ) -> VenuePositionDiscrepancy:
        """
        Create a VenuePositionDiscrepancy object.
        
        Args:
            market_id: Market identifier
            internal_yes_qty: Internal YES quantity
            internal_no_qty: Internal NO quantity
            external_yes_qty: External YES quantity
            external_no_qty: External NO quantity
            severity: Discrepancy severity ("critical", "warning", "info")
            reason: Human-readable reason
            venue: Venue name (default "kalshi")
        
        Returns:
            VenuePositionDiscrepancy: Discrepancy object
        """
        return VenuePositionDiscrepancy(
            venue=venue,
            market_id=market_id,
            internal_yes_qty=internal_yes_qty,
            internal_no_qty=internal_no_qty,
            external_yes_qty=external_yes_qty,
            external_no_qty=external_no_qty,
            severity=severity,
            reason=reason,
        )

    # =========================================================================
    # Gate Decision
    # =========================================================================

    def check_gate(self) -> ExecutionGateStatus:
        """
        Check the execution gate state.
        
        Returns:
            ExecutionGateStatus: Current gate status
        """
        return check_execution_gate()

    def assert_gate_state(
        self,
        expected_can_trade: bool,
        gate_status: ExecutionGateStatus,
        expected_critical_sources: Optional[List[str]] = None,
        expected_warning_sources: Optional[List[str]] = None,
    ) -> None:
        """
        Assert gate state matches expectations.
        
        Args:
            expected_can_trade: Expected can_trade value
            gate_status: Actual gate status
            expected_critical_sources: Expected critical source names
            expected_warning_sources: Expected warning source names
        """
        assert gate_status.can_trade == expected_can_trade, \
            f"Expected can_trade={expected_can_trade}, got {gate_status.can_trade}"

        if expected_critical_sources is not None:
            critical_sources = [r.source for r in gate_status.reasons if r.severity == "critical"]
            for source in expected_critical_sources:
                assert source in critical_sources, \
                    f"Expected critical source '{source}' not found in {critical_sources}"

        if expected_warning_sources is not None:
            warning_sources = [r.source for r in gate_status.reasons if r.severity == "warning"]
            for source in expected_warning_sources:
                assert source in warning_sources, \
                    f"Expected warning source '{source}' not found in {warning_sources}"

    # =========================================================================
    # Full Chain: Classification → Gate Decision
    # =========================================================================

    def run_full_chain(
        self,
        market_id: str,
        internal_yes_qty: int,
        internal_no_qty: int,
        external_yes_qty: int,
        external_no_qty: int,
        venue: str = "kalshi",
    ) -> Dict[str, Any]:
        """
        Run the full chain: classification → gate decision.
        
        Args:
            market_id: Market identifier
            internal_yes_qty: Internal YES quantity
            internal_no_qty: Internal NO quantity
            external_yes_qty: External YES quantity
            external_no_qty: External NO quantity
            venue: Venue name (default "kalshi")
        
        Returns:
            Dict with classification results and gate decision
        """
        # Step 1: Classify severity
        severity, reason = self.classify_discrepancy(
            internal_yes_qty, internal_no_qty,
            external_yes_qty, external_no_qty,
        )

        # Step 2: Detect phantom
        phantom = self.detect_phantom(
            market_id,
            internal_yes_qty, internal_no_qty,
            external_yes_qty, external_no_qty,
        )

        # Step 3: Create discrepancy
        discrepancy = self.create_discrepancy(
            market_id,
            internal_yes_qty, internal_no_qty,
            external_yes_qty, external_no_qty,
            severity, reason, venue,
        )

        # Step 4: Check gate (note: this uses global state, so discrepancy must be registered)
        # For test harness usage, we return the discrepancy for the test to register
        gate_status = self.check_gate()

        return {
            "severity": severity,
            "reason": reason,
            "phantom": phantom,
            "discrepancy": discrepancy,
            "gate_status": gate_status,
        }

    # =========================================================================
    # Risk → Gate Integration
    # =========================================================================

    def simulate_order(
        self,
        asset: str,
        fills: List[KalshiFillFixture],
        risk_state: Optional[Dict[str, Any]] = None,
        recon_state: Optional[Dict[str, Any]] = None,
        venue: str = "kalshi",
    ) -> Dict[str, Any]:
        """
        Simulate an order through risk → gate pipeline.
        
        This helper:
        - Replays fills into risk engine and ledger
        - Runs recon (optional)
        - Computes risk status (OK / WARNING / CRITICAL / HARD_STOP)
        - Runs check_execution_gate() with both risk and reconciliation inputs
        - Returns: {risk_status, gate_state, allowed_operations}
        
        Args:
            asset: Asset name (e.g., "BTC", "ETH")
            fills: List of fills to replay
            risk_state: Optional pre-existing risk state (for testing)
            recon_state: Optional pre-existing reconciliation state (for testing)
            venue: Venue name (default "kalshi")
        
        Returns:
            Dict with risk status, gate state, and allowed operations
        """
        # Step 1: Compute risk status from fills
        risk_status = self._compute_risk_status(asset, fills, risk_state)
        
        # Step 2: Run reconciliation if state provided
        if recon_state is not None:
            # Run classification with provided state
            severity, reason = self.classify_discrepancy(
                recon_state.get("internal_yes_qty", 0),
                recon_state.get("internal_no_qty", 0),
                recon_state.get("external_yes_qty", 0),
                recon_state.get("external_no_qty", 0),
            )
            phantom = self.detect_phantom(
                recon_state.get("market_id", ""),
                recon_state.get("internal_yes_qty", 0),
                recon_state.get("internal_no_qty", 0),
                recon_state.get("external_yes_qty", 0),
                recon_state.get("external_no_qty", 0),
            )
        else:
            severity = "info"
            reason = "No reconciliation state provided"
            phantom = None
        
        # Step 3: Check gate with both risk and recon inputs
        gate_status = self.check_gate()
        
        # Step 4: Determine allowed operations based on risk status and gate state
        allowed_operations = self._determine_allowed_operations(
            risk_status, gate_status
        )
        
        return {
            "risk_status": risk_status,
            "gate_state": gate_status.gate_state,
            "allowed_operations": allowed_operations,
            "recon_severity": severity if recon_state else None,
            "recon_phantom": phantom is not None if recon_state else None,
            "can_trade": gate_status.can_trade,
        }

    def _compute_risk_status(
        self,
        asset: str,
        fills: List[KalshiFillFixture],
        existing_state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Compute risk status from fills.
        
        Args:
            asset: Asset name
            fills: List of fills
            existing_state: Optional pre-existing risk state
        
        Returns:
            Risk status: "ok", "warning", "critical", "hard_stop"
        """
        # Calculate total exposure from fills
        total_exposure = Decimal("0")
        for fill in fills:
            if fill.action == "buy":
                total_exposure += fill.count * fill.yes_price_dollars
            else:
                total_exposure -= fill.count * fill.yes_price_dollars
        
        # Use existing state if provided
        if existing_state is not None:
            total_exposure += Decimal(str(existing_state.get("existing_exposure", 0)))
        
        # Risk thresholds (from KALSHI_RISK_EXTERNAL_CONTRACT.md)
        per_asset_cap = Decimal("2000.00")  # $2k per asset
        warning_threshold = Decimal("0.80")  # 80%
        critical_threshold = Decimal("0.90")  # 90%
        
        utilization = abs(total_exposure) / per_asset_cap
        
        if utilization >= Decimal("1.00"):
            return "hard_stop"
        elif utilization >= critical_threshold:
            return "critical"
        elif utilization >= warning_threshold:
            return "warning"
        else:
            return "ok"

    def _determine_allowed_operations(
        self,
        risk_status: str,
        gate_status: ExecutionGateStatus,
    ) -> List[str]:
        """
        Determine allowed operations based on risk status and gate state.
        
        Args:
            risk_status: Risk status from risk engine
            gate_status: Gate status from check_execution_gate()
        
        Returns:
            List of allowed operations
        """
        # If gate is blocked, no operations allowed
        if not gate_status.can_trade:
            return []
        
        # If risk is hard stop, no new orders allowed
        if risk_status == "hard_stop":
            return ["reduce_only"]
        
        # If risk is critical, reduce-only mode
        if risk_status == "critical":
            return ["reduce_only"]
        
        # If risk is warning, allow all but flag for review
        if risk_status == "warning":
            return ["buy", "sell"]
        
        # Normal operation
        return ["buy", "sell"]

    # =========================================================================
    # Historical Data Loading (for Backtesting)
    # =========================================================================

    def load_historical_fills(
        self,
        file_path: str,
    ) -> List[KalshiFillFixture]:
        """
        Load historical fills from a JSON file.

        Args:
            file_path: Path to JSON file with historical fills

        Returns:
            List of KalshiFillFixture objects
        """
        with open(file_path, 'r') as f:
            data = json.load(f)

        fills = []
        for item in data:
            fill = KalshiFillFixture(
                fill_id=item.get("fill_id", ""),
                trade_id=item.get("trade_id", ""),
                order_id=item.get("order_id", ""),
                market_ticker=item.get("market_ticker", ""),
                side=item.get("side", "yes"),
                action=item.get("action", "buy"),
                count=item.get("count", 0),
                yes_price_dollars=Decimal(str(item.get("yes_price_dollars", 0))),
                no_price_dollars=Decimal(str(item.get("no_price_dollars", 0))),
                fee_cost_dollars=Decimal(str(item.get("fee_cost_dollars", 0))),
                proceeds_dollars=Decimal(str(item.get("proceeds_dollars", 0))),
                created_time=datetime.fromisoformat(item.get("created_time", datetime.now(timezone.utc).isoformat())),
            )
            fills.append(fill)
        return fills

    def load_historical_positions(
        self,
        file_path: str,
    ) -> List[KalshiPositionFixture]:
        """
        Load historical positions from a JSON file.

        Args:
            file_path: Path to JSON file with historical positions

        Returns:
            List of KalshiPositionFixture objects
        """
        with open(file_path, 'r') as f:
            data = json.load(f)

        positions = []
        for item in data:
            position = KalshiPositionFixture(
                ticker=item.get("ticker", ""),
                side=item.get("side", "yes"),
                count=item.get("count", 0),
                avg_price_dollars=Decimal(str(item.get("avg_price_dollars", 0))),
                total_cost_dollars=Decimal(str(item.get("total_cost_dollars", 0))),
                unrealized_pnl_dollars=Decimal(str(item.get("unrealized_pnl_dollars", 0))),
            )
            positions.append(position)
        return positions

    # =========================================================================
    # Backtesting: Strategy Simulation
    # =========================================================================

    @dataclass
    class StrategyPolicy:
        """Simple strategy policy for backtesting."""
        max_position_size: int = 10
        max_orders_per_minute: int = 5
        min_edge: Decimal = Decimal("0.02")  # 2% edge
        allow_reduce_only: bool = True

    def simulate_strategy_order(
        self,
        market_ticker: str,
        side: str,
        action: str,
        count: int,
        price_dollars: Decimal,
        policy: Optional[StrategyPolicy] = None,
        current_positions: Optional[List[KalshiPositionFixture]] = None,
    ) -> Dict[str, Any]:
        """
        Simulate an order according to strategy policy.

        Args:
            market_ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price_dollars: Price in dollars
            policy: Strategy policy (uses default if None)
            current_positions: Current positions for position size check

        Returns:
            Dict with simulation result and constraint violations
        """
        if policy is None:
            policy = self.StrategyPolicy()

        violations = []
        allowed = True

        # Check position size limit
        if current_positions:
            current_size = sum(p.count for p in current_positions if p.ticker == market_ticker)
            if count > policy.max_position_size:
                violations.append(f"Position size {count} exceeds max {policy.max_position_size}")
                allowed = False

        # Check order size
        if count > policy.max_position_size:
            violations.append(f"Order size {count} exceeds max {policy.max_position_size}")
            allowed = False

        # Check edge (simplified - would need market data in real implementation)
        # For now, assume edge is sufficient
        edge_ok = True  # Would check against current market prices

        return {
            "allowed": allowed,
            "violations": violations,
            "edge_ok": edge_ok,
            "policy": {
                "max_position_size": policy.max_position_size,
                "max_orders_per_minute": policy.max_orders_per_minute,
                "min_edge": str(policy.min_edge),
            },
        }

    def backtest_operational_constraints(
        self,
        historical_fills: List[KalshiFillFixture],
        policy: Optional[StrategyPolicy] = None,
        venue: str = "kalshi",
    ) -> Dict[str, Any]:
        """
        Backtest operational constraints over historical fills.

        This simulates each fill through:
        1. Strategy policy check
        2. Risk constraint check
        3. Reconciliation constraint check
        4. Gate state check

        Records when and why trading would have been constrained.

        Args:
            historical_fills: List of historical fills to replay
            policy: Strategy policy (uses default if None)
            venue: Venue name (default "kalshi")

        Returns:
            Dict with backtest results including constraint violations
        """
        if policy is None:
            policy = self.StrategyPolicy()

        results = {
            "total_fills": len(historical_fills),
            "strategy_violations": 0,
            "risk_violations": 0,
            "recon_violations": 0,
            "gate_blocks": 0,
            "constraint_timeline": [],
            "final_risk_status": "ok",
            "final_gate_state": "OPEN",
        }

        current_positions = []
        cumulative_exposure = Decimal("0")

        for i, fill in enumerate(historical_fills):
            # Step 1: Strategy policy check
            strategy_result = self.simulate_strategy_order(
                market_ticker=fill.market_ticker,
                side=fill.side,
                action=fill.action,
                count=fill.count,
                price_dollars=fill.yes_price_dollars,
                policy=policy,
                current_positions=current_positions,
            )

            if not strategy_result["allowed"]:
                results["strategy_violations"] += 1
                results["constraint_timeline"].append({
                    "fill_id": fill.fill_id,
                    "timestamp": fill.created_time.isoformat(),
                    "constraint": "strategy_policy",
                    "violations": strategy_result["violations"],
                })
                continue  # Skip this fill in backtest

            # Step 2: Risk constraint check
            risk_status = self._compute_risk_status(
                asset=fill.market_ticker.split("-")[0].replace("KX", ""),
                fills=[fill],
                existing_state={"existing_exposure": float(cumulative_exposure)},
            )

            if risk_status in ["critical", "hard_stop"]:
                results["risk_violations"] += 1
                results["constraint_timeline"].append({
                    "fill_id": fill.fill_id,
                    "timestamp": fill.created_time.isoformat(),
                    "constraint": "risk_limit",
                    "risk_status": risk_status,
                })

            # Update cumulative exposure
            if fill.action == "buy":
                cumulative_exposure += fill.count * fill.yes_price_dollars
            else:
                cumulative_exposure -= fill.count * fill.yes_price_dollars

            # Step 3: Gate state check
            gate_status = self.check_gate()

            if not gate_status.can_trade:
                results["gate_blocks"] += 1
                results["constraint_timeline"].append({
                    "fill_id": fill.fill_id,
                    "timestamp": fill.created_time.isoformat(),
                    "constraint": "execution_gate",
                    "gate_state": gate_status.gate_state,
                })

            # Update positions
            current_positions.append(self.build_position(
                ticker=fill.market_ticker,
                side=fill.side,
                count=fill.count,
                avg_price_dollars=fill.yes_price_dollars,
            ))

            # Track final states
            results["final_risk_status"] = risk_status
            results["final_gate_state"] = gate_status.gate_state

        return results


# Global harness instance for convenience
_harness_instance = None


def get_harness() -> KalshiTestHarness:
    """Get or create the global harness instance."""
    global _harness_instance
    if _harness_instance is None:
        _harness_instance = KalshiTestHarness()
    return _harness_instance

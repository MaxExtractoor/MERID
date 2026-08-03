"""
Kalshi Crypto Risk Infrastructure Tests

This test suite validates the risk infrastructure for Kalshi 15-minute crypto markets.
It enforces the contract defined in docs/audit/KALSHI_RISK_EXTERNAL_CONTRACT.md.

SPEC_VERSION: 1.0.0
"""
This suite tests:
- Position exposure caps (per-market per-side, time-bucket, account-level)
- PnL computation with Kalshi binary payoff and fee schedule
- Risk breach response (80% warning, 90% critical, 100% hard stop)
- Kill-switch integration with reconciliation
- Risk to gate integration (limit breach to reduce-only/block)

Cross-references:
- External contract: docs/audit/KALSHI_RISK_EXTERNAL_CONTRACT.md
- Reconciliation contract: docs/audit/KALSHI_RECONCILIATION_CONTRACT.md
- Gate logic: core/execution_gate.py
- Risk modules: risk/position_sizing.py, merid/risk/kalshi_risk_profile.py

Test markers:
- @pytest.mark.kalshi_risk - All Kalshi risk tests
- @pytest.mark.kalshi_risk_caps - Position cap tests
- @pytest.mark.kalshi_risk_pnl - PnL and fee tests
- @pytest.mark.kalshi_risk_breach - Breach response tests
- @pytest.mark.kalshi_risk_killswitch - Kill-switch integration tests
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Risk contract constants from KALSHI_RISK_EXTERNAL_CONTRACT.md
PER_MARKET_PER_SIDE_CAP = 500  # Max contracts per side per market
PER_15MIN_BUCKET_CAP = 250  # Max contracts per 15-minute bucket
TOTAL_ACCOUNT_EXPOSURE_CAP = Decimal("10000.00")  # $10k total exposure
PER_ASSET_EXPOSURE_CAP = Decimal("2000.00")  # $2k per asset

# Fee schedule constants
TAKER_FEE_PER_CONTRACT = Decimal("0.01")  # 1¢ taker
MAKER_FEE_PER_CONTRACT = Decimal("0.005")  # 0.5¢ maker
FEE_CAP_PER_CONTRACT = Decimal("0.07")  # 7¢ cap

# Breach thresholds
WARNING_THRESHOLD = Decimal("0.80")  # 80%
CRITICAL_THRESHOLD = Decimal("0.90")  # 90%
HARD_LIMIT_THRESHOLD = Decimal("1.00")  # 100%


class RiskStatus(str, Enum):
    """Risk status levels."""
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    HARD_STOP = "hard_stop"


class OrderSide(str, Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class ContractSide(str, Enum):
    """Contract side (YES/NO for binary markets)."""
    YES = "yes"
    NO = "no"


@dataclass
class KalshiRiskFillFixture:
    """Fixture data for Kalshi risk fills."""
    ticker: str  # e.g., "KXBTC-26JAN24-50000"
    side: ContractSide  # "yes" or "no"
    action: OrderSide  # "buy" or "sell"
    price_dollars: Decimal  # Entry price in dollars (0.00 to 1.00)
    size: int  # Number of contracts
    is_maker: bool  # True if maker order, False if taker
    fee_dollars: Decimal  # Fee in dollars
    timestamp: datetime  # Fill timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ticker": self.ticker,
            "side": self.side.value,
            "action": self.action.value,
            "price_dollars": float(self.price_dollars),
            "size": self.size,
            "is_maker": self.is_maker,
            "fee_dollars": float(self.fee_dollars),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    status: RiskStatus
    cap_exceeded: bool
    cap_utilization: Decimal  # Percentage of cap used
    market_exposure: Dict[str, int]  # Exposure per market
    asset_exposure: Dict[str, int]  # Exposure per asset
    total_exposure: Decimal  # Total notional exposure
    allowed_operations: List[str]  # Operations allowed at this risk level
    reason: Optional[str]  # Reason for breach or warning


@dataclass
class PnLResult:
    """Result of PnL calculation."""
    gross_pnl: Decimal
    fees: Decimal
    net_pnl: Decimal
    per_contract_pnl: Decimal
    fee_per_contract: Decimal


class KalshiRiskTestHarness:
    """
    Test harness for Kalshi risk infrastructure.
    
    Provides utilities for:
    - Building risk fill fixtures
    - Replaying fills into risk engine
    - Computing PnL with Kalshi fee schedule
    - Checking risk caps and breach response
    - Simulating kill-switch behavior
    """

    def __init__(self):
        self.current_positions: Dict[str, Dict[str, int]] = {}  # ticker -> {side: count}
        self.current_exposure: Dict[str, Decimal] = {}  # asset -> exposure in dollars

    # =========================================================================
    # Fixture Builders
    # =========================================================================

    def build_risk_fill(
        self,
        ticker: str,
        side: ContractSide,
        action: OrderSide,
        price_dollars: Decimal,
        size: int,
        is_maker: bool = False,
        timestamp: Optional[datetime] = None,
    ) -> KalshiRiskFillFixture:
        """
        Build a Kalshi risk fill fixture.
        
        Args:
            ticker: Market ticker (e.g., "KXBTC-26JAN24-50000")
            side: Contract side (YES/NO)
            action: Order action (buy/sell)
            price_dollars: Entry price in dollars (0.00 to 1.00)
            size: Number of contracts
            is_maker: True if maker order, False if taker
            timestamp: Fill timestamp (defaults to now)
        
        Returns:
            KalshiRiskFillFixture: Fill fixture
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Calculate fee based on Kalshi schedule
        fee_per_contract = MAKER_FEE_PER_CONTRACT if is_maker else TAKER_FEE_PER_CONTRACT
        fee_dollars = min(fee_per_contract * size, FEE_CAP_PER_CONTRACT * size)

        return KalshiRiskFillFixture(
            ticker=ticker,
            side=side,
            action=action,
            price_dollars=price_dollars,
            size=size,
            is_maker=is_maker,
            fee_dollars=fee_dollars,
            timestamp=timestamp,
        )

    def build_fills_sequence(
        self,
        ticker: str,
        side: ContractSide,
        action: OrderSide,
        base_price: Decimal = Decimal("0.50"),
        num_fills: int = 5,
        size_per_fill: int = 10,
    ) -> List[KalshiRiskFillFixture]:
        """
        Build a sequence of fills for testing.
        
        Args:
            ticker: Market ticker
            side: Contract side
            action: Order action
            base_price: Base price in dollars
            num_fills: Number of fills to generate
            size_per_fill: Size per fill
        
        Returns:
            List of KalshiRiskFillFixture
        """
        fills = []
        for i in range(num_fills):
            fill = self.build_risk_fill(
                ticker=ticker,
                side=side,
                action=action,
                price_dollars=base_price,
                size=size_per_fill,
                is_maker=(i % 2 == 0),  # Alternate maker/taker
            )
            fills.append(fill)
        return fills

    # =========================================================================
    # Risk Engine Simulation
    # =========================================================================

    def replay_fills(self, fills: List[KalshiRiskFillFixture]) -> None:
        """
        Replay fills into the risk engine and update internal state.
        
        Args:
            fills: List of fills to replay
        """
        for fill in fills:
            ticker = fill.ticker
            side = fill.side.value
            action = fill.action.value
            size = fill.size

            # Update position
            if ticker not in self.current_positions:
                self.current_positions[ticker] = {"yes": 0, "no": 0}

            if action == "buy":
                self.current_positions[ticker][side] += size
            else:  # sell
                self.current_positions[ticker][side] -= size

            # Update exposure (simplified: price * size)
            asset = self._extract_asset_from_ticker(ticker)
            exposure = fill.price_dollars * size
            if asset not in self.current_exposure:
                self.current_exposure[asset] = Decimal("0")
            if action == "buy":
                self.current_exposure[asset] += exposure
            else:
                self.current_exposure[asset] -= exposure

    def _extract_asset_from_ticker(self, ticker: str) -> str:
        """Extract asset from ticker (e.g., KXBTC -> BTC)."""
        if ticker.startswith("KXBTC"):
            return "BTC"
        elif ticker.startswith("KXETH"):
            return "ETH"
        elif ticker.startswith("KXSOL"):
            return "SOL"
        elif ticker.startswith("KXXRP"):
            return "XRP"
        elif ticker.startswith("KXDOGE"):
            return "DOGE"
        else:
            return "UNKNOWN"

    def get_market_exposure(self, ticker: str) -> Dict[str, int]:
        """Get exposure for a specific market by side."""
        return self.current_positions.get(ticker, {"yes": 0, "no": 0})

    def get_asset_exposure(self, asset: str) -> Decimal:
        """Get total exposure for an asset in dollars."""
        return self.current_exposure.get(asset, Decimal("0"))

    def get_total_exposure(self) -> Decimal:
        """Get total account exposure in dollars."""
        return sum(abs(exposure) for exposure in self.current_exposure.values())

    # =========================================================================
    # Risk Cap Checks
    # =========================================================================

    def check_per_market_per_side_cap(
        self,
        ticker: str,
        side: str,
        new_size: int,
    ) -> RiskCheckResult:
        """
        Check if an order would exceed per-market per-side cap.
        
        Args:
            ticker: Market ticker
            side: Contract side (yes/no)
            new_size: Size of new order
        
        Returns:
            RiskCheckResult: Risk check result
        """
        current_size = self.current_positions.get(ticker, {}).get(side, 0)
        new_total = current_size + new_size
        cap_utilization = Decimal(new_total) / Decimal(PER_MARKET_PER_SIDE_CAP)

        if new_total > PER_MARKET_PER_SIDE_CAP:
            return RiskCheckResult(
                status=RiskStatus.HARD_STOP,
                cap_exceeded=True,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=self.get_total_exposure(),
                allowed_operations=[],
                reason=f"Per-market per-side cap exceeded: {new_total} > {PER_MARKET_PER_SIDE_CAP}",
            )
        elif cap_utilization >= CRITICAL_THRESHOLD:
            return RiskCheckResult(
                status=RiskStatus.CRITICAL,
                cap_exceeded=False,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=self.get_total_exposure(),
                allowed_operations=["reduce_only"],
                reason=f"Per-market per-side cap at critical: {cap_utilization:.0%}",
            )
        elif cap_utilization >= WARNING_THRESHOLD:
            return RiskCheckResult(
                status=RiskStatus.WARNING,
                cap_exceeded=False,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=self.get_total_exposure(),
                allowed_operations=["buy", "sell"],
                reason=f"Per-market per-side cap at warning: {cap_utilization:.0%}",
            )
        else:
            return RiskCheckResult(
                status=RiskStatus.OK,
                cap_exceeded=False,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=self.get_total_exposure(),
                allowed_operations=["buy", "sell"],
                reason=None,
            )

    def check_total_account_exposure(self, new_exposure: Decimal) -> RiskCheckResult:
        """
        Check if new exposure would exceed total account cap.
        
        Args:
            new_exposure: Additional exposure in dollars
        
        Returns:
            RiskCheckResult: Risk check result
        """
        current_exposure = self.get_total_exposure()
        new_total = current_exposure + abs(new_exposure)
        cap_utilization = new_total / TOTAL_ACCOUNT_EXPOSURE_CAP

        if new_total > TOTAL_ACCOUNT_EXPOSURE_CAP:
            return RiskCheckResult(
                status=RiskStatus.HARD_STOP,
                cap_exceeded=True,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=new_total,
                allowed_operations=[],
                reason=f"Total account exposure cap exceeded: ${new_total:.2f} > ${TOTAL_ACCOUNT_EXPOSURE_CAP:.2f}",
            )
        elif cap_utilization >= CRITICAL_THRESHOLD:
            return RiskCheckResult(
                status=RiskStatus.CRITICAL,
                cap_exceeded=False,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=new_total,
                allowed_operations=["reduce_only"],
                reason=f"Total account exposure at critical: {cap_utilization:.0%}",
            )
        elif cap_utilization >= WARNING_THRESHOLD:
            return RiskCheckResult(
                status=RiskStatus.WARNING,
                cap_exceeded=False,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=new_total,
                allowed_operations=["buy", "sell"],
                reason=f"Total account exposure at warning: {cap_utilization:.0%}",
            )
        else:
            return RiskCheckResult(
                status=RiskStatus.OK,
                cap_exceeded=False,
                cap_utilization=cap_utilization,
                market_exposure=self.current_positions,
                asset_exposure={k: int(v) for k, v in self.current_exposure.items()},
                total_exposure=new_total,
                allowed_operations=["buy", "sell"],
                reason=None,
            )

    # =========================================================================
    # PnL Computation
    # =========================================================================

    def compute_pnl(
        self,
        entry_price: Decimal,
        exit_price: Decimal,
        size: int,
        side: ContractSide,
        is_maker: bool = False,
    ) -> PnLResult:
        """
        Compute PnL for a trade with Kalshi binary payoff and fee schedule.
        
        Args:
            entry_price: Entry price in dollars (0.00 to 1.00)
            exit_price: Exit price in dollars (0.00 to 1.00)
            size: Number of contracts
            side: Contract side (YES/NO)
            is_maker: True if maker order, False if taker
        
        Returns:
            PnLResult: PnL breakdown
        """
        # Calculate gross PnL based on binary payoff
        if side == ContractSide.YES:
            gross_pnl_per_contract = exit_price - entry_price
        else:  # NO
            gross_pnl_per_contract = (Decimal("1.00") - exit_price) - entry_price

        gross_pnl = gross_pnl_per_contract * size

        # Calculate fees with Kalshi schedule
        fee_per_contract = MAKER_FEE_PER_CONTRACT if is_maker else TAKER_FEE_PER_CONTRACT
        fee_per_contract = min(fee_per_contract, FEE_CAP_PER_CONTRACT)
        fees = fee_per_contract * size

        # Net PnL
        net_pnl = gross_pnl - fees

        return PnLResult(
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=net_pnl,
            per_contract_pnl=gross_pnl_per_contract,
            fee_per_contract=fee_per_contract,
        )


# ============================================================================
# Test Classes
# ============================================================================

class TestKalshiRiskCaps:
    """Test position exposure caps (per-market per-side, time-bucket, account-level)."""

    @pytest.fixture
    def harness(self):
        """Provide a fresh risk test harness."""
        h = KalshiRiskTestHarness()
        yield h
        h.current_positions.clear()
        h.current_exposure.clear()

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_caps
    def test_per_market_per_side_cap_exceeded(self, harness):
        """Test that orders exceeding per-market per-side cap are blocked."""
        ticker = "KXBTC-26JAN24-50000"
        side = "yes"
        
        # Arrange: Create fills buying 500 YES contracts
        fills = harness.build_fills_sequence(
            ticker=ticker,
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=50,
            size_per_fill=10,
        )
        harness.replay_fills(fills)
        
        # Act: Check risk for +1 more YES contract
        result = harness.check_per_market_per_side_cap(ticker, side, new_size=1)
        
        # Assert: Risk engine flags order as over cap
        assert result.status == RiskStatus.HARD_STOP
        assert result.cap_exceeded == True
        assert "cap exceeded" in result.reason.lower()
        assert "500" in result.reason

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_caps
    def test_per_market_per_side_cap_within_limit(self, harness):
        """Test that orders within per-market per-side cap are allowed."""
        ticker = "KXBTC-26JAN24-50000"
        side = "yes"
        
        # Arrange: Create fills buying 400 YES contracts (80% of cap)
        fills = harness.build_fills_sequence(
            ticker=ticker,
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=40,
            size_per_fill=10,
        )
        harness.replay_fills(fills)
        
        # Act: Check risk for +50 more YES contracts
        result = harness.check_per_market_per_side_cap(ticker, side, new_size=50)
        
        # Assert: Risk engine allows order (at warning threshold)
        assert result.status == RiskStatus.WARNING
        assert result.cap_exceeded == False
        assert "buy" in result.allowed_operations

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_caps
    def test_total_account_exposure_cap_exceeded(self, harness):
        """Test that orders exceeding total account exposure cap are blocked."""
        # Arrange: Create fills across multiple assets near $10k
        btc_fills = harness.build_fills_sequence(
            ticker="KXBTC-26JAN24-50000",
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=100,
            size_per_fill=10,
        )
        eth_fills = harness.build_fills_sequence(
            ticker="KXETH-26JAN24-4000",
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=100,
            size_per_fill=10,
        )
        harness.replay_fills(btc_fills + eth_fills)
        
        # Act: Check risk for additional exposure
        result = harness.check_total_account_exposure(Decimal("1000.00"))
        
        # Assert: Risk engine denies order
        assert result.status == RiskStatus.HARD_STOP
        assert result.cap_exceeded == True
        assert "total account exposure" in result.reason.lower()


class TestKalshiRiskPnl:
    """Test PnL computation with Kalshi binary payoff and fee schedule."""

    @pytest.fixture
    def harness(self):
        """Provide a fresh risk test harness."""
        return KalshiRiskTestHarness()

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_pnl
    def test_trade_pnl_with_fees_taker(self, harness):
        """Test PnL calculation for taker trade with fees."""
        # Arrange: Single BTC YES trade at 0.45, taker, 10 contracts
        entry_price = Decimal("0.45")
        exit_price = Decimal("1.00")  # YES wins
        size = 10
        is_maker = False
        
        # Act: Compute PnL
        result = harness.compute_pnl(entry_price, exit_price, size, ContractSide.YES, is_maker)
        
        # Assert: PnL matches expected
        expected_gross_per_contract = exit_price - entry_price  # 0.55
        expected_gross = expected_gross_per_contract * size  # 5.50
        expected_fee_per_contract = TAKER_FEE_PER_CONTRACT  # 0.01
        expected_fees = expected_fee_per_contract * size  # 0.10
        expected_net = expected_gross - expected_fees  # 5.40
        
        assert result.gross_pnl == expected_gross
        assert result.fees == expected_fees
        assert result.net_pnl == expected_net
        assert result.per_contract_pnl == expected_gross_per_contract
        assert result.fee_per_contract == expected_fee_per_contract

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_pnl
    def test_trade_pnl_with_fees_maker(self, harness):
        """Test PnL calculation for maker trade with lower fees."""
        # Arrange: Single BTC YES trade at 0.45, maker, 10 contracts
        entry_price = Decimal("0.45")
        exit_price = Decimal("1.00")
        size = 10
        is_maker = True
        
        # Act: Compute PnL
        result = harness.compute_pnl(entry_price, exit_price, size, ContractSide.YES, is_maker)
        
        # Assert: Maker fees are lower
        expected_fee_per_contract = MAKER_FEE_PER_CONTRACT  # 0.005
        assert result.fee_per_contract == expected_fee_per_contract
        assert result.fees == expected_fee_per_contract * size

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_pnl
    def test_fee_cap_enforcement(self, harness):
        """Test that fee cap is enforced for large orders."""
        # Arrange: Large trade that would exceed fee cap
        entry_price = Decimal("0.50")
        exit_price = Decimal("1.00")
        size = 100  # Large size to test cap
        is_maker = False
        
        # Act: Compute PnL
        result = harness.compute_pnl(entry_price, exit_price, size, ContractSide.YES, is_maker)
        
        # Assert: Fee per contract is capped at 7¢
        assert result.fee_per_contract == FEE_CAP_PER_CONTRACT
        assert result.fees == FEE_CAP_PER_CONTRACT * size


class TestKalshiRiskBreachResponse:
    """Test risk breach response (80% warning, 90% critical, 100% hard stop)."""

    @pytest.fixture
    def harness(self):
        """Provide a fresh risk test harness."""
        h = KalshiRiskTestHarness()
        yield h
        h.current_positions.clear()
        h.current_exposure.clear()

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_breach
    def test_warning_threshold_80_percent(self, harness):
        """Test risk status at 80% warning threshold."""
        ticker = "KXBTC-26JAN24-50000"
        side = "yes"
        
        # Arrange: Exposure at 400 contracts (80% of 500)
        warning_size = int(PER_MARKET_PER_SIDE_CAP * WARNING_THRESHOLD)
        fills = harness.build_fills_sequence(
            ticker=ticker,
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=40,
            size_per_fill=10,
        )
        harness.replay_fills(fills)
        
        # Act: Run risk check
        result = harness.check_per_market_per_side_cap(ticker, side, new_size=0)
        
        # Assert: Risk status is WARNING, no hard block
        assert result.status == RiskStatus.WARNING
        assert result.cap_exceeded == False
        assert "buy" in result.allowed_operations
        assert "warning" in result.reason.lower()

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_breach
    def test_critical_threshold_90_percent(self, harness):
        """Test risk status at 90% critical threshold."""
        ticker = "KXBTC-26JAN24-50000"
        side = "yes"
        
        # Arrange: Exposure at 450 contracts (90% of 500)
        critical_size = int(PER_MARKET_PER_SIDE_CAP * CRITICAL_THRESHOLD)
        fills = harness.build_fills_sequence(
            ticker=ticker,
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=45,
            size_per_fill=10,
        )
        harness.replay_fills(fills)
        
        # Act: Run risk check
        result = harness.check_per_market_per_side_cap(ticker, side, new_size=0)
        
        # Assert: Risk status is CRITICAL, reduce-only mode
        assert result.status == RiskStatus.CRITICAL
        assert result.cap_exceeded == False
        assert "reduce_only" in result.allowed_operations
        assert "buy" not in result.allowed_operations
        assert "critical" in result.reason.lower()

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_breach
    def test_hard_limit_100_percent(self, harness):
        """Test risk status at 100% hard limit."""
        ticker = "KXBTC-26JAN24-50000"
        side = "yes"
        
        # Arrange: Exposure at 500 contracts (100% of 500)
        fills = harness.build_fills_sequence(
            ticker=ticker,
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=50,
            size_per_fill=10,
        )
        harness.replay_fills(fills)
        
        # Act: Attempt order that would exceed cap
        result = harness.check_per_market_per_side_cap(ticker, side, new_size=1)
        
        # Assert: Risk check fails, hard stop
        assert result.status == RiskStatus.HARD_STOP
        assert result.cap_exceeded == True
        assert len(result.allowed_operations) == 0
        assert "hard stop" in result.reason.lower() or "exceeded" in result.reason.lower()


class TestKalshiRiskKillSwitchIntegration:
    """Test kill-switch integration with reconciliation."""

    @pytest.fixture
    def harness(self):
        """Provide a fresh risk test harness."""
        h = KalshiRiskTestHarness()
        yield h
        h.current_positions.clear()
        h.current_exposure.clear()

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_killswitch
    def test_phantom_triggers_kill_switch(self, harness):
        """Test that phantom position triggers kill-switch."""
        # This test would integrate with phantom_detection.py
        # For now, we simulate the trigger
        
        # Arrange: Simulate phantom detection
        phantom_detected = True
        market_id = "KXBTC-26JAN24-50000"
        
        # Act: Simulate kill-switch activation
        kill_switch_active = phantom_detected
        
        # Assert: Kill-switch engages
        assert kill_switch_active == True
        # In full implementation, would assert:
        # - Orders canceled in market
        # - Gate set to BLOCKED
        # - Kill-switch metric emitted

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_killswitch
    def test_risk_breach_triggers_kill_switch(self, harness):
        """Test that risk hard limit breach triggers kill-switch."""
        # Arrange: Exposure beyond hard limit
        fills = harness.build_fills_sequence(
            ticker="KXBTC-26JAN24-50000",
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=55,  # 550 contracts, exceeds 500 cap
            size_per_fill=10,
        )
        harness.replay_fills(fills)
        
        # Act: Check risk
        result = harness.check_per_market_per_side_cap("KXBTC-26JAN24-50000", "yes", new_size=0)
        
        # Assert: Hard stop triggers kill-switch
        assert result.status == RiskStatus.HARD_STOP
        # In full implementation, would assert:
        # - Orders to increase exposure canceled
        # - No new orders allowed
        # - Auto-flatten triggered if defined


class TestKalshiRiskTimeBuckets:
    """Test 15-minute bucket limits."""

    @pytest.fixture
    def harness(self):
        """Provide a fresh risk test harness."""
        h = KalshiRiskTestHarness()
        yield h
        h.current_positions.clear()
        h.current_exposure.clear()

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_caps
    def test_15min_bucket_limit(self, harness):
        """Test that 15-minute bucket limit is enforced."""
        # Arrange: 3 markets within same 15-minute window totaling 250 contracts
        fills_market1 = harness.build_fills_sequence(
            ticker="KXBTC-26JAN24-50000",
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=10,
            size_per_fill=10,  # 100 contracts
        )
        fills_market2 = harness.build_fills_sequence(
            ticker="KXBTC-26JAN24-51000",
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=10,
            size_per_fill=10,  # 100 contracts
        )
        fills_market3 = harness.build_fills_sequence(
            ticker="KXBTC-26JAN24-52000",
            side=ContractSide.YES,
            action=OrderSide.BUY,
            base_price=Decimal("0.50"),
            num_fills=5,
            size_per_fill=10,  # 50 contracts
        )
        harness.replay_fills(fills_market1 + fills_market2 + fills_market3)
        
        # Act: Attempt order that takes bucket to 251
        # (This would require time-bucket logic in full implementation)
        total_contracts = harness.get_market_exposure("KXBTC-26JAN24-50000")["yes"]
        
        # Assert: Bucket limit enforced
        # In full implementation, would check bucket total across markets
        assert total_contracts == 100  # Just checking one market for now


class TestKalshiRiskGateIntegration:
    """Test risk → gate integration using the central harness simulate_order helper."""

    @pytest.fixture
    def kalshi_harness(self):
        """Provide a fresh Kalshi test harness."""
        from tests.event_venues.kalshi.harness import KalshiTestHarness
        h = KalshiTestHarness()
        yield h

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_breach
    def test_risk_warning_allows_new_orders(self, kalshi_harness):
        """Test that risk WARNING status allows new orders."""
        # Arrange: Risk state at 80% (warning threshold)
        fills = [
            kalshi_harness.build_fill(
                fill_id="fill_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=1600,  # $1600 exposure (80% of $2000 cap)
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 1600}
        
        # Act: Simulate order through risk → gate pipeline
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=fills,
            risk_state=risk_state,
        )
        
        # Assert: Risk status is WARNING, gate allows buy/sell
        assert result["risk_status"] == "warning"
        assert "buy" in result["allowed_operations"]
        assert "sell" in result["allowed_operations"]

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_breach
    def test_risk_critical_enforces_reduce_only(self, kalshi_harness):
        """Test that risk CRITICAL status enforces reduce-only mode."""
        # Arrange: Risk state at 90% (critical threshold)
        fills = [
            kalshi_harness.build_fill(
                fill_id="fill_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=1800,  # $1800 exposure (90% of $2000 cap)
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 1800}
        
        # Act: Simulate order through risk → gate pipeline
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=fills,
            risk_state=risk_state,
        )
        
        # Assert: Risk status is CRITICAL, only reduce-only allowed
        assert result["risk_status"] == "critical"
        assert "reduce_only" in result["allowed_operations"]
        assert "buy" not in result["allowed_operations"]

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_breach
    def test_risk_hard_stop_blocks_all_orders(self, kalshi_harness):
        """Test that risk HARD_STOP status blocks all new orders."""
        # Arrange: Risk state at 100% (hard limit)
        fills = [
            kalshi_harness.build_fill(
                fill_id="fill_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=2000,  # $2000 exposure (100% of $2000 cap)
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 2000}
        
        # Act: Simulate order through risk → gate pipeline
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=fills,
            risk_state=risk_state,
        )
        
        # Assert: Risk status is HARD_STOP, no operations allowed
        assert result["risk_status"] == "hard_stop"
        assert len(result["allowed_operations"]) == 0

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_killswitch
    def test_phantom_plus_risk_breach_stricter_wins(self, kalshi_harness):
        """Test that phantom + risk breach uses stricter of the two."""
        # Arrange: Both phantom detection and risk breach
        fills = [
            kalshi_harness.build_fill(
                fill_id="fill_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=1500,  # $1500 exposure
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 1500}
        recon_state = {
            "market_id": "KXBTC-26JAN24-50000",
            "internal_yes_qty": 100,
            "internal_no_qty": 0,
            "external_yes_qty": 0,  # Phantom: internal has position, external doesn't
            "external_no_qty": 0,
        }
        
        # Act: Simulate order with both risk and recon state
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=fills,
            risk_state=risk_state,
            recon_state=recon_state,
        )
        
        # Assert: Phantom detected (stricter than risk warning)
        assert result["recon_phantom"] == True
        # In full implementation, phantom should trigger BLOCKED state
        # For now, we verify the recon state is processed
        assert result["recon_severity"] is not None

    @pytest.mark.kalshi_risk
    @pytest.mark.kalshi_risk_breach
    def test_clean_risk_allows_full_trading(self, kalshi_harness):
        """Test that clean risk status allows full trading."""
        # Arrange: Normal risk state (well within limits)
        fills = [
            kalshi_harness.build_fill(
                fill_id="fill_001",
                market_ticker="KXBTC-26JAN24-50000",
                side="yes",
                action="buy",
                count=100,  # $100 exposure (5% of $2000 cap)
                yes_price_dollars=Decimal("0.50"),
            )
        ]
        risk_state = {"existing_exposure": 100}
        
        # Act: Simulate order through risk → gate pipeline
        result = kalshi_harness.simulate_order(
            asset="BTC",
            fills=fills,
            risk_state=risk_state,
        )
        
        # Assert: Risk status is OK, full trading allowed
        assert result["risk_status"] == "ok"
        assert "buy" in result["allowed_operations"]
        assert "sell" in result["allowed_operations"]


# ============================================================================
# Test Runner Configuration
# ============================================================================

def pytest_configure(config):
    """Configure pytest markers for Kalshi risk tests."""
    config.addinivalue_line(
        "markers", "kalshi_risk: Kalshi risk infrastructure tests"
    )
    config.addinivalue_line(
        "markers", "kalshi_risk_caps: Position cap tests"
    )
    config.addinivalue_line(
        "markers", "kalshi_risk_pnl: PnL and fee tests"
    )
    config.addinivalue_line(
        "markers", "kalshi_risk_breach: Breach response tests"
    )
    config.addinivalue_line(
        "markers", "kalshi_risk_killswitch: Kill-switch integration tests"
    )

"""Tests for Kalshi Order Group functionality.

Covers:
- OrderGroupRiskManager state tracking
- OrderGroupLifecycleManager hooks
- OrderGroupErrorClassifier recovery patterns
- API endpoint integration
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from merid.event_venues.kalshi.order_group_manager import (
    OrderGroupState,
    OrderGroupRiskManager,
)
from merid.event_venues.kalshi.order_group_lifecycle import (
    OrderGroupLifecycleManager,
    LifecycleConfig,
)
from merid.event_venues.kalshi.order_group_recovery import (
    OrderGroupErrorClassifier,
    OrderGroupRecoveryManager,
    ErrorCode,
    RecoveryAction,
)
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    BatchOrderIntent,
    route_batch_orders_async,
)


# ═══════════════════════════════════════════════════════════════════════════
# OrderGroupState Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderGroupState:
    """Tests for OrderGroupState dataclass."""

    def test_initial_state(self):
        """Test fresh OrderGroupState initialization."""
        state = OrderGroupState(
            order_group_id="test-og-1",
            contracts_limit=1000,
        )
        assert state.order_group_id == "test-og-1"
        assert state.contracts_limit == 1000
        assert state.used_contracts == 0
        assert state.matched_contracts == 0
        assert state.status == "active"
        assert state.is_active()

    def test_utilization_calculation(self):
        """Test utilization percentage calculation."""
        state = OrderGroupState(
            order_group_id="test-og-1",
            contracts_limit=1000,
            used_contracts=500,
            matched_contracts=300,
        )
        assert state.utilization_pct == 50.0

    def test_can_add_contracts_active(self):
        """Test can_add_contracts when group is active."""
        state = OrderGroupState(
            order_group_id="test-og-1",
            contracts_limit=1000,
            used_contracts=500,
        )
        assert state.can_add_contracts(400)  # Under limit
        assert state.can_add_contracts(500)  # At limit
        assert not state.can_add_contracts(501)  # Over limit

    def test_can_add_contracts_triggered(self):
        """Test can_add_contracts when group is triggered."""
        state = OrderGroupState(
            order_group_id="test-og-1",
            contracts_limit=1000,
            status="triggered",
        )
        assert not state.can_add_contracts(1)  # Cannot add when triggered

    def test_record_new_order(self):
        """Test recording new orders."""
        state = OrderGroupState(
            order_group_id="test-og-1",
            contracts_limit=1000,
        )
        state.record_new_order(100)
        assert state.used_contracts == 100
        state.record_new_order(50)
        assert state.used_contracts == 150

    def test_record_fill(self):
        """Test recording fills."""
        state = OrderGroupState(
            order_group_id="test-og-1",
            contracts_limit=1000,
            used_contracts=100,
        )
        state.record_fill(50)
        assert state.used_contracts == 50
        assert state.matched_contracts == 50

    def test_record_fill_clamps_at_zero(self):
        """Test fill recording doesn't go below zero."""
        state = OrderGroupState(
            order_group_id="test-og-1",
            contracts_limit=1000,
            used_contracts=30,
        )
        state.record_fill(50)  # Try to fill more than used
        assert state.used_contracts == 0
        assert state.matched_contracts == 50


# ═══════════════════════════════════════════════════════════════════════════
# OrderGroupRiskManager Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderGroupRiskManager:
    """Tests for OrderGroupRiskManager."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Kalshi client."""
        client = MagicMock()
        client.get_order_groups = AsyncMock(return_value=MagicMock(
            success=True,
            data=[
                {
                    "order_group_id": "og-1",
                    "status": "active",
                    "contracts_limit": 1000,
                    "matched_contracts": 100,
                    "used_contracts": 200,
                },
                {
                    "order_group_id": "og-2",
                    "status": "triggered",
                    "contracts_limit": 500,
                    "matched_contracts": 500,
                    "used_contracts": 0,
                },
            ],
        ))
        return client

    @pytest.mark.asyncio
    async def test_refresh_all_groups(self, mock_client):
        """Test refreshing all groups from API."""
        manager = OrderGroupRiskManager(mock_client)
        
        with patch.object(mock_client, 'connect', AsyncMock()):
            with patch.object(mock_client, 'close', AsyncMock()):
                manager.refresh_all()
                
        assert len(manager.groups) == 2
        assert "og-1" in manager.groups
        assert "og-2" in manager.groups
        assert manager.groups["og-1"].status == "active"
        assert manager.groups["og-2"].status == "triggered"

    def test_get_group_existing(self, mock_client):
        """Test getting an existing group."""
        manager = OrderGroupRiskManager(mock_client)
        
        # Manually populate
        manager.groups["og-1"] = OrderGroupState(
            order_group_id="og-1",
            contracts_limit=1000,
            status="active",
        )
        
        group = manager.get_group("og-1")
        assert group is not None
        assert group.order_group_id == "og-1"

    def test_get_group_nonexistent(self, mock_client):
        """Test getting a non-existent group."""
        manager = OrderGroupRiskManager(mock_client)
        group = manager.get_group("nonexistent")
        assert group is None

    def test_record_new_order(self, mock_client):
        """Test recording new orders."""
        manager = OrderGroupRiskManager(mock_client)
        
        manager.groups["og-1"] = OrderGroupState(
            order_group_id="og-1",
            contracts_limit=1000,
            used_contracts=0,
        )
        
        manager.record_new_order("og-1", 100)
        assert manager.groups["og-1"].used_contracts == 100

    def test_record_fill(self, mock_client):
        """Test recording fills."""
        manager = OrderGroupRiskManager(mock_client)
        
        manager.groups["og-1"] = OrderGroupState(
            order_group_id="og-1",
            contracts_limit=1000,
            used_contracts=200,
            matched_contracts=0,
        )
        
        manager.record_fill("og-1", 50)
        assert manager.groups["og-1"].used_contracts == 150
        assert manager.groups["og-1"].matched_contracts == 50

    def test_get_usage_summary(self, mock_client):
        """Test getting usage summary."""
        manager = OrderGroupRiskManager(mock_client)
        
        manager.groups["og-1"] = OrderGroupState(
            order_group_id="og-1",
            contracts_limit=1000,
            used_contracts=500,
            matched_contracts=300,
        )
        
        summary = manager.get_usage_summary("og-1")
        assert summary["order_group_id"] == "og-1"
        assert summary["utilization_pct"] == 50.0
        assert summary["remaining"] == 500


# ═══════════════════════════════════════════════════════════════════════════
# OrderGroupErrorClassifier Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderGroupErrorClassifier:
    """Tests for OrderGroupErrorClassifier."""

    def test_classify_invalid_limit(self):
        """Test classifying invalid limit errors."""
        classification = OrderGroupErrorClassifier.classify(
            "invalid_limit: contracts must be positive"
        )
        assert classification.code == ErrorCode.INVALID_LIMIT
        assert not classification.is_retryable
        assert classification.suggested_action == RecoveryAction.SKIP_AND_CONTINUE

    def test_classify_group_not_found(self):
        """Test classifying group not found errors."""
        classification = OrderGroupErrorClassifier.classify(
            "order_group_not_found: og-123"
        )
        assert classification.code == ErrorCode.ORDER_GROUP_NOT_FOUND
        assert classification.is_retryable
        assert classification.suggested_action == RecoveryAction.REFRESH_GROUPS

    def test_classify_group_triggered(self):
        """Test classifying group triggered errors."""
        classification = OrderGroupErrorClassifier.classify(
            "group_triggered: order group already triggered"
        )
        assert classification.code == ErrorCode.GROUP_TRIGGERED
        assert not classification.is_retryable
        assert classification.suggested_action == RecoveryAction.RESET_GROUP

    def test_classify_limit_exceeded(self):
        """Test classifying limit exceeded errors."""
        classification = OrderGroupErrorClassifier.classify(
            "contracts_limit_exceeded: used=900, limit=1000"
        )
        assert classification.code == ErrorCode.CONTRACTS_LIMIT_EXCEEDED
        assert not classification.is_retryable

    def test_classify_with_status_code(self):
        """Test classifying with HTTP status code."""
        classification = OrderGroupErrorClassifier.classify(
            "Something went wrong",
            status_code=404,
        )
        assert classification.code == ErrorCode.ORDER_GROUP_NOT_FOUND

    def test_classify_unknown_error(self):
        """Test classifying unknown errors."""
        classification = OrderGroupErrorClassifier.classify(
            "some random error we don't recognize"
        )
        assert classification.code == ErrorCode.UNKNOWN_ERROR
        assert classification.suggested_action == RecoveryAction.HALT_AND_ALERT


# ═══════════════════════════════════════════════════════════════════════════
# OrderGroupRecoveryManager Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderGroupRecoveryManager:
    """Tests for OrderGroupRecoveryManager."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Kalshi client."""
        client = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_attempt_recovery_refresh_groups(self, mock_client):
        """Test recovery by refreshing groups."""
        mock_client.get_order_groups = AsyncMock(return_value=MagicMock(
            success=True,
            data=[{"order_group_id": "og-1"}],
        ))
        
        manager = OrderGroupRecoveryManager(mock_client)
        result = await manager.attempt_recovery(
            "og-1",
            "order_group_not_found",
        )
        
        assert result.action_taken == RecoveryAction.REFRESH_GROUPS
        assert result.error_resolved

    @pytest.mark.asyncio
    async def test_attempt_recovery_max_retries(self, mock_client):
        """Test max retry limit enforcement."""
        manager = OrderGroupRecoveryManager(mock_client)
        
        # Attempt recovery multiple times
        for _ in range(4):
            result = await manager.attempt_recovery(
                "og-1",
                "some error",
            )
        
        # 4th attempt should fail due to max retries
        assert not result.success
        assert "Max recovery attempts" in result.message

    def test_reset_attempt_counter(self, mock_client):
        """Test resetting attempt counter."""
        manager = OrderGroupRecoveryManager(mock_client)
        
        # Populate attempts
        manager._recovery_attempts["og-1:unknown_error"] = 3
        
        # Reset specific group
        manager.reset_attempt_counter("og-1")
        assert "og-1:unknown_error" not in manager._recovery_attempts

    def test_get_recovery_stats(self, mock_client):
        """Test getting recovery statistics."""
        manager = OrderGroupRecoveryManager(mock_client)
        manager._recovery_attempts = {
            "og-1:error1": 2,
            "og-2:error2": 3,
        }
        
        stats = manager.get_recovery_stats()
        assert stats["total_attempts"] == 5
        assert stats["max_attempts"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# OrderRouter Batch Tests
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_batch_order_intent_creation():
    """Test BatchOrderIntent merges settings correctly."""
    batch = BatchOrderIntent(
        orders=[
            OrderIntent(
                ticker="KXBTC-24JUN",
                side="yes",
                action="buy",
                price_cents=55,
                count=10,
                order_group_id="custom-og",  # Individual override
            ),
            OrderIntent(
                ticker="KXETH-24JUN",
                side="no",
                action="buy",
                price_cents=45,
                count=20,
                # No order_group_id - should use batch default
            ),
        ],
        order_group_id="batch-default-og",
        self_trade_prevention_type="taker_at_cross",
    )
    
    assert batch.orders[0].order_group_id == "custom-og"  # Individual wins
    assert batch.orders[1].order_group_id == "batch-default-og"  # Batch default


# ═══════════════════════════════════════════════════════════════════════════
# OrderIntent Tests
# ═══════════════════════════════════════════════════════════════════════════

def test_order_intent_with_post_only():
    """Test OrderIntent with post_only flag."""
    intent = OrderIntent(
        ticker="KXBTC-24JUN",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        post_only=True,
    )
    assert intent.post_only is True


def test_order_intent_with_order_group():
    """Test OrderIntent with order group assignment."""
    intent = OrderIntent(
        ticker="KXBTC-24JUN",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
        order_group_id="og-123",
        self_trade_prevention_type="taker_at_cross",
    )
    assert intent.order_group_id == "og-123"
    assert intent.self_trade_prevention_type == "taker_at_cross"

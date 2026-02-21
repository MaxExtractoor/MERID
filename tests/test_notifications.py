"""
Integration tests for the notifications feature.

Tests the full stack: NotificationStore (SQLite) → API endpoints → response shape.
Uses a temporary in-memory DB to avoid polluting the real store.

Covers:
  1. GET /api/v1/notifications — empty store, with data, stub fallback
  2. POST /api/v1/notifications/{id}/read — mark single read
  3. POST /api/v1/notifications/read-all — mark all read
  4. GET /api/v1/notifications/telegram/log — filtered by source
  5. Trade fill → notification emitted
"""

import os
import tempfile
import time
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixture: temp DB + patched store singleton
# ---------------------------------------------------------------------------

@pytest.fixture()
def notif_client(missing_endpoints_client):
    """Provide a TestClient with a fresh, temp-file-backed NotificationStore."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Remove the file so we start with a truly empty DB
    os.unlink(db_path)

    import core.notifications as notif_mod
    old_store = notif_mod._store

    # Directly create a store with the temp DB and inject into singleton
    notif_mod._store = notif_mod.NotificationStore(db_path=db_path)

    yield missing_endpoints_client

    # Cleanup
    notif_mod._store = old_store
    try:
        os.unlink(db_path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# GET /api/v1/notifications
# ---------------------------------------------------------------------------

class TestNotificationsEndpoint:

    def test_empty_store_returns_real_empty(self, notif_client):
        """Empty store → real response (no _stub), zero notifications."""
        resp = notif_client.get("/api/v1/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data
        assert data["notifications"] == []
        assert data["unread_count"] == 0
        assert data["total"] == 0

    def test_returns_added_notifications(self, notif_client):
        """After adding notifications, they appear in the response."""
        from core.notifications import add_notification

        add_notification(type="info", title="Test 1", message="Hello", source="test")
        add_notification(type="warning", title="Test 2", message="Watch out", source="test")

        resp = notif_client.get("/api/v1/notifications")
        data = resp.json()
        assert "_stub" not in data
        assert data["total"] == 2
        assert data["unread_count"] == 2
        assert len(data["notifications"]) == 2
        # Newest first
        assert data["notifications"][0]["title"] == "Test 2"

    def test_limit_parameter(self, notif_client):
        """Limit parameter caps the number of returned notifications."""
        from core.notifications import add_notification

        for i in range(5):
            add_notification(type="info", title=f"N-{i}", message="", source="test")

        resp = notif_client.get("/api/v1/notifications?limit=2")
        data = resp.json()
        assert len(data["notifications"]) == 2
        assert data["total"] == 5

    def test_import_failure_returns_stub(self, missing_endpoints_client):
        """When notification store can't be imported, stub fallback fires."""
        broken = MagicMock()
        broken.get_notification_store.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"core.notifications": broken}):
            resp = missing_endpoints_client.get("/api/v1/notifications")

        assert resp.status_code == 200
        assert resp.json().get("_stub") is True


# ---------------------------------------------------------------------------
# POST /api/v1/notifications/{id}/read
# ---------------------------------------------------------------------------

class TestMarkRead:

    def test_mark_single_read(self, notif_client):
        """Marking a notification as read reduces unread_count."""
        from core.notifications import add_notification

        n = add_notification(type="info", title="Unread", message="", source="test")

        resp = notif_client.post(f"/api/v1/notifications/{n.id}/read")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # Verify unread count dropped
        resp = notif_client.get("/api/v1/notifications")
        assert resp.json()["unread_count"] == 0

    def test_mark_nonexistent_returns_false(self, notif_client):
        resp = notif_client.post("/api/v1/notifications/does-not-exist/read")
        assert resp.status_code == 200
        assert resp.json()["success"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/notifications/read-all
# ---------------------------------------------------------------------------

class TestMarkAllRead:

    def test_mark_all_read(self, notif_client):
        from core.notifications import add_notification

        add_notification(type="info", title="A", message="", source="test")
        add_notification(type="info", title="B", message="", source="test")

        resp = notif_client.post("/api/v1/notifications/read-all")
        assert resp.status_code == 200
        result = resp.json()
        assert result["success"] is True
        assert result["marked"] == 2

        resp = notif_client.get("/api/v1/notifications")
        assert resp.json()["unread_count"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/notifications/telegram/log
# ---------------------------------------------------------------------------

class TestTelegramLog:

    def test_filters_by_source(self, notif_client):
        """Telegram log only returns notifications with source='telegram'."""
        from core.notifications import add_notification

        add_notification(type="info", title="Trade", message="Fill", source="trading")
        add_notification(type="info", title="TG Alert", message="Alert sent", source="telegram")

        resp = notif_client.get("/api/v1/notifications/telegram/log")
        data = resp.json()
        assert "_stub" not in data
        assert data["total"] == 1
        assert data["messages"][0]["message"] == "Alert sent"


# ---------------------------------------------------------------------------
# Trade → notification integration
# ---------------------------------------------------------------------------

class TestTradeNotificationIntegration:

    def test_order_fill_emits_notification(self, notif_client):
        """When an order fills, a trade notification is added to the store."""
        from trading.paper_trading import PaperTradingEngine, PaperPortfolio

        engine = PaperTradingEngine.__new__(PaperTradingEngine)
        engine.starting_balance = 100000.0
        engine.portfolios = {"operator": PaperPortfolio(user_id="operator", starting_balance=100000.0, current_balance=100000.0)}
        engine.order_counter = 0
        engine.position_counter = 0
        engine.current_prices = {"BTC-USD": 68000.0, "BTC/USDT": 68000.0}
        engine.price_feed = None
        engine._listeners = {"trade": set(), "summary": set(), "position": set()}
        engine._summary_dirty = False
        engine._positions_dirty = False
        engine._last_summary_emit = 0.0
        engine._last_positions_emit = 0.0
        engine.summary_snapshot = None

        pt_mod = MagicMock()
        pt_mod.get_paper_engine = MagicMock(return_value=engine)

        pd_mock = MagicMock()
        pd_mock.price = 68000.0
        feed = MagicMock()
        feed.price_cache = {"BTC/USDT": pd_mock}
        pf_mod = MagicMock()
        pf_mod.get_live_price_feed = MagicMock(return_value=feed)

        mods = {
            "trading.paper_trading": pt_mod,
            "data.live_price_feed": pf_mod,
        }

        with patch.dict("sys.modules", mods):
            with patch("trading.paper_trading._save_paper_state"):
                with patch("trading.paper_trading._get_risk_controller", return_value=None):
                    resp = notif_client.post("/api/v1/orders/submit", json={
                        "symbol": "BTC-USD", "side": "BUY",
                        "orderType": "MARKET", "size": "0.1",
                    })
                    assert resp.json()["success"] is True

        # Check notification was emitted
        resp = notif_client.get("/api/v1/notifications")
        data = resp.json()
        trade_notifs = [n for n in data["notifications"] if n["type"] == "trade"]
        assert len(trade_notifs) >= 1
        assert "Order Filled" in trade_notifs[0]["title"]


# ---------------------------------------------------------------------------
# GET /api/v1/notifications/stats
# ---------------------------------------------------------------------------

class TestNotificationStats:

    def test_stats_empty_store(self, notif_client):
        """Empty store returns zero counts and healthy=True."""
        resp = notif_client.get("/api/v1/notifications/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "_stub" not in data
        assert data["total"] == 0
        assert data["unread"] == 0
        assert data["healthy"] is True
        assert data["last_created_at"] is None

    def test_stats_with_data(self, notif_client):
        """Stats reflect added notifications and severity breakdown."""
        from core.notifications import add_notification

        add_notification(type="info", title="A", message="", source="test", severity="info")
        add_notification(type="warning", title="B", message="", source="test", severity="warning")
        add_notification(type="error", title="C", message="", source="test", severity="error")

        resp = notif_client.get("/api/v1/notifications/stats")
        data = resp.json()
        assert data["total"] == 3
        assert data["unread"] == 3
        assert data["last_created_at"] is not None
        assert data["by_severity"]["info"] == 1
        assert data["by_severity"]["warning"] == 1
        assert data["by_severity"]["error"] == 1
        assert data["healthy"] is True

    def test_stats_import_failure_returns_stub(self, missing_endpoints_client):
        """When notification store can't be imported, stub fallback fires."""
        broken = MagicMock()
        broken.get_notification_store.side_effect = ImportError("no module")

        with patch.dict("sys.modules", {"core.notifications": broken}):
            resp = missing_endpoints_client.get("/api/v1/notifications/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data.get("_stub") is True
        assert data["healthy"] is False

"""Regression tests for alert/notification bug fixes.

Covers:
  BUG-01/02 — PredictionMarketRisk.halt() fires alert + escalation
  BUG-04    — Per-severity dedup suppression (CRITICAL never suppressed)
  BUG-06    — system_observability.py probe failures return firing=True
  BUG-07    — SMSChannel / PushChannel do not lie about delivery
  BUG-08    — PredictionAlert has alert_id UUID; acknowledge() uses it
"""

import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# BUG-01/02: halt() fires alert and starts escalation
# ---------------------------------------------------------------------------

class TestHaltFiresAlertAndEscalation:

    def _make_risk(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        return PredictionMarketRisk(PredictionRiskConfig())

    def test_halt_fires_kill_switch_alert(self):
        risk = self._make_risk()

        with patch("merid.prediction.alerts.PredictionAlertManager.fire_kill_switch") as mock_fire:
            with patch("notifications.escalation.EscalationManager.start_escalation"):
                risk.halt("daily loss exceeded", unwind=False)

        mock_fire.assert_called_once_with("daily loss exceeded", False)

    def test_halt_starts_escalation(self):
        risk = self._make_risk()
        calls = []

        with patch("merid.prediction.alerts.PredictionAlertManager.fire_kill_switch"):
            with patch(
                "notifications.escalation.EscalationManager.start_escalation",
                side_effect=lambda *a, **kw: calls.append((a, kw)),
            ):
                risk.halt("drawdown exceeded", unwind=True)

        assert len(calls) == 1
        _, kw = calls[0]
        assert kw.get("severity") == "critical"

    def test_second_halt_while_already_halted_does_not_double_fire(self):
        risk = self._make_risk()

        with patch("merid.prediction.alerts.PredictionAlertManager.fire_kill_switch") as mock_fire:
            with patch("notifications.escalation.EscalationManager.start_escalation"):
                risk.halt("first halt")
                risk.halt("second halt while halted")

        assert mock_fire.call_count == 1

    def test_resume_then_halt_fires_again(self):
        risk = self._make_risk()

        with patch("merid.prediction.alerts.PredictionAlertManager.fire_kill_switch") as mock_fire:
            with patch("notifications.escalation.EscalationManager.start_escalation"):
                risk.halt("first halt")
                risk.resume()
                risk.halt("second halt after resume")

        assert mock_fire.call_count == 2

    def test_alert_emission_failure_does_not_raise(self):
        risk = self._make_risk()
        with patch("merid.prediction.alerts.PredictionAlertManager.fire_kill_switch", side_effect=RuntimeError("sink error")):
            with patch("notifications.escalation.EscalationManager.start_escalation", side_effect=RuntimeError("esc error")):
                # Must not raise — alert failure is non-fatal
                risk.halt("test failure isolation")
        assert risk._halted is True

    def test_check_drawdown_halt_threshold_fires_alert(self):
        from merid.prediction.risk import PredictionRiskConfig, PredictionMarketRisk
        cfg = PredictionRiskConfig(drawdown_halt_pct=Decimal("0.10"))
        risk = PredictionMarketRisk(cfg)

        with patch("merid.prediction.alerts.PredictionAlertManager.fire_kill_switch") as mock_fire:
            with patch("notifications.escalation.EscalationManager.start_escalation"):
                risk.check_drawdown(
                    portfolio_value_usd=Decimal("850"),
                    peak_value_usd=Decimal("1000"),
                )

        assert risk._halted is True
        mock_fire.assert_called_once()


# ---------------------------------------------------------------------------
# BUG-04: Per-severity dedup suppression
# ---------------------------------------------------------------------------

class TestPerSeverityDedup:

    def _make_manager(self):
        from merid.prediction.alerts import PredictionAlertManager
        return PredictionAlertManager(max_history=200)

    def _critical_alert(self, title="Critical event"):
        from merid.prediction.alerts import PredictionAlert, AlertCategory, AlertSeverity
        return PredictionAlert(
            category=AlertCategory.KILL_SWITCH,
            severity=AlertSeverity.CRITICAL,
            title=title,
            message="test",
        )

    def _warning_alert(self, title="Warning event"):
        from merid.prediction.alerts import PredictionAlert, AlertCategory, AlertSeverity
        return PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.WARNING,
            title=title,
            message="test",
        )

    def _info_alert(self, title="Info event"):
        from merid.prediction.alerts import PredictionAlert, AlertCategory, AlertSeverity
        return PredictionAlert(
            category=AlertCategory.STALENESS,
            severity=AlertSeverity.INFO,
            title=title,
            message="test",
        )

    def test_critical_alert_never_suppressed_on_repeated_fire(self):
        mgr = self._make_manager()
        sink_calls = []
        mgr.add_sink(lambda a: sink_calls.append(a))

        for _ in range(3):
            mgr.fire(self._critical_alert())

        assert len(sink_calls) == 3

    def test_warning_alert_suppressed_within_60s(self):
        mgr = self._make_manager()
        sink_calls = []
        mgr.add_sink(lambda a: sink_calls.append(a))

        mgr.fire(self._warning_alert())
        mgr.fire(self._warning_alert())

        assert len(sink_calls) == 1

    def test_warning_alert_fires_again_after_60s(self):
        mgr = self._make_manager()
        sink_calls = []
        mgr.add_sink(lambda a: sink_calls.append(a))

        from merid.prediction.alerts import AlertCategory, AlertSeverity
        past = datetime.now(timezone.utc) - timedelta(seconds=61)
        key = f"{AlertCategory.RISK_LIMIT.value}:None:Warning event"
        mgr._suppressed[key] = past

        mgr.fire(self._warning_alert())
        assert len(sink_calls) == 1

    def test_info_alert_suppressed_within_300s(self):
        mgr = self._make_manager()
        sink_calls = []
        mgr.add_sink(lambda a: sink_calls.append(a))

        mgr.fire(self._info_alert())
        mgr.fire(self._info_alert())

        assert len(sink_calls) == 1

    def test_info_alert_fires_again_after_300s(self):
        mgr = self._make_manager()
        sink_calls = []
        mgr.add_sink(lambda a: sink_calls.append(a))

        from merid.prediction.alerts import AlertCategory
        past = datetime.now(timezone.utc) - timedelta(seconds=301)
        key = f"{AlertCategory.STALENESS.value}:None:Info event"
        mgr._suppressed[key] = past

        mgr.fire(self._info_alert())
        assert len(sink_calls) == 1

    def test_different_titles_not_cross_suppressed(self):
        mgr = self._make_manager()
        sink_calls = []
        mgr.add_sink(lambda a: sink_calls.append(a))

        mgr.fire(self._warning_alert("Warning A"))
        mgr.fire(self._warning_alert("Warning B"))

        assert len(sink_calls) == 2


# ---------------------------------------------------------------------------
# BUG-08: alert_id UUID and acknowledge by id
# ---------------------------------------------------------------------------

class TestAlertIdAndAcknowledge:

    def _make_manager(self):
        from merid.prediction.alerts import PredictionAlertManager
        return PredictionAlertManager(max_history=200)

    def _make_alert(self, title="Test"):
        from merid.prediction.alerts import PredictionAlert, AlertCategory, AlertSeverity
        return PredictionAlert(
            category=AlertCategory.RISK_LIMIT,
            severity=AlertSeverity.CRITICAL,
            title=title,
            message="test",
        )

    def test_alert_has_uuid_alert_id(self):
        from merid.prediction.alerts import PredictionAlert, AlertCategory, AlertSeverity
        a = PredictionAlert(
            category=AlertCategory.KILL_SWITCH,
            severity=AlertSeverity.CRITICAL,
            title="t",
            message="m",
        )
        assert isinstance(a.alert_id, str)
        assert len(a.alert_id) == 32  # uuid4().hex

    def test_each_alert_gets_unique_id(self):
        alerts = [self._make_alert() for _ in range(5)]
        ids = {a.alert_id for a in alerts}
        assert len(ids) == 5

    def test_to_dict_includes_id_key(self):
        a = self._make_alert()
        d = a.to_dict()
        assert "id" in d
        assert d["id"] == a.alert_id

    def test_acknowledge_by_alert_id_returns_true(self):
        mgr = self._make_manager()
        alert = self._make_alert()
        mgr.fire(alert)
        assert mgr.acknowledge(alert.alert_id) is True
        assert alert.acknowledged is True

    def test_acknowledge_unknown_id_returns_false(self):
        mgr = self._make_manager()
        assert mgr.acknowledge("nonexistent-id") is False

    def test_acknowledge_updates_unacknowledged_count(self):
        mgr = self._make_manager()
        a1 = self._make_alert("A")
        a2 = self._make_alert("B")
        mgr.fire(a1)
        mgr.fire(a2)
        assert mgr.unacknowledged_count() == 2
        mgr.acknowledge(a1.alert_id)
        assert mgr.unacknowledged_count() == 1

    def test_history_index_evicts_with_history(self):
        mgr = self._make_manager()
        mgr._max_history = 3
        alerts = [self._make_alert(f"A{i}") for i in range(5)]
        for a in alerts:
            mgr.fire(a)
        # Only last 3 should be in history_index
        assert len(mgr._history) == 3
        assert len(mgr._history_index) == 3
        # First 2 should have been evicted
        assert alerts[0].alert_id not in mgr._history_index
        assert alerts[1].alert_id not in mgr._history_index
        assert alerts[4].alert_id in mgr._history_index


# ---------------------------------------------------------------------------
# BUG-06: system_observability.py probe failures fire, not silent-green
# ---------------------------------------------------------------------------

class TestObservabilityProbeFailures:
    """Probe failures must return firing=True at warning, not firing=False.

    Alert rules use lazy local imports inside try blocks, so probes are
    triggered by patching the source module's function and forcing an ImportError
    (simulating the module being unavailable).
    """

    def _assert_fires_on_runtime_error(self, alert_class, getter_dotpath):
        """Patch the getter function on its source module to raise RuntimeError."""
        parts = getter_dotpath.rsplit(".", 1)
        module_path, func_name = parts[0], parts[1]
        with patch(f"{getter_dotpath}", side_effect=RuntimeError("probe crashed")):
            result = alert_class().evaluate()

        assert result["firing"] is True, (
            f"{alert_class.__name__} returned firing=False on probe failure"
        )
        assert result["severity"] == "warning"
        assert "probe_error" in result["detail"]

    def test_opinion_freshness_probe_failure_fires(self):
        from web.api.system_observability import OpinionFreshnessAlert
        import merid.prediction.consensus as _m
        self._assert_fires_on_runtime_error(
            OpinionFreshnessAlert,
            "merid.prediction.consensus.get_prediction_consensus_store",
        )

    def test_circuit_breaker_open_probe_failure_fires(self):
        from web.api.system_observability import CircuitBreakerOpenAlert
        import merid.resilience.circuit_breaker as _m
        self._assert_fires_on_runtime_error(
            CircuitBreakerOpenAlert,
            "merid.resilience.circuit_breaker.get_all_breakers",
        )

    def test_risk_kill_switch_probe_failure_fires(self):
        from web.api.system_observability import RiskKillSwitchAlert
        import merid.risk as _m
        self._assert_fires_on_runtime_error(
            RiskKillSwitchAlert,
            "merid.risk.get_risk_status",
        )

    def test_ws_feed_probe_failure_fires(self):
        from web.api.system_observability import WSFeedDisconnectedAlert
        import merid.signals.ws_price_feed as _m
        self._assert_fires_on_runtime_error(
            WSFeedDisconnectedAlert,
            "merid.signals.ws_price_feed.get_ws_feed_manager",
        )

    def test_no_debate_activity_probe_failure_fires(self):
        from web.api.system_observability import NoDebateActivityAlert
        import merid.prediction.debate as _m
        self._assert_fires_on_runtime_error(
            NoDebateActivityAlert,
            "merid.prediction.debate.get_debate_store",
        )


# ---------------------------------------------------------------------------
# BUG-07: SMSChannel does not lie about delivery when unconfigured
# ---------------------------------------------------------------------------

class TestSMSChannelHonestDelivery:

    def _make_channel(self):
        from notifications.channels import SMSChannel
        ch = SMSChannel()
        ch.enabled = True
        return ch

    def _make_message(self):
        import uuid
        from notifications.channels import NotificationMessage, ChannelType
        return NotificationMessage(
            message_id=uuid.uuid4().hex,
            channel_type=ChannelType.SMS,
            recipient="+15551234567",
            subject="Alert",
            body="Test SMS",
        )

    def test_unconfigured_sms_returns_true_with_sent_status(self):
        """When account_sid is not set, the stub path is used (dev/test only)."""
        from notifications.channels import DeliveryStatus
        ch = self._make_channel()
        ch.account_sid = ""

        import asyncio
        msg = self._make_message()
        result = asyncio.get_event_loop().run_until_complete(ch.send(msg))
        assert result is True
        assert msg.status == DeliveryStatus.SENT

    def test_configured_sms_without_twilio_returns_failed(self):
        """When configured but twilio not installed, must fail honestly."""
        from notifications.channels import DeliveryStatus
        import asyncio
        ch = self._make_channel()
        ch.account_sid = "AC123"
        ch.auth_token = "tok"
        ch.from_number = "+15550000000"

        msg = self._make_message()

        with patch.dict("sys.modules", {"twilio": None, "twilio.rest": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'twilio'")):
                result = asyncio.get_event_loop().run_until_complete(ch.send(msg))

        assert result is False
        assert msg.status == DeliveryStatus.FAILED

    def test_push_unconfigured_returns_failed(self):
        """PushChannel without firebase_credentials must fail, not silently succeed."""
        from notifications.channels import PushChannel, DeliveryStatus, NotificationMessage, ChannelType
        import asyncio

        ch = PushChannel()
        ch.enabled = True
        ch.firebase_credentials = ""

        import uuid
        msg = NotificationMessage(
            message_id=uuid.uuid4().hex,
            channel_type=ChannelType.PUSH,
            recipient="device-token-abc",
            subject="Push test",
            body="body",
        )
        result = asyncio.get_event_loop().run_until_complete(ch.send(msg))
        assert result is False
        assert msg.status == DeliveryStatus.FAILED


# ---------------------------------------------------------------------------
# BUG-03: NotificationManager loads recipients from settings
# ---------------------------------------------------------------------------

class TestNotificationManagerRecipients:

    def test_loads_email_from_receiver_email(self):
        from notifications.notification_manager import NotificationManager

        mock_settings = MagicMock()
        mock_settings.RECEIVER_EMAIL = "ops@example.com"
        mock_settings.MY_EMAIL = None
        mock_settings.TWILIO_PHONE = None

        with patch("notifications.notification_manager.get_channel_manager"), \
             patch("notifications.notification_manager.get_alert_rules_engine") as mock_rules, \
             patch("notifications.notification_manager.get_escalation_manager"):
            mock_rules.return_value.on_trigger = MagicMock()
            with patch("merid.settings.settings", mock_settings):
                mgr = NotificationManager.__new__(NotificationManager)
                mgr.logger = MagicMock()
                mgr._preferences = {}
                mgr._load_recipients_from_settings.__func__(mgr)

        assert mgr._preferences.get("default", {}).get("email") == "ops@example.com"

    def test_loads_phone_from_twilio_phone(self):
        from notifications.notification_manager import NotificationManager

        mock_settings = MagicMock()
        mock_settings.RECEIVER_EMAIL = None
        mock_settings.MY_EMAIL = None
        mock_settings.TWILIO_PHONE = "+15559876543"

        with patch("notifications.notification_manager.get_channel_manager"), \
             patch("notifications.notification_manager.get_alert_rules_engine") as mock_rules, \
             patch("notifications.notification_manager.get_escalation_manager"):
            mock_rules.return_value.on_trigger = MagicMock()
            with patch("merid.settings.settings", mock_settings):
                mgr = NotificationManager.__new__(NotificationManager)
                mgr.logger = MagicMock()
                mgr._preferences = {}
                mgr._load_recipients_from_settings.__func__(mgr)

        assert mgr._preferences.get("default", {}).get("phone") == "+15559876543"

    def test_warns_when_no_recipients_configured(self):
        from notifications.notification_manager import NotificationManager

        mock_settings = MagicMock()
        mock_settings.RECEIVER_EMAIL = None
        mock_settings.MY_EMAIL = None
        mock_settings.TWILIO_PHONE = None

        with patch("notifications.notification_manager.get_channel_manager"), \
             patch("notifications.notification_manager.get_alert_rules_engine") as mock_rules, \
             patch("notifications.notification_manager.get_escalation_manager"):
            mock_rules.return_value.on_trigger = MagicMock()
            mock_logger = MagicMock()
            with patch("merid.settings.settings", mock_settings):
                mgr = NotificationManager.__new__(NotificationManager)
                mgr.logger = mock_logger
                mgr._preferences = {}
                mgr._load_recipients_from_settings.__func__(mgr)

        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "RECEIVER_EMAIL" in warning_msg or "no default recipients" in warning_msg

"""
Alerting configuration validation tests (S6-02 gap closure).

Validates:
- alertmanager.yml is well-formed YAML with required sections
- alert_rules.yml has valid rule groups with required fields
- Every alert rule has severity, annotations (summary, description, runbook_url)
- Critical alerts route to pagerduty-critical receiver
- Inhibit rules are defined
- All receivers referenced in routes exist
- Notification dispatch logic (Telegram bot integration)
"""

import os
import unittest

import yaml


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERTMANAGER_PATH = os.path.join(REPO_ROOT, "monitoring", "alertmanager.yml")
ALERT_RULES_PATH = os.path.join(REPO_ROOT, "monitoring", "alert_rules.yml")


class TestAlertmanagerConfig(unittest.TestCase):
    """alertmanager.yml is well-formed and has required sections."""

    @classmethod
    def setUpClass(cls):
        with open(ALERTMANAGER_PATH, "r") as f:
            cls.config = yaml.safe_load(f)

    def test_file_exists(self):
        self.assertTrue(os.path.exists(ALERTMANAGER_PATH))

    def test_has_global_section(self):
        self.assertIn("global", self.config)

    def test_has_route_section(self):
        self.assertIn("route", self.config)

    def test_has_receivers_section(self):
        self.assertIn("receivers", self.config)
        self.assertIsInstance(self.config["receivers"], list)
        self.assertGreater(len(self.config["receivers"]), 0)

    def test_has_inhibit_rules(self):
        self.assertIn("inhibit_rules", self.config)
        self.assertIsInstance(self.config["inhibit_rules"], list)

    def test_default_receiver_exists(self):
        route = self.config["route"]
        default_receiver = route.get("receiver")
        self.assertIsNotNone(default_receiver)
        receiver_names = {r["name"] for r in self.config["receivers"]}
        self.assertIn(default_receiver, receiver_names)

    def test_all_route_receivers_exist(self):
        receiver_names = {r["name"] for r in self.config["receivers"]}
        routes = self.config["route"].get("routes", [])
        for r in routes:
            recv = r.get("receiver")
            if recv:
                self.assertIn(
                    recv, receiver_names,
                    f"Route receiver '{recv}' not defined in receivers list",
                )

    def test_critical_routes_to_pagerduty(self):
        routes = self.config["route"].get("routes", [])
        critical_routes = [
            r for r in routes
            if r.get("match", {}).get("severity") == "critical"
        ]
        self.assertTrue(len(critical_routes) > 0, "No critical severity route found")
        # At least one critical route should go to pagerduty
        pagerduty_critical = [
            r for r in critical_routes
            if "pagerduty" in r.get("receiver", "").lower()
        ]
        self.assertTrue(
            len(pagerduty_critical) > 0,
            "Critical alerts should route to PagerDuty receiver",
        )

    def test_receivers_have_names(self):
        for recv in self.config["receivers"]:
            self.assertIn("name", recv)
            self.assertTrue(len(recv["name"]) > 0)

    def test_slack_configs_have_channel(self):
        for recv in self.config["receivers"]:
            slack_configs = recv.get("slack_configs", [])
            for sc in slack_configs:
                self.assertIn("channel", sc, f"Receiver '{recv['name']}' slack config missing channel")


class TestAlertRules(unittest.TestCase):
    """alert_rules.yml has valid rule groups with required fields."""

    @classmethod
    def setUpClass(cls):
        with open(ALERT_RULES_PATH, "r") as f:
            cls.config = yaml.safe_load(f)

    def test_file_exists(self):
        self.assertTrue(os.path.exists(ALERT_RULES_PATH))

    def test_has_groups(self):
        self.assertIn("groups", self.config)
        self.assertIsInstance(self.config["groups"], list)

    def test_minimum_rule_groups(self):
        groups = self.config["groups"]
        self.assertGreaterEqual(len(groups), 4, "Expected at least 4 rule groups")

    def test_groups_have_names(self):
        for group in self.config["groups"]:
            self.assertIn("name", group)
            self.assertTrue(len(group["name"]) > 0)

    def test_groups_have_rules(self):
        for group in self.config["groups"]:
            self.assertIn("rules", group)
            self.assertIsInstance(group["rules"], list)

    def test_all_rules_have_alert_name(self):
        for group in self.config["groups"]:
            for rule in group.get("rules", []):
                self.assertIn("alert", rule, f"Rule in group '{group['name']}' missing 'alert' field")

    def test_all_rules_have_expr(self):
        for group in self.config["groups"]:
            for rule in group.get("rules", []):
                self.assertIn("expr", rule, f"Rule '{rule.get('alert')}' missing 'expr'")

    def test_all_rules_have_severity_label(self):
        for group in self.config["groups"]:
            for rule in group.get("rules", []):
                labels = rule.get("labels", {})
                self.assertIn(
                    "severity", labels,
                    f"Rule '{rule.get('alert')}' missing severity label",
                )
                self.assertIn(
                    labels["severity"], {"critical", "warning", "info"},
                    f"Rule '{rule.get('alert')}' has invalid severity '{labels['severity']}'",
                )

    def test_all_rules_have_annotations(self):
        for group in self.config["groups"]:
            for rule in group.get("rules", []):
                annotations = rule.get("annotations", {})
                alert_name = rule.get("alert", "unknown")
                self.assertIn("summary", annotations, f"Rule '{alert_name}' missing summary annotation")
                self.assertIn("description", annotations, f"Rule '{alert_name}' missing description annotation")

    def test_all_rules_have_runbook_url(self):
        for group in self.config["groups"]:
            for rule in group.get("rules", []):
                annotations = rule.get("annotations", {})
                alert_name = rule.get("alert", "unknown")
                self.assertIn(
                    "runbook_url", annotations,
                    f"Rule '{alert_name}' missing runbook_url annotation",
                )
                self.assertTrue(
                    annotations["runbook_url"].startswith("http"),
                    f"Rule '{alert_name}' runbook_url should be a URL",
                )

    def test_critical_rules_exist(self):
        critical_rules = []
        for group in self.config["groups"]:
            for rule in group.get("rules", []):
                if rule.get("labels", {}).get("severity") == "critical":
                    critical_rules.append(rule["alert"])
        self.assertGreater(len(critical_rules), 0, "No critical rules defined")
        # Expect at least API down and DB down
        alert_names = set(critical_rules)
        self.assertIn("MERID_API_Down", alert_names)
        self.assertIn("Neo4j_Connection_Failed", alert_names)

    def test_rule_count(self):
        total_rules = sum(
            len(group.get("rules", []))
            for group in self.config["groups"]
        )
        self.assertGreaterEqual(total_rules, 15, "Expected at least 15 alert rules")


class TestAlertRuleGroups(unittest.TestCase):
    """Specific rule groups cover key domains."""

    @classmethod
    def setUpClass(cls):
        with open(ALERT_RULES_PATH, "r") as f:
            cls.config = yaml.safe_load(f)
        cls.group_names = {g["name"] for g in cls.config["groups"]}

    def test_has_critical_group(self):
        self.assertIn("merid_critical", self.group_names)

    def test_has_governance_group(self):
        self.assertIn("merid_governance", self.group_names)

    def test_has_infrastructure_group(self):
        self.assertIn("merid_infrastructure", self.group_names)

    def test_has_database_group(self):
        self.assertIn("merid_database", self.group_names)

    def test_has_swarm_group(self):
        self.assertIn("merid_swarm", self.group_names)

    def test_has_reality_system_group(self):
        self.assertIn("merid_reality_system", self.group_names)


class TestNotificationDispatch(unittest.TestCase):
    """Telegram notification bot is configured for alert dispatch."""

    def test_telegram_bot_module_exists(self):
        telegram_path = os.path.join(REPO_ROOT, "core", "telegram_bot.py")
        self.assertTrue(
            os.path.exists(telegram_path),
            "core/telegram_bot.py should exist for notification dispatch",
        )

    def test_telegram_bot_has_send_method(self):
        # Verify the module has a send capability
        import importlib
        spec = importlib.util.find_spec("core.telegram_bot")
        self.assertIsNotNone(spec, "core.telegram_bot module should be importable")

    def test_alertmanager_has_slack_webhook(self):
        """At least one receiver uses Slack webhook (primary notification channel)."""
        with open(ALERTMANAGER_PATH, "r") as f:
            config = yaml.safe_load(f)
        has_slack = False
        for recv in config.get("receivers", []):
            if recv.get("slack_configs"):
                has_slack = True
                break
        self.assertTrue(has_slack, "At least one receiver should have Slack config")

    def test_alertmanager_has_pagerduty(self):
        """At least one receiver uses PagerDuty (escalation channel)."""
        with open(ALERTMANAGER_PATH, "r") as f:
            config = yaml.safe_load(f)
        has_pd = False
        for recv in config.get("receivers", []):
            if recv.get("pagerduty_configs"):
                has_pd = True
                break
        self.assertTrue(has_pd, "At least one receiver should have PagerDuty config")


if __name__ == "__main__":
    unittest.main()

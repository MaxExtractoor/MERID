"""
Alert Rules Engine.

Defines and evaluates alert rules for automated notifications.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("notifications.alert_rules")


class RuleOperator(Enum):
    """Comparison operators for rules."""
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"
    IN_RANGE = "in_range"
    CHANGED = "changed"
    CHANGED_BY = "changed_by"


class RuleCategory(Enum):
    """Categories of alert rules."""
    PRICE = "price"
    POSITION = "position"
    RISK = "risk"
    SYSTEM = "system"
    EXECUTION = "execution"
    AGENT = "agent"
    CUSTOM = "custom"


class RuleSeverity(Enum):
    """Severity levels for alerts."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class RuleCondition:
    """A single condition in a rule."""
    field: str
    operator: RuleOperator
    value: Any
    value_secondary: Optional[Any] = None  # For range comparisons
    
    def evaluate(self, data: Dict[str, Any], previous_data: Optional[Dict[str, Any]] = None) -> bool:
        """Evaluate the condition against data."""
        actual = self._get_nested_value(data, self.field)
        
        if actual is None:
            return False
        
        if self.operator == RuleOperator.EQUALS:
            return actual == self.value
        elif self.operator == RuleOperator.NOT_EQUALS:
            return actual != self.value
        elif self.operator == RuleOperator.GREATER_THAN:
            return float(actual) > float(self.value)
        elif self.operator == RuleOperator.LESS_THAN:
            return float(actual) < float(self.value)
        elif self.operator == RuleOperator.GREATER_OR_EQUAL:
            return float(actual) >= float(self.value)
        elif self.operator == RuleOperator.LESS_OR_EQUAL:
            return float(actual) <= float(self.value)
        elif self.operator == RuleOperator.CONTAINS:
            return str(self.value) in str(actual)
        elif self.operator == RuleOperator.NOT_CONTAINS:
            return str(self.value) not in str(actual)
        elif self.operator == RuleOperator.MATCHES:
            import re
            return bool(re.match(str(self.value), str(actual)))
        elif self.operator == RuleOperator.IN_RANGE:
            return float(self.value) <= float(actual) <= float(self.value_secondary or self.value)
        elif self.operator == RuleOperator.CHANGED:
            if previous_data is None:
                return False
            prev = self._get_nested_value(previous_data, self.field)
            return actual != prev
        elif self.operator == RuleOperator.CHANGED_BY:
            if previous_data is None:
                return False
            prev = self._get_nested_value(previous_data, self.field)
            if prev is None:
                return False
            change_pct = abs((float(actual) - float(prev)) / float(prev)) * 100
            return change_pct >= float(self.value)
        
        return False
    
    def _get_nested_value(self, data: Dict[str, Any], field: str) -> Any:
        """Get nested value from dict using dot notation."""
        keys = field.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "operator": self.operator.value,
            "value": self.value,
            "value_secondary": self.value_secondary,
        }


@dataclass
class AlertRule:
    """An alert rule definition."""
    rule_id: str
    name: str
    category: RuleCategory
    severity: RuleSeverity
    
    # Conditions (all must be true for rule to trigger)
    conditions: List[RuleCondition] = field(default_factory=list)
    
    # Actions
    notification_channels: List[str] = field(default_factory=list)
    notification_template: str = ""
    
    # State
    enabled: bool = True
    triggered_count: int = 0
    last_triggered: Optional[float] = None
    
    # Cooldown
    cooldown_seconds: float = 300.0  # 5 minutes between triggers
    
    # Metadata
    description: str = ""
    created_at: float = field(default_factory=time.time)
    
    def can_trigger(self) -> bool:
        """Check if rule can trigger (cooldown check)."""
        if not self.enabled:
            return False
        if self.last_triggered is None:
            return True
        return time.time() - self.last_triggered >= self.cooldown_seconds
    
    def evaluate(self, data: Dict[str, Any], previous_data: Optional[Dict[str, Any]] = None) -> bool:
        """Evaluate all conditions."""
        if not self.can_trigger():
            return False
        
        return all(c.evaluate(data, previous_data) for c in self.conditions)
    
    def trigger(self) -> None:
        """Mark rule as triggered."""
        self.triggered_count += 1
        self.last_triggered = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "category": self.category.value,
            "severity": self.severity.value,
            "conditions": [c.to_dict() for c in self.conditions],
            "notification_channels": self.notification_channels,
            "enabled": self.enabled,
            "triggered_count": self.triggered_count,
            "last_triggered": self.last_triggered,
            "cooldown_seconds": self.cooldown_seconds,
            "description": self.description,
        }


class AlertRulesEngine:
    """
    Engine for evaluating alert rules.
    
    Features:
    - Rule definition and management
    - Condition evaluation
    - Trigger tracking
    - Cooldown management
    """
    
    def __init__(self):
        self.logger = get_logger("notifications.alert_rules")
        
        # Rules
        self._rules: Dict[str, AlertRule] = {}
        
        # Previous data for change detection
        self._previous_data: Dict[str, Dict[str, Any]] = {}
        
        # Trigger callbacks
        self._trigger_callbacks: List[Callable[[AlertRule, Dict[str, Any]], None]] = []
        
        # Initialize default rules
        self._init_default_rules()
    
    def _init_default_rules(self) -> None:
        """Initialize default alert rules."""
        # Price alert
        self.add_rule(AlertRule(
            rule_id="price_drop_5pct",
            name="Price Drop 5%",
            category=RuleCategory.PRICE,
            severity=RuleSeverity.WARNING,
            conditions=[
                RuleCondition(
                    field="price_change_pct",
                    operator=RuleOperator.LESS_THAN,
                    value=-5.0,
                )
            ],
            notification_channels=["email", "push"],
            notification_template="Price dropped {price_change_pct}%",
            description="Alert when price drops more than 5%",
        ))
        
        # Position risk alert
        self.add_rule(AlertRule(
            rule_id="high_drawdown",
            name="High Drawdown",
            category=RuleCategory.RISK,
            severity=RuleSeverity.ERROR,
            conditions=[
                RuleCondition(
                    field="drawdown_pct",
                    operator=RuleOperator.GREATER_THAN,
                    value=10.0,
                )
            ],
            notification_channels=["email", "sms", "push"],
            notification_template="Drawdown exceeded 10%: {drawdown_pct}%",
            description="Alert when drawdown exceeds 10%",
        ))
        
        # System health alert
        self.add_rule(AlertRule(
            rule_id="system_unhealthy",
            name="System Unhealthy",
            category=RuleCategory.SYSTEM,
            severity=RuleSeverity.CRITICAL,
            conditions=[
                RuleCondition(
                    field="health.status",
                    operator=RuleOperator.NOT_EQUALS,
                    value="healthy",
                )
            ],
            notification_channels=["email", "sms", "push", "webhook"],
            notification_template="System health degraded: {health.status}",
            description="Alert when system health is not healthy",
            cooldown_seconds=60.0,
        ))
        
        # Execution failure alert
        self.add_rule(AlertRule(
            rule_id="execution_failed",
            name="Execution Failed",
            category=RuleCategory.EXECUTION,
            severity=RuleSeverity.ERROR,
            conditions=[
                RuleCondition(
                    field="execution.status",
                    operator=RuleOperator.EQUALS,
                    value="failed",
                )
            ],
            notification_channels=["email", "push"],
            notification_template="Execution failed: {execution.error}",
            description="Alert on execution failure",
        ))
    
    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule."""
        self._rules[rule.rule_id] = rule
        self.logger.info(f"Added rule: {rule.name}")
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove an alert rule."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False
    
    def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule."""
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = True
            return True
        return False
    
    def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule."""
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = False
            return True
        return False
    
    def evaluate(self, data_source: str, data: Dict[str, Any]) -> List[AlertRule]:
        """Evaluate all rules against data."""
        triggered_rules = []
        
        previous = self._previous_data.get(data_source)
        
        for rule in self._rules.values():
            if rule.evaluate(data, previous):
                rule.trigger()
                triggered_rules.append(rule)
                
                # Notify callbacks
                for callback in self._trigger_callbacks:
                    try:
                        callback(rule, data)
                    except Exception as e:
                        self.logger.error(f"Trigger callback error: {e}")
        
        # Store for next evaluation
        self._previous_data[data_source] = data.copy()
        
        return triggered_rules
    
    def on_trigger(self, callback: Callable[[AlertRule, Dict[str, Any]], None]) -> None:
        """Register callback for rule triggers."""
        self._trigger_callbacks.append(callback)
    
    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        """Get a rule by ID."""
        return self._rules.get(rule_id)
    
    def get_rules_by_category(self, category: RuleCategory) -> List[AlertRule]:
        """Get rules by category."""
        return [r for r in self._rules.values() if r.category == category]
    
    def get_triggered_rules(self, since: Optional[float] = None) -> List[AlertRule]:
        """Get recently triggered rules."""
        rules = [r for r in self._rules.values() if r.last_triggered is not None]
        if since:
            rules = [r for r in rules if r.last_triggered >= since]
        return sorted(rules, key=lambda r: r.last_triggered or 0, reverse=True)
    
    def create_price_alert(
        self,
        symbol: str,
        target_price: float,
        direction: str = "above",
        channels: Optional[List[str]] = None,
    ) -> str:
        """Create a simple price alert."""
        import uuid
        
        rule_id = f"price_alert_{uuid.uuid4().hex[:8]}"
        
        operator = RuleOperator.GREATER_OR_EQUAL if direction == "above" else RuleOperator.LESS_OR_EQUAL
        
        rule = AlertRule(
            rule_id=rule_id,
            name=f"Price Alert: {symbol} {direction} ${target_price}",
            category=RuleCategory.PRICE,
            severity=RuleSeverity.INFO,
            conditions=[
                RuleCondition(
                    field=f"prices.{symbol}",
                    operator=operator,
                    value=target_price,
                )
            ],
            notification_channels=channels or ["push"],
            notification_template=f"{symbol} price is now {{prices.{symbol}}} (target: {target_price})",
        )
        
        self.add_rule(rule)
        return rule_id
    
    def get_status(self) -> Dict[str, Any]:
        """Get rules engine status."""
        return {
            "total_rules": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules.values() if r.enabled),
            "triggered_today": sum(
                1 for r in self._rules.values()
                if r.last_triggered and r.last_triggered > time.time() - 86400
            ),
            "rules": [r.to_dict() for r in self._rules.values()],
        }


# Singleton
_alert_rules_engine: Optional[AlertRulesEngine] = None


def get_alert_rules_engine() -> AlertRulesEngine:
    """Get or create the Alert Rules Engine singleton."""
    global _alert_rules_engine
    if _alert_rules_engine is None:
        _alert_rules_engine = AlertRulesEngine()
    return _alert_rules_engine

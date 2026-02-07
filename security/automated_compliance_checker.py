"""
Automated compliance checking scaffolding.

Runs policy rules over trade intents / agent actions and emits findings with
severity levels. Designed to integrate with Execution Guard before actions hit
on-chain systems.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List


logger = logging.getLogger(__name__)


@dataclass
class ComplianceRule:
    rule_id: str
    description: str
    severity: str
    expression: str  # simple eval expression for prototype


class AutomatedComplianceChecker:
    def __init__(self) -> None:
        self._rules: List[ComplianceRule] = []

    def register_rule(self, rule: ComplianceRule) -> None:
        self._rules.append(rule)

    def evaluate(self, payload: Dict[str, object]) -> List[Dict[str, str]]:
        findings: List[Dict[str, str]] = []
        for rule in self._rules:
            try:
                if self._safe_evaluate(rule.expression, payload):
                    findings.append({"rule_id": rule.rule_id, "severity": rule.severity, "description": rule.description})
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.rule_id}: {e}")
        return findings
    
    def _safe_evaluate(self, expression: str, payload: Dict[str, object]) -> bool:
        """Safely evaluate compliance rule expression without eval()."""
        import operator
        import ast
        
        # Define safe operators
        safe_ops = {
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
            ast.And: lambda a, b: a and b,
            ast.Or: lambda a, b: a or b,
            ast.Not: operator.not_,
            ast.In: lambda a, b: a in b,
            ast.NotIn: lambda a, b: a not in b,
        }
        
        def eval_node(node):
            if isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.Name):
                # Only allow access to payload
                if node.id == "payload":
                    return payload
                raise ValueError(f"Undefined variable: {node.id}")
            elif isinstance(node, ast.Subscript):
                value = eval_node(node.value)
                key = eval_node(node.slice)
                return value.get(key) if isinstance(value, dict) else None
            elif isinstance(node, (ast.List, ast.Tuple)):
                return [eval_node(elt) for elt in node.elts]
            elif isinstance(node, ast.Compare):
                left = eval_node(node.left)
                for op, comparator in zip(node.ops, node.comparators):
                    right = eval_node(comparator)
                    op_func = safe_ops.get(type(op))
                    if not op_func:
                        raise ValueError(f"Unsupported operator: {type(op)}")
                    if not op_func(left, right):
                        return False
                    left = right
                return True
            elif isinstance(node, ast.BoolOp):
                op_func = safe_ops.get(type(node.op))
                if not op_func:
                    raise ValueError(f"Unsupported operator: {type(node.op)}")
                values = [eval_node(v) for v in node.values]
                result = values[0]
                for val in values[1:]:
                    result = op_func(result, val)
                return result
            elif isinstance(node, ast.UnaryOp):
                op_func = safe_ops.get(type(node.op))
                if not op_func:
                    raise ValueError(f"Unsupported operator: {type(node.op)}")
                return op_func(eval_node(node.operand))
            else:
                raise ValueError(f"Unsupported node type: {type(node)}")
        
        try:
            tree = ast.parse(expression, mode='eval')
            return bool(eval_node(tree.body))
        except Exception as e:
            logger.error(f"Failed to evaluate expression '{expression}': {e}")
            return False

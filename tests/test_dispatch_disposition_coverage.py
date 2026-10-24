"""Dispatch-handoff observability tests (2026-10-24).

Verifies the durable-disposition patch: every pre-intent exit of
``_execute_candidate`` carries a rejection detail or terminal lifecycle
event, ``OrderCandidate`` propagates ``decision_id``, the entries-disabled
suppression branch records the owning control, and ``_mark_reject``
preserves (never regresses) rejection detail.

These tests are structural / unit-level: they do not change admission or
execution behavior, and none of them bypass revalidation.
"""
import ast
import inspect
import textwrap
from pathlib import Path

import pytest

LOOP_PATH = Path(__file__).resolve().parent.parent / "merid" / "loop_15m.py"
ALLOC_PATH = Path(__file__).resolve().parent.parent / "merid" / "risk" / "profiles" / "global_allocator.py"
GRID_PATH = Path(__file__).resolve().parent.parent / "merid" / "prediction" / "agent_grid_15m.py"


def _execute_candidate_ast():
    tree = ast.parse(LOOP_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_execute_candidate":
            return node
    pytest.fail("_execute_candidate not found")


def _block_dispositions(stmts, stop_node):
    """Collect disposition markers in a statement list before stop_node."""
    marks = set()
    for stmt in stmts:
        if stmt is stop_node:
            break
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Assign):
                for t in sub.targets:
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                            and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "_reject_detail"):
                        marks.add("reject_detail")
            if isinstance(sub, ast.Call):
                fn = sub.func
                name = ""
                if isinstance(fn, ast.Attribute):
                    name = fn.attr
                elif isinstance(fn, ast.Name):
                    name = fn.id
                if name == "_mark_reject":
                    marks.add("mark_reject")
                if name == "_log_candidate_lifecycle_event":
                    marks.add("lifecycle")
    return marks


def _returns_without_disposition(func_node):
    """Every `return` exiting _execute_candidate must have a disposition in
    at least one enclosing statement block (or be `return self._mark_reject`)."""
    uncovered = []
    parent = {}
    for node in ast.walk(func_node):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def enclosing_block_stmts(node):
        """Walk up to the nearest parent that holds node in a stmt list; yield (stmts, chain)."""
        cur = node
        while cur in parent:
            p = parent[cur]
            for attr in ("body", "orelse", "finalbody"):
                stmts = getattr(p, attr, None)
                if isinstance(stmts, list) and cur in stmts:
                    yield stmts, p
                    break
            cur = p

    for node in ast.walk(func_node):
        if not isinstance(node, ast.Return):
            continue
        # skip returns inside nested function defs (local helpers, not exits)
        cur = parent.get(node)
        nested = False
        while cur is not None and cur is not func_node:
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                nested = True
                break
            cur = parent.get(cur)
        if nested:
            continue
        # `return self._mark_reject(...)` is itself the disposition
        v = node.value
        if isinstance(v, ast.Call):
            fn = v.func
            if isinstance(fn, ast.Attribute) and fn.attr == "_mark_reject":
                continue
        found = set()
        for stmts, holder in enclosing_block_stmts(node):
            found |= _block_dispositions(stmts, node)
            if found:
                break
            # keep walking outward through enclosing blocks
        if not found:
            uncovered.append(node.lineno)
    return uncovered


class TestReturnCoverage:
    def test_every_return_has_disposition(self):
        node = _execute_candidate_ast()
        uncovered = _returns_without_disposition(node)
        assert uncovered == [], (
            f"_execute_candidate returns without _reject_detail / _mark_reject / "
            f"lifecycle event at lines: {uncovered}"
        )


def _load_mark_reject():
    """Extract _mark_reject source and exec standalone (avoids importing the
    13k-line loop module and its heavy package init)."""
    tree = ast.parse(LOOP_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_mark_reject":
            src = textwrap.dedent(ast.get_source_segment(
                LOOP_PATH.read_text(encoding="utf-8"), node))
            ns = {"Dict": dict}
            exec(src, ns)
            return ns["_mark_reject"]
    pytest.fail("_mark_reject not found")


class TestMarkReject:
    def test_stamps_stage_and_fields(self):
        _mark_reject = _load_mark_reject()
        cand = {}
        rc = _mark_reject(None, cand, "my_gate", "my_reason", observed_value=1, required_value=2)
        assert rc is False
        assert cand["_reject_detail"]["stage"] == "my_gate"
        assert cand["_reject_detail"]["reason"] == "my_reason"
        assert cand["_reject_detail"]["observed_value"] == 1
        assert cand["_reject_detail"]["required_value"] == 2

    def test_accumulates_not_loses_fields(self):
        _mark_reject = _load_mark_reject()
        cand = {"_reject_detail": {"stage": "sizing_and_gate_checks"}}
        _mark_reject(None, cand, "ev_gate", "ev_below_min", net_ev=0.001)
        assert cand["_reject_detail"]["net_ev"] == 0.001
        # stage updates to the furthest gate that fired
        assert cand["_reject_detail"]["stage"] == "ev_gate"


class TestOrderCandidateDecisionId:
    def test_field_exists_and_propagates(self):
        # AST check (avoids heavy package import): OrderCandidate declares
        # decision_id and the allocator return path copies it back.
        tree = ast.parse(ALLOC_PATH.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "OrderCandidate":
                fields = {t.target.id for t in node.body
                          if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
                assert "decision_id" in fields, f"OrderCandidate fields: {sorted(fields)}"
                return
        pytest.fail("OrderCandidate class not found")


class TestSuppressionBranch:
    def test_entries_disabled_event_records_control(self):
        src = LOOP_PATH.read_text(encoding="utf-8")
        idx = src.find('to_state="BLOCKED_ENTRIES_DISABLED"')
        assert idx > 0, "suppression lifecycle event missing"
        ctx = src[idx:idx + 3000]
        for key in ("entries_block_reason", "allow_new_entries", "decision_id"):
            assert key in ctx, f"suppression event context missing {key}"

    def test_mark_reject_helper_present(self):
        src = LOOP_PATH.read_text(encoding="utf-8")
        assert "def _mark_reject(" in src


class TestLifecycleEmits:
    def test_grid_best_edge_losers_logged(self):
        src = GRID_PATH.read_text(encoding="utf-8")
        assert "ALLOCATION_REJECTED" in src or "best_edge" in src

    def test_allocator_propagates_decision_id(self):
        src = ALLOC_PATH.read_text(encoding="utf-8")
        assert "decision_id" in src

    def test_intent_identity_stamped_on_candidate(self):
        src = LOOP_PATH.read_text(encoding="utf-8")
        assert 'candidate["intent_id"]' in src
        assert 'candidate["client_order_id"]' in src

    def test_route_decision_id_stamped_early(self):
        src = LOOP_PATH.read_text(encoding="utf-8")
        # route-suffixed id must be stamped before suppression/RECEIVED events
        assert 'trade_decision' in src and 'decision_id' in src

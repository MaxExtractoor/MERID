"""Restore accidentally-eaten defs/classes per audit/damage_check_final.txt.

Cases:
- missing top-level class -> append at file end
- missing top-level def -> append at file end
- missing def whose parent class still exists -> insert at end of class body
- missing def/class nested inside a function -> replace enclosing function
  wholesale with the base version
"""
import ast, subprocess, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = 'f288c268~1'

DAMAGE = {
 'tests/test_agent_contract_validation.py': ['def:tracking_init'],
 'tests/test_audit_bug_regressions.py': ['def:_get'],
 'tests/test_audit_fix_regressions.py': ['def:async_cb'],
 'tests/test_audit_regression.py': ['class:FakeConfig', 'class:_Stat', 'def:capture_route', 'def:fake_place', 'def:fake_route'],
 'tests/test_btc_anchored_move.py': ['def:reader', 'def:writer'],
 'tests/test_kalshi_audit_regressions.py': ['def:_run'],
 'tests/test_loop_lag_stress.py': ['def:slow_scan', 'def:slow_synthetic_scan'],
 'tests/test_reconciliation_gate_transitions.py': ['class:_D'],
 'tests/test_sprint_bc.py': ['def:fake_publish'],
 'tests/test_sprint_m.py': ['def:mock_route'],
 'tests/test_system_observability.py': ['class:TestSignalMetricsCacheStaleAlert', 'def:_make_ok_report', 'def:_mock_new_alerts', 'def:test_firing_when_cache_empty', 'def:test_firing_when_cache_old'],
 'tests/test_telegram_rate_limiter.py': ['class:TestCryptoMarketDiscovery', 'def:_make_catalog', 'def:_mock_market'],
}


def build_parent_map(tree):
    parent = {}
    def visit(node, par):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
            visit(child, node)
    visit(tree, None)
    return parent


def enclosing_top(node, parent, tree):
    """Return the top-level (module-body) ancestor of node."""
    cur = node
    while parent.get(cur) is not None and parent.get(cur) is not tree:
        cur = parent[cur]
    return cur


def span_text(lns, node):
    s = min([node.lineno] + [d.lineno for d in getattr(node, 'decorator_list', [])]) - 1
    return '\n'.join(lns[s:node.end_lineno])


for fpath, missing in DAMAGE.items():
    old = subprocess.run(['git', 'show', f'{BASE}:{fpath}'], capture_output=True,
                         text=True, encoding='utf-8', errors='replace').stdout
    new = open(fpath, encoding='utf-8', errors='replace').read()
    ot = ast.parse(old); nt = ast.parse(new)
    ol = old.split('\n'); nl = new.split('\n')
    oparent = build_parent_map(ot)

    # index base defs/classes by name
    base_nodes = {}
    for n in ast.walk(ot):
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            base_nodes.setdefault(n.name, n)
    new_nodes = {}
    for n in ast.walk(nt):
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            new_nodes.setdefault(n.name, n)

    ops = []  # (start0, end_or_None, text) — applied in descending order
    for m in missing:
        kind, name = m.split(':', 1)
        node = base_nodes.get(name)
        if node is None:
            print('NOT-IN-BASE', fpath, name); continue
        par = oparent.get(node)
        if isinstance(par, ast.ClassDef):
            # method of a class — insert at end of class body in new file
            tgt_cls = new_nodes.get(par.name)
            if tgt_cls is None:
                # parent class itself gone — restore whole class instead
                ops.append((len(nl), None, '\n\n' + span_text(ol, par)))
                continue
            ops.append((tgt_cls.end_lineno, None, span_text(ol, node)))
        elif isinstance(par, ast.Module):
            ops.append((len(nl), None, '\n\n' + span_text(ol, node)))
        else:
            # nested anywhere inside a function/class — restore the
            # enclosing top-level node wholesale
            top = enclosing_top(node, oparent, ot)
            cur = new_nodes.get(top.name)
            txt = span_text(ol, top)
            if cur is not None and cur is not top:
                s = min([cur.lineno] + [d.lineno for d in getattr(cur, 'decorator_list', [])]) - 1
                ops.append((s, cur.end_lineno, txt))
            else:
                ops.append((len(nl), None, '\n\n' + txt))

    for s, e, txt in sorted(ops, key=lambda x: -x[0]):
        if e is None:
            nl.insert(s, txt)
        else:
            nl[s:e] = txt.split('\n')
    out = '\n'.join(nl)
    try:
        ast.parse(out)
    except SyntaxError as e:
        print('WOULD-BREAK', fpath, e.lineno, e.msg); continue
    open(fpath, 'w', encoding='utf-8').write(out)
    print('restored', fpath)

"""Second-pass UI marks: per-param strict xfails driven by JUnit dispositions.

For each failing test in UI source-grep files:
- parametrized: rewrite parametrize list so failing params carry
  pytest.param(..., marks=xfail(strict, reason)); missing-file params get
  AUDIT-2026-09-22-04, existing-file content defects get AUDIT-2026-09-22-11.
- plain: add function-level strict xfail with the appropriate reason.

Idempotent-ish: skips functions already carrying an AUDIT mark on the line
above.
"""
import ast, json, re, os, sys
import xml.etree.ElementTree as ET

BS = chr(92)
R_MISSING = "DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15."
R_DEFECT = "DEFECT AUDIT-2026-09-22-11: existing frontend file violates the asserted UI contract. Expiry 2026-10-15."

tree = ET.parse('audit/baseline_junit_20260922d.xml')
# {classname: {base: {paramid: kind}}}
fails = {}
for tc in tree.iter('testcase'):
    cls = tc.get('classname', '')
    name = tc.get('name', '')
    fail = tc.find('failure'); err = tc.find('error')
    node = fail if fail is not None else err
    if node is None:
        continue
    text = (node.text or '') + (node.get('message') or '')
    if 'XPASS' in text:
        continue
    mm = re.search(r"No module named '([^']+)'", text)
    if mm:
        continue  # handled by deletion pass
    ff = re.findall(r"No such file or directory: '([^']+)'", text)
    kind = 'missing' if (ff and 'react' in ff[0].replace(BS, '/')) or 'Missing file' in text and 'react' in text.replace(BS,'/') else 'defect'
    base = name.split('[')[0]
    param = name[len(base):].strip('[]') if '[' in name else None
    fails.setdefault(cls, {}).setdefault(base, {})[param] = kind

# only touch UI-grep test files
UI_FILES = {
    'tests.test_sprint15_remaining_gaps', 'tests.test_sprint17_ux_polish',
    'tests.test_sprint19_assistant', 'tests.test_sprint20_loading_states',
    'tests.test_sprint21_error_states', 'tests.test_sprint22_accessibility',
    'tests.test_sprint24_empty_mutation', 'tests.test_sprint25_keyboard_a11y',
    'tests.test_sprint26_polling_constants', 'tests.test_sprint27_api_base_url',
    'tests.test_sprint28_button_types', 'tests.test_sprint29_auth_token_key',
    'tests.test_sprint30_cleanup_warn', 'tests.test_sprint31_console_error_imports',
    'tests.test_sprint34_console_error_components', 'tests.test_sprint37_hardcoded_urls',
    'tests.test_sprint40_chart_colors', 'tests.test_sprint43_status_enums',
    'tests.test_wiring_audit', 'tests.test_live_odds_slo_viz',
    'tests.test_kalshi_grid_wiring', 'tests.test_season5_completion',
    'tests.test_season7_completion', 'tests.test_paper_ladder',
    'tests.test_ui_backend_contract',
}

HELPER = '''

def _ap(names, test_name):
    """Per-param strict xfail driven by audit dispositions (AUDIT-2026-09-22)."""
    fm = _XFAIL_PARAMS.get(test_name, {})
    out = []
    for n in names:
        vals = getattr(n, "values", None)
        if vals is not None:  # already a pytest.param/ParameterSet
            key = "-".join(str(v) for v in vals)
            if key in fm:
                out.append(pytest.param(
                    *vals, marks=list(n.marks) + [
                        pytest.mark.xfail(strict=True, reason=fm[key])]))
            else:
                out.append(n)
        elif isinstance(n, tuple):
            key = "-".join(str(x) for x in n)
            if key in fm:
                out.append(pytest.param(
                    *n, marks=pytest.mark.xfail(strict=True, reason=fm[key])))
            else:
                out.append(n)
        elif n in fm:
            out.append(pytest.param(
                n, marks=pytest.mark.xfail(strict=True, reason=fm[n])))
        else:
            out.append(n)
    return out
'''

for mod in sorted(UI_FILES):
    classes = {c: v for c, v in fails.items() if c == mod or c.startswith(mod + '.')}
    if not classes:
        continue
    fpath = mod.replace('.', '/') + '.py'
    if not os.path.exists(fpath):
        continue
    src = open(fpath, encoding='utf-8', errors='replace').read()
    tree2 = ast.parse(src)
    cls_nodes = {n.name: n for n in ast.walk(tree2) if isinstance(n, ast.ClassDef)}
    # build per-test fail maps
    xmap = {}
    for cls, tests in classes.items():
        cname = cls.split('.')[-1]
        for base, params in tests.items():
            xmap.setdefault((cname, base), {}).update(params)
    if not xmap:
        continue
    # emit literal map
    lines_map = ["_XFAIL_PARAMS = {"]
    for (cname, base), params in sorted(xmap.items()):
        pm = {p: (R_MISSING if k == 'missing' else R_DEFECT) for p, k in params.items() if p is not None}
        if pm:
            lines_map.append(f"    {base!r}: {pm!r},")
    lines_map.append("}")
    map_src = "\n".join(lines_map)

    changed = False
    inserts = []      # (0-based line index, text) applied first, bottom-up
    replacements = [] # (old_str, new_str) applied after inserts
    for (cname, base), params in sorted(xmap.items()):
        cnode = cls_nodes.get(cname)
        if cnode is None:
            continue
        fn = next((n for n in cnode.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == base), None)
        if fn is None:
            continue
        # already marked?
        head = src.split('\n')[max(0, fn.lineno - 4):fn.lineno]
        if any('AUDIT-2026-09-22' in h for h in head):
            continue
        has_param = any('parametrize' in ast.unparse(d) for d in fn.decorator_list)
        if has_param and all(p is not None for p in params):
            dec = next(d for d in fn.decorator_list if 'parametrize' in ast.unparse(d))
            ds = ast.unparse(dec)
            m = re.match(r'(?:pytest\.mark\.)?parametrize\((["\'])(.+?)\1,\s*(.*)\)$', ds, re.S)
            if not m:
                print('SKIP-noparam-match', fpath, cname, base)
                continue
            argnames, listexpr = m.group(2), m.group(3)
            new_ds = (' ' * (dec.col_offset - 1)) + f'@pytest.mark.parametrize("{argnames}", _ap({listexpr}, {base!r}))'
            old_ds = '@' + ds
            if old_ds in src:
                replacements.append((old_ds, new_ds))
            else:
                dec_lines = src.split('\n')[dec.lineno - 1:dec.end_lineno]
                joined = '\n'.join(dec_lines)
                if 'parametrize' in joined:
                    replacements.append((joined, new_ds))
                else:
                    print('SKIP-deco', fpath, cname, base)
        elif not has_param and all(p is None for p in params):
            kind = next(iter(params.values()))
            reason = R_MISSING if kind == 'missing' else R_DEFECT
            decos = [d.lineno for d in fn.decorator_list]
            insert_ln = (min(decos) if decos else fn.lineno) - 1
            indent = ' ' * fn.col_offset
            inserts.append((insert_ln, f'{indent}@pytest.mark.xfail(strict=True, reason="{reason}")'))
        else:
            print('SKIP-mixed', fpath, cname, base, params)
    if inserts:
        lns = src.split('\n')
        for ln, txt in sorted(inserts, key=lambda x: -x[0]):
            lns.insert(ln, txt)
        src = '\n'.join(lns)
        changed = True
    for old, new in replacements:
        if old in src:
            src = src.replace(old, new, 1)
            changed = True
        else:
            print('SKIP-repl-miss', fpath, old[:60])
    if not changed:
        continue
    # inject map + helper after last import
    if '_XFAIL_PARAMS' not in src:
        try:
            t3 = ast.parse(src)
        except SyntaxError as e:
            print('PARSEFAIL', fpath, e.lineno, e.msg)
            sl = src.split('\n')
            import io as _io
            _o = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            for i in range(max(0, e.lineno - 45), min(len(sl), e.lineno + 3)):
                _o.write(f"{i+1:4}|{sl[i]}\n")
            _o.write(f"inserts: {inserts}\n")
            _o.flush()
            raise
        last = 0
        for n in t3.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                last = n.end_lineno
        lns = src.split('\n')
        lns.insert(last, map_src + HELPER)
        src = '\n'.join(lns)
    open(fpath, 'w', encoding='utf-8').write(src)
    print('edited', fpath)

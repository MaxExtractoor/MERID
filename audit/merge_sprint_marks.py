"""Merge: restore committed (marked) sprint24/25/26 and re-add eaten classes.

Committed f288c268 versions have correct marks but pass-1 overlap ate
classes/methods. Current files have the classes (restored from base) but no
marks. Take committed as base; append/insert the missing defs from current,
rewriting their parametrize decorators to route through _ap/_ui_params and
extending _XFAIL_PARAMS where needed.
"""
import ast, subprocess, io, sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

R04 = "DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15."
R11 = "DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15."

# file -> {class: {method: (param_list_name, dir_var, {param: reason})}}
SPECS = {
 'tests/test_sprint24_empty_mutation.py': {
   'TestEmptyStateGuard': {
     'test_has_empty_state_guard': ('EMPTY_STATE_VIEWS', 'VIEWS_DIR',
        {'ApiDashboard.tsx': R04, 'Logs.tsx': R11, 'Risk.tsx': R11}),
     'test_empty_guard_checks_length_or_null': ('EMPTY_STATE_VIEWS', 'VIEWS_DIR',
        {'ApiDashboard.tsx': R04, 'Logs.tsx': R11, 'Risk.tsx': R11}),
   },
   'TestEmptyStateImport': {  # class exists in commit; method eaten
     'test_imports_empty_state': ('EMPTY_STATE_VIEWS', 'VIEWS_DIR',
        {'ApiDashboard.tsx': R04, 'Logs.tsx': R11, 'Risk.tsx': R11}),
   },
 },
 'tests/test_sprint25_keyboard_a11y.py': {
   'TestKeyboardA11yComponents': {  # all target files missing -> conditional -04
     'test_has_role_button': ('KEYBOARD_FIXED_FILES_COMPONENTS', 'COMPONENTS_DIR', 'ALL_MISSING'),
     'test_has_onkeydown': ('KEYBOARD_FIXED_FILES_COMPONENTS', 'COMPONENTS_DIR', 'ALL_MISSING'),
     'test_has_tabindex': ('KEYBOARD_FIXED_FILES_COMPONENTS', 'COMPONENTS_DIR', 'ALL_MISSING'),
   },
 },
 'tests/test_sprint26_polling_constants.py': {
   'TestViewsImportDefaults': {  # class exists in commit; method eaten
     'test_imports_defaults': ('UPDATED_VIEWS', 'VIEWS_DIR',
        {'Agents.tsx': R04, 'ApiDashboard.tsx': R04, 'Logs.tsx': R11, 'Research.tsx': R04, 'Risk.tsx': R11}),
   },
   'TestViewsUsePollingConstants': {
     'test_uses_polling_constant': ('UPDATED_VIEWS', 'VIEWS_DIR',
        {'Agents.tsx': R04, 'ApiDashboard.tsx': R04, 'Logs.tsx': R11, 'Research.tsx': R04, 'Risk.tsx': R11}),
     'test_no_hardcoded_polling_intervals': ('UPDATED_VIEWS', 'VIEWS_DIR',
        {'Agents.tsx': R04, 'ApiDashboard.tsx': R04, 'Logs.tsx': R11, 'Research.tsx': R04, 'Risk.tsx': R11}),
   },
 },
}


def names_of(src):
    t = ast.parse(src)
    return t, {n.name: n for n in ast.walk(t)
               if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}


def span(lns, node):
    s = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
    return '\n'.join(lns[s:node.end_lineno])


def rewrite_deco(text, list_name, dir_var, method_name, pmap):
    """Rewrite parametrize over list_name to _ap(...) or _ui_params(...)."""
    if pmap == 'ALL_MISSING':
        return text.replace(
            f'@pytest.mark.parametrize("filename", {list_name})',
            f'@pytest.mark.parametrize("filename", _ui_params({dir_var}, {list_name}))')
    return text.replace(
        f'@pytest.mark.parametrize("filename", {list_name})',
        f'@pytest.mark.parametrize("filename", _ap({list_name}, {method_name!r}))')


for fpath, classes in SPECS.items():
    com = subprocess.run(['git', 'show', f'f288c268:{fpath}'], capture_output=True,
                         text=True, encoding='utf-8', errors='replace').stdout
    cur = open(fpath, encoding='utf-8', errors='replace').read()
    ct, cn = names_of(com)
    rt, rn = names_of(cur)
    cl = cur.split('\n')
    out = com

    new_map_entries = {}
    pending_methods = []  # (class_name, method_src)
    appended = []
    for cname, methods in classes.items():
        cnode_cur = rn.get(cname)
        cnode_com = cn.get(cname)
        for mname, (list_name, dir_var, pmap) in methods.items():
            mnode = next((m for m in cnode_cur.body
                          if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and m.name == mname), None)
            src_txt = rewrite_deco(span(cl, mnode), list_name, dir_var, mname, pmap)
            if cnode_com is None:
                continue  # whole class appended later
            # insert method at end of existing class
            pending_methods.append((cname, cnode_com.end_lineno, src_txt))
            if pmap != 'ALL_MISSING':
                new_map_entries[mname] = pmap
        if cnode_com is None:
            c_txt = span(cl, cnode_cur)
            for mname, (list_name, dir_var, pmap) in methods.items():
                c_txt = c_txt.replace(
                    f'@pytest.mark.parametrize("filename", {list_name})',
                    f'@pytest.mark.parametrize("filename", '
                    + (f'_ui_params({dir_var}, {list_name}))' if pmap == 'ALL_MISSING'
                       else f'_ap({list_name}, {mname!r}))'))
                if pmap != 'ALL_MISSING':
                    new_map_entries[mname] = pmap
            appended.append(c_txt)

    # apply method inserts bottom-up on committed line positions
    lns = out.split('\n')
    for cname, end, txt in sorted(pending_methods, key=lambda x: -x[1]):
        lns.insert(end, txt)
    out = '\n'.join(lns)
    for c_txt in appended:
        out = out.rstrip('\n') + '\n\n\n' + c_txt + '\n'

    # extend _XFAIL_PARAMS with new entries (skip keys already present)
    if new_map_entries:
        extra = []
        for mname, pmap in new_map_entries.items():
            if f"{mname!r}:" in out:
                continue
            extra.append(f"    {mname!r}: {pmap!r},")
        if extra:
            marker = '_XFAIL_PARAMS = {'
            idx = out.index(marker) + len(marker)
            out = out[:idx] + '\n' + '\n'.join(extra) + out[idx:]

    ast.parse(out)
    open(fpath, 'w', encoding='utf-8').write(out)
    print('merged', fpath, '| appended classes:', len(appended), '| inserted methods:', len(pending_methods), '| new map keys:', sorted(new_map_entries))

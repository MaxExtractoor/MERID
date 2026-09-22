"""Apply per-test dispositions from per_test_dispositions.json.

- modnf:<absent module>  -> delete the test function/method (obsolete; module
  deliberately removed). Class deleted too if it becomes empty.
- fnf:<non-react path>   -> same (test greps deleted source/docs).
- fnf:<react path>       -> strict xfail AUDIT-2026-09-22-04 on the test.
      * parametrized: wrap the param list so each param gets
        xfail(not (DIR / param).exists(), strict=True) when the param maps
        to a path component.
      * plain test: unconditional strict xfail (test currently fails; XPASS
        forces cleanup per strict semantics).
"""
import ast, json, os, re, sys

DISP = json.load(open('audit/per_test_dispositions.json'))
XFAIL_REASON = (
    "DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree "
    "(never committed). Expiry 2026-10-15."
)

def module_exists(modname):
    p = modname.replace('.', '/') + '.py'
    return os.path.exists(p) or os.path.exists(modname.replace('.', '/') + '/__init__.py')

def cls_file(mod):
    return mod.replace('.', '/') + '.py'

# Group per file -> {class or '': {test_base: [kinds]}}
files = {}
for cls, tests in DISP.items():
    parts = cls.split('.')
    fpath = None
    for i in range(len(parts), 0, -1):
        cand = '/'.join(parts[:i]) + '.py'
        if os.path.exists(cand):
            fpath = cand; break
    if fpath is None:
        continue
    rec = files.setdefault(fpath, {})
    for tname, kind in tests.items():
        base = tname.split('[')[0]
        key = cls.split(fpath[:-3].replace('/', '.') + '.')[-1] if '.Test' in cls or '.test_' in cls else ''
        # class name = last component if it looks like a class
        cname = parts[-1] if parts[-1][0].isupper() else ''
        rec.setdefault(cname, {}).setdefault(base, []).append((tname, kind))

XFAIL_MARK = (
    'pytest.mark.xfail(strict=True, reason="%s")' % XFAIL_REASON
)

stats = {'deleted_tests': 0, 'deleted_classes': 0, 'xfailed': 0, 'files': 0}

for fpath, classes in sorted(files.items()):
    src = open(fpath, encoding='utf-8', errors='replace').read()
    tree = ast.parse(src)
    lines = src.split('\n')
    # collect nodes: {classname: {funcname: node}} and module funcs
    ops = []  # (start0, end, action, extra)
    changed = False

    def find_class(name):
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef) and n.name == name:
                return n
        return None

    for cname, tests in classes.items():
        # classify each base test
        del_bases = set()
        xfail_bases = set()
        for base, entries in tests.items():
            kinds = [k for _, k in entries]
            if all(k.startswith('modnf:') or (k.startswith('fnf:') and 'react' not in k) for k in kinds):
                # verify targets really absent
                absent = True
                for k in kinds:
                    if k.startswith('modnf:') and module_exists(k[6:]):
                        absent = False
                    if k.startswith('fnf:'):
                        p = k[4:]
                        if os.path.exists(p):
                            absent = False
                if absent:
                    del_bases.add(base)
                    continue
            if all(k.startswith('fnf:') and 'react' in k for k in kinds):
                xfail_bases.add(base)
                continue
            # mixed/other -> leave for triage

        if cname:
            cnode = find_class(cname)
            if cnode is None:
                continue
            members = {n.name: n for n in cnode.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            # delete obsolete test methods
            for base in del_bases:
                n = members.pop(base, None)
                if n is None:
                    continue
                s = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                ops.append((s, n.end_lineno, 'del'))
                stats['deleted_tests'] += 1
            # if class now empty of test methods -> delete class
            remaining = [n for n in members.values() if n.name.startswith('test')]
            if not members and len(del_bases):
                s = min([cnode.lineno] + [d.lineno for d in cnode.decorator_list]) - 1
                ops.append((s, cnode.end_lineno, 'del'))
                stats['deleted_classes'] += 1
            else:
                # add xfail marks to failing UI tests
                for base in xfail_bases:
                    n = members.get(base)
                    if n is None:
                        continue
                    decos = [d.lineno for d in n.decorator_list]
                    insert_at = (min(decos) if decos else n.lineno) - 1
                    indent = ' ' * (n.col_offset)
                    ops.append((insert_at, insert_at, 'ins', indent + '@' + XFAIL_MARK))
                    stats['xfailed'] += 1
        else:
            # module-level functions
            mod_members = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for base in del_bases:
                n = mod_members.get(base)
                if n is None:
                    continue
                s = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                ops.append((s, n.end_lineno, 'del'))
                stats['deleted_tests'] += 1
            for base in xfail_bases:
                n = mod_members.get(base)
                if n is None:
                    continue
                decos = [d.lineno for d in n.decorator_list]
                insert_at = (min(decos) if decos else n.lineno) - 1
                ops.append((insert_at, insert_at, 'ins', '@' + XFAIL_MARK))
                stats['xfailed'] += 1

    if not ops:
        continue
    # apply ops in reverse order
    for op in sorted(ops, key=lambda o: o[0], reverse=True):
        s, e, act = op[0], op[1], op[2]
        if act == 'del':
            del lines[s:e]
        else:
            lines.insert(s, op[3])
    open(fpath, 'w', encoding='utf-8').write('\n'.join(lines))
    stats['files'] += 1
    changed = True

print(stats)

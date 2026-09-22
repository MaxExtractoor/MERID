"""Repair files damaged by the pass-1 overlap bug.

For each file in the damage list: restore from d87a3776 (pre-disposition
state — contains the legit first-commit test edits), then re-apply the
INTENDED dispositions with the overlap bug fixed:

1. delete classes listed in obsolete_classes.json (whole-class deletion
   only when every member is being removed)
2. delete obsolete test methods: disp bases that are modnf or non-react fnf
   (all-targets-absent verified) plus pass-2 import/attr-obsolete bases
3. does NOT re-apply xfail marks — the UI mark pass runs separately after
"""
import ast, os, re, io, sys, json, pathlib, subprocess
import xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = 'f288c268~1'

obsolete = json.load(open('audit/obsolete_classes.json'))
disp = json.load(open('audit/per_test_dispositions.json'))
damaged = [l.split(' ', 1)[0] for l in open('audit/pass1_damage_check3.txt', encoding='utf-8')
           if l.startswith('tests/')]


def mod_exists(modname):
    p = modname.replace('.', '/')
    return os.path.exists(p + '.py') or os.path.exists(p + '/__init__.py')


def check(mod, attr):
    mp = pathlib.Path(mod.replace('.', '/'))
    mod_file = mp.with_suffix('.py') if mp.with_suffix('.py').exists() else (mp / '__init__.py' if (mp / '__init__.py').exists() else None)
    if mod_file is None:
        return False
    if (mp.parent / (attr + '.py')).exists() or (mp.parent / attr / '__init__.py').exists() or (mp / (attr + '.py')).exists():
        return True
    src = mod_file.read_text(encoding='utf-8', errors='replace')
    if '__getattr__' in src:
        return True
    return bool(re.search(rf'(?m)^\s*(def|class)\s+{re.escape(attr)}\b|^\s*{re.escape(attr)}\s*[:=]', src))


# pass-2 obsolete test bases
tree = ET.parse('audit/baseline_junit_20260922d.xml')
p2 = {}
for tc in tree.iter('testcase'):
    node = tc.find('failure'); node = node if node is not None else tc.find('error')
    if node is None:
        continue
    text = (node.text or '') + (node.get('message') or '')
    targets = []
    for m in re.finditer(r"cannot import name '([^']+)' from '([^']+)'", text):
        targets.append((m.group(2), m.group(1)))
    for m in re.finditer(r"module '([^']+)' has no attribute '([^']+)'", text):
        targets.append((m.group(1), m.group(2)))
    if targets and all(not check(mo, a) for mo, a in targets):
        p2.setdefault(tc.get('classname', '?'), set()).add(tc.get('name', '?').split('[')[0])

# per-file obsolete test bases from disp (modnf + non-react fnf, verified absent)
disp_del = {}
for cls, tests in disp.items():
    parts = cls.split('.')
    fpath = None
    for i in range(len(parts), 0, -1):
        cand = '/'.join(parts[:i]) + '.py'
        if os.path.exists(cand):
            fpath = cand; break
    if fpath is None:
        continue
    cname = parts[-1] if parts[-1][0].isupper() else ''
    for tname, kind in tests.items():
        base = tname.split('[')[0]
        kinds = kind if isinstance(kind, list) else [kind]
        ok = all(k.startswith('modnf:') or (k.startswith('fnf:') and 'react' not in k) for k in kinds)
        if not ok:
            continue
        absent = True
        for k in kinds:
            if k.startswith('modnf:') and mod_exists(k[6:]):
                absent = False
            if k.startswith('fnf:') and os.path.exists(k[4:]):
                absent = False
        if absent:
            disp_del.setdefault(fpath, {}).setdefault(cname, set()).add(base)

stats = {'files': 0, 'del_tests': 0, 'del_classes': 0}
for fpath in damaged:
    old = subprocess.run(['git', 'show', f'{BASE}:{fpath}'], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    if not old.strip():
        print('NO-BASE', fpath); continue
    try:
        tree2 = ast.parse(old)
    except SyntaxError:
        print('BASE-SYNTAX', fpath); continue
    lns = old.split('\n')
    mod = fpath[:-3].replace('/', '.')
    del_classes = {c for c, _ in (obsolete.get(mod) or [])}
    ops = []
    cls_nodes = {n.name: n for n in ast.walk(tree2) if isinstance(n, ast.ClassDef)}
    # collect per-class obsolete test bases
    cls_bases = {}
    for cls, bases in disp_del.get(fpath, {}).items():
        if cls:
            cls_bases.setdefault(cls, set()).update(bases)
        else:
            cls_bases.setdefault('', set()).update(bases)
    for cls, bases in p2.items():
        if not cls.startswith(mod):
            continue
        cname = cls.split('.')[-1]
        if cname and cname in cls_nodes:
            cls_bases.setdefault(cname, set()).update(bases)
        else:
            cls_bases.setdefault('', set()).update(bases)  # module-level
    for cname, bases in cls_bases.items():
        if cname:
            cnode = cls_nodes.get(cname)
            if cnode is None:
                continue
            members = {n.name: n for n in cnode.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            test_members = {k for k in members if k.startswith('test')}
            if cname in del_classes or (test_members and test_members.issubset(bases)):
                # delete whole class — covers methods, no overlap
                s = min([cnode.lineno] + [d.lineno for d in cnode.decorator_list]) - 1
                ops.append((s, cnode.end_lineno, 'class', cname))
                stats['del_classes'] += 1
                stats['del_tests'] += len(test_members)
            else:
                for base in bases:
                    n = members.get(base)
                    if n is None:
                        continue
                    s = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                    ops.append((s, n.end_lineno, 'fn', base))
                    stats['del_tests'] += 1
        else:
            for base in bases:
                for n in tree2.body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == base:
                        s = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                        ops.append((s, n.end_lineno, 'fn', base))
                        stats['del_tests'] += 1
    # also delete classes flagged obsolete even without disp entries
    for cname in del_classes:
        cnode = cls_nodes.get(cname)
        if cnode is None:
            continue
        if any(o[3] == cname for o in ops):
            continue
        s = min([cnode.lineno] + [d.lineno for d in cnode.decorator_list]) - 1
        ops.append((s, cnode.end_lineno, 'class', cname))
        stats['del_classes'] += 1
    # drop ops nested inside a deleted class
    class_spans = [(s, e) for s, e, t, _ in ops if t == 'class']
    ops = [o for o in ops if o[2] == 'class' or not any(cs <= o[0] < ce for cs, ce in class_spans)]
    for s, e, t, name in sorted(ops, key=lambda o: -o[0]):
        del lns[s:e]
    out = '\n'.join(lns)
    try:
        ast.parse(out)
    except SyntaxError as e:
        print('WOULD-BREAK', fpath, e); continue
    open(fpath, 'w', encoding='utf-8').write(out)
    stats['files'] += 1
    print('repaired', fpath)
print(stats)

"""Second-order obsolete-test deletion: tests failing on ImportError
'cannot import name X from Y' or AttributeError 'module M has no attribute A'
where the target module/submodule/symbol was deliberately removed in the
Phase-1 legacy sweep or the 15m production refactor (verified via git log -S).

A test is deleted only when EVERY failing target it references is absent.
"""
import ast, os, re, io, sys, pathlib
import xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def check(mod, attr):
    mp = pathlib.Path(mod.replace('.', '/'))
    mod_file = mp.with_suffix('.py') if mp.with_suffix('.py').exists() else (mp / '__init__.py' if (mp / '__init__.py').exists() else None)
    if mod_file is None:
        return False
    if (mp.parent / (attr + '.py')).exists() or (mp.parent / attr / '__init__.py').exists() or (mp / (attr + '.py')).exists():
        return True
    src = mod_file.read_text(encoding='utf-8', errors='replace')
    if '__getattr__' in src:
        return True  # dynamic attrs — can't statically prove absence
    return bool(re.search(
        rf'(?m)^\s*(def|class)\s+{re.escape(attr)}\b|^\s*{re.escape(attr)}\s*[:=]', src))

# collect failing tests per (classname) with their absent targets
tree = ET.parse('audit/baseline_junit_20260922d.xml')
tests = {}  # cls -> {base: set(absent_targets)}
for tc in tree.iter('testcase'):
    node = tc.find('failure'); node = node if node is not None else tc.find('error')
    if node is None:
        continue
    text = (node.text or '') + (node.get('message') or '')
    if 'XPASS' in text:
        continue
    targets = []
    for m in re.finditer(r"cannot import name '([^']+)' from '([^']+)'", text):
        targets.append((m.group(2), m.group(1)))
    for m in re.finditer(r"module '([^']+)' has no attribute '([^']+)'", text):
        targets.append((m.group(1), m.group(2)))
    if not targets:
        continue
    if all(not check(mod, attr) for mod, attr in targets):
        cls = tc.get('classname', '?'); name = tc.get('name', '?')
        base = name.split('[')[0]
        tests.setdefault(cls, {}).setdefault(base, set()).update(targets)

# group by file
files = {}
for cls, bases in tests.items():
    parts = cls.split('.')
    fpath = None
    for i in range(len(parts), 0, -1):
        cand = '/'.join(parts[:i]) + '.py'
        if os.path.exists(cand):
            fpath = cand; break
    if fpath is None:
        continue
    cname = parts[-1] if parts[-1][0].isupper() else ''
    files.setdefault(fpath, {}).setdefault(cname, set()).update(bases)

stats = {'deleted': 0, 'classes': 0, 'files': 0}
for fpath, classes in sorted(files.items()):
    src = open(fpath, encoding='utf-8', errors='replace').read()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        print('SYNTAX-SKIP', fpath); continue
    lns = src.split('\n')
    ops = []
    cls_nodes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    for cname, bases in classes.items():
        if cname:
            cnode = cls_nodes.get(cname)
            if cnode is None:
                continue
            members = {n.name: n for n in cnode.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            remaining = {k: v for k, v in members.items() if k not in bases}
            if bases and not remaining:
                # whole class deleted — its span covers the methods; do NOT
                # also queue per-method deletions (stale spans would eat the
                # next class after the list mutates)
                s = min([cnode.lineno] + [d.lineno for d in cnode.decorator_list]) - 1
                ops.append((s, cnode.end_lineno))
                stats['deleted'] += len(bases)
                stats['classes'] += 1
            else:
                for base in bases:
                    n = members.get(base)
                    if n is None:
                        continue
                    s = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                    ops.append((s, n.end_lineno))
                    stats['deleted'] += 1
        else:
            mod_members = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for base in bases:
                n = mod_members.get(base)
                if n is None:
                    continue
                s = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                ops.append((s, n.end_lineno))
                stats['deleted'] += 1
    if not ops:
        continue
    for s, e in sorted(ops, reverse=True):
        del lns[s:e]
    out = '\n'.join(lns)
    try:
        ast.parse(out)
    except SyntaxError as e:
        print('WOULD-BREAK', fpath, e); continue
    open(fpath, 'w', encoding='utf-8').write(out)
    stats['files'] += 1
    print('edited', fpath)
print(stats)

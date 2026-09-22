import re, os
from pathlib import Path
root = Path('.')
missing_targets = {}
test_files = []
for dirpath, dirs, files in os.walk('tests'):
    for fn in files:
        if fn.startswith('test_') and fn.endswith('.py'):
            test_files.append(Path(dirpath)/fn)
pat = re.compile(r'(?:web[/\\]react[/\\]src[/\\]|REACT_SRC\s*/\s*)(["\'])([\w\-./\\]+\.(?:tsx|ts))\1')
for tf in test_files:
    try:
        src = tf.read_text(encoding='utf-8', errors='replace')
    except Exception:
        continue
    for _, t in pat.findall(src):
        t = t.replace('\\', '/')
        if not t.startswith('web/'):
            t = 'web/react/src/' + t
        if not (root/t).exists():
            missing_targets.setdefault(str(tf), set()).add(t)
for tf, ts in sorted(missing_targets.items()):
    print(f"{tf}: {len(ts)} missing -> {sorted(ts)[:4]}")

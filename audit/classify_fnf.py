import xml.etree.ElementTree as ET, collections, re, sys

tree = ET.parse('audit/baseline_junit_20260922d.xml')
cls_paths = collections.defaultdict(set)
per_cls = collections.defaultdict(lambda: collections.Counter())
BS = chr(92)
for tc in tree.iter('testcase'):
    cls = tc.get('classname', '')
    fail = tc.find('failure'); err = tc.find('error'); sk = tc.find('skipped')
    st = 'pass'; text = ''
    if fail is not None:
        st = 'XPASS' if 'XPASS' in (fail.get('message') or '') else 'fail'
        text = (fail.text or '') + (fail.get('message') or '')
    elif err is not None:
        st = 'error'; text = (err.text or '') + (err.get('message') or '')
    elif sk is not None:
        st = 'xfail' if sk.get('type') == 'pytest.xfail' else 'skip'
    per_cls[cls][st] += 1
    if st in ('fail', 'error'):
        for x in re.findall(r"No such file or directory: '([^']+)'", text) + re.findall("Missing file: ([^'" + chr(10) + "]+)", text):
            norm = x.replace(BS, '/')
            if 'MERID' in norm:
                norm = norm.split('MERID')[-1]
            cls_paths[cls].add(norm.lstrip('/'))

for cls, paths in sorted(cls_paths.items()):
    react = [p for p in paths if '/react/' in p or 'web/react' in p]
    other = [p for p in paths if p not in react]
    kind = 'UI' if react and not other else ('OBSOLETE' if other and not react else 'MIXED')
    c = per_cls[cls]
    print(f"{c['fail']+c['error']:3d}bad {c['pass']:3d}p {kind:8s} {cls} :: {sorted(other)[:3] if kind != 'UI' else sorted(react)[:3]}")

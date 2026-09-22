"""Per-test failure disposition extraction from baseline JUnit.

Outputs JSON: {classname: {testname: kind}} where kind is
 'modnf:<module>' | 'fnf:<path>' | 'other:<sig>'
"""
import xml.etree.ElementTree as ET
import collections, re, json

BS = chr(92)
tree = ET.parse('audit/baseline_junit_20260922d.xml')
out = collections.defaultdict(dict)

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
        out[cls][name] = 'modnf:' + mm.group(1)
        continue
    ff = re.findall(r"No such file or directory: '([^']+)'", text) or re.findall("Missing file: ([^'" + chr(10) + "]+)", text)
    if ff:
        p = ff[0].replace(BS, '/')
        if 'MERID' in p:
            p = p.split('MERID')[-1]
        out[cls][name] = 'fnf:' + p.lstrip('/')
        continue
    first = [l for l in text.split(chr(10)) if l.strip()]
    out[cls][name] = 'other:' + (first[-1][:80] if first else '?')

json.dump(out, open('audit/per_test_dispositions.json', 'w'), indent=1)
kinds = collections.Counter(v.split(':')[0] for v2 in out.values() for v in v2.values())
print(kinds)
print('classes:', len(out))

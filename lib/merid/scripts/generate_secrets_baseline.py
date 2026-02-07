#!/usr/bin/env python3
import subprocess
import sys
p = subprocess.run(['detect-secrets', 'scan', '--all-files'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
open('.secrets.baseline', 'wb').write(p.stdout)
if p.returncode != 0:
    print('detect-secrets returned non-zero:', p.returncode, file=sys.stderr)
    print(p.stderr.decode(), file=sys.stderr)
else:
    print('Baseline written to .secrets.baseline')
import re
from pathlib import Path

BASE_DIRS = [Path('.')]
KEY_PATTERN = re.compile(r'^([A-Z0-9_]+)\s*=[^=]*$')

flags = {}

def record(flag, source, line, val=None):
    flags.setdefault(flag, {'sources': [], 'value': None})
    flags[flag]['sources'].append((source, line))
    if val is not None:
        flags[flag]['value'] = val

# parse .env
env_path = Path('.env')
if env_path.exists():
    for i,line in enumerate(env_path.read_text().splitlines(),1):
        line=line.strip()
        if not line or line.startswith('#'):
            continue
        m=KEY_PATTERN.match(line)
        if m:
            key=m.group(1)
            record(key, '.env', i, line.split('=',1)[1].strip())

# parse settings (Pydantic) lines
settings_path = Path('merid/settings.py')
if settings_path.exists():
    for i,line in enumerate(settings_path.read_text().splitlines(),1):
        if ':' in line:
            before=line.split(':')[0].strip()
            if before.isupper():
                record(before, 'merid/settings.py', i)

# parse paper config dataclasses names? search uppercase names with default bool l??
paper_path = Path('merid/paper_config.py')
if paper_path.exists():
    for i,line in enumerate(paper_path.read_text().splitlines(),1):
        tokens=re.findall(r'([A-Z0-9_]+)\s*=\s*(True|False)', line)
        for key,_ in tokens:
            record(key, 'merid/paper_config.py', i)

# filter relevant keywords
relevant = {k:v for k,v in flags.items() if any(tok in k for tok in ('SWARM','DOMAIN','AGENT','KALSHI','MERID_PM','MERID_SWARM','PROMOTION','PREDICTION'))}

print('FLAG | VALUE | SOURCE LOCATIONS | EXAMPLE USES')
for flag,(data) in sorted(relevant.items()):
    occurrences=[]
    for base in BASE_DIRS:
        for path in base.rglob('*'):
            if path.suffix in {'.py','.tsx','.ts'}:
                try:
                    text=path.read_text()
                except Exception:
                    continue
                if flag in text:
                    occurrences.append(str(path))
    print(f"{flag} | {data['value']} | {data['sources']} | {occurrences[:3]}{'...' if len(occurrences)>3 else ''}")

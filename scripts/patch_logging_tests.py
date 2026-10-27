"""Patch stale logging tests that import the non-existent merid_logging module."""
import os

logging_dir = r'c:\Dev\MERID\tests\logging'
files = [f for f in os.listdir(logging_dir) if f.startswith('test_merid') and f.endswith('.py')]

SKIP_GUARD = (
    'try:\n'
    '    import merid_logging\n'
    '    _MERID_LOGGING_AVAILABLE = True\n'
    'except ImportError:\n'
    '    merid_logging = None  # type: ignore\n'
    '    _MERID_LOGGING_AVAILABLE = False\n'
    '\n'
    'pytestmark = pytest.mark.skipif(\n'
    '    not _MERID_LOGGING_AVAILABLE,\n'
    '    reason="DEBT-LOGGING-001: merid_logging is a stale prototype module not present in the codebase",\n'
    ')\n'
)

for fname in files:
    path = os.path.join(logging_dir, fname)
    with open(path, 'r', encoding='utf-8') as fh:
        content = fh.read()

    if '_MERID_LOGGING_AVAILABLE' in content:
        print(f'ALREADY PATCHED: {fname}')
        continue

    if 'import merid_logging' not in content and 'from merid_logging' not in content:
        print(f'NO_MATCH: {fname}')
        continue

    # Ensure pytest is imported
    if 'import pytest' not in content:
        content = content.replace('import logging\n', 'import logging\nimport pytest\n', 1)

    # Replace bare `import merid_logging` with the guarded version
    content = content.replace('import merid_logging\n', SKIP_GUARD, 1)

    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(content)
    print(f'PATCHED: {fname}')

print('Done.')

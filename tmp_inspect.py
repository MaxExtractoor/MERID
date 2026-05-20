import json

path = r'C:/Users/Chris/.claude/projects/c--Dev-MERID/81425bd3-1fb8-4283-acab-2fb2749635a7/subagents/agent-a35a5b55926a0d7a9.jsonl'
lines = open(path, encoding='utf-8').readlines()
print(f'Total lines: {len(lines)}')

# Print structure of first 3 lines
for i in range(3):
    obj = json.loads(lines[i])
    keys = list(obj.keys())
    print(f'Line {i}: keys={keys}')
    if 'type' in obj:
        print(f'  type={obj["type"]}')
    if 'role' in obj:
        print(f'  role={obj["role"]}')

print('\n--- Last 5 lines ---')
for i, line in enumerate(lines[-5:], len(lines)-5):
    obj = json.loads(line)
    keys = list(obj.keys())
    print(f'Line {i}: keys={keys}')
    if 'type' in obj:
        print(f'  type={obj["type"]}')
    # Check for text content anywhere
    s = json.dumps(obj)
    if len(s) > 200:
        print(f'  content len (json): {len(s)}')
    else:
        print(f'  full: {s[:500]}')

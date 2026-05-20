import json, sys

files = {
    'A_frontend': r'C:/Users/Chris/.claude/projects/c--Dev-MERID/81425bd3-1fb8-4283-acab-2fb2749635a7/subagents/agent-a35a5b55926a0d7a9.jsonl',
    'B_backend_pnl': r'C:/Users/Chris/.claude/projects/c--Dev-MERID/81425bd3-1fb8-4283-acab-2fb2749635a7/subagents/agent-ab5039151951c24b9.jsonl',
    'C_api_endpoints': r'C:/Users/Chris/.claude/projects/c--Dev-MERID/81425bd3-1fb8-4283-acab-2fb2749635a7/subagents/agent-affbca9fb639f1a4a.jsonl',
}

for label, path in files.items():
    print(f'\n\n===== {label} =====')
    try:
        lines = open(path, encoding='utf-8').readlines()
        print(f'  Total lines: {len(lines)}')
        # Find all assistant messages with substantial text
        best = None
        best_len = 0
        for i, line in enumerate(lines):
            try:
                obj = json.loads(line)
                if obj.get('role') == 'assistant':
                    content = obj.get('content', '')
                    text = ''
                    if isinstance(content, list):
                        for c in content:
                            if isinstance(c, dict) and c.get('type') == 'text':
                                text += c.get('text', '')
                    elif isinstance(content, str):
                        text = content
                    if len(text) > best_len:
                        best_len = len(text)
                        best = (i, text)
            except Exception as e:
                pass
        if best:
            idx, text = best
            print(f'  Longest assistant msg at line {idx}, len={len(text)}')
            # Write to separate file
            out_path = f'C:/Dev/MERID/tmp_agent_{label}.txt'
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(text)
            print(f'  Written to {out_path}')
        else:
            print('  No assistant messages found')
    except Exception as e:
        print(f'  ERROR: {e}')

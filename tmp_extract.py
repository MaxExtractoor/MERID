import json

def get_text_from_message(obj):
    """Extract text from the message field of a JSONL entry."""
    msg = obj.get('message', {})
    if isinstance(msg, dict):
        # Could be {role, content} or direct text
        content = msg.get('content', '')
        role = msg.get('role', '')
        if isinstance(content, list):
            text = ''
            for c in content:
                if isinstance(c, dict) and c.get('type') == 'text':
                    text += c.get('text', '')
            return role, text
        elif isinstance(content, str):
            return role, content
    elif isinstance(msg, str):
        return '', msg
    return '', ''

files = {
    'A_frontend': r'C:/Users/Chris/.claude/projects/c--Dev-MERID/81425bd3-1fb8-4283-acab-2fb2749635a7/subagents/agent-a35a5b55926a0d7a9.jsonl',
    'B_backend_pnl': r'C:/Users/Chris/.claude/projects/c--Dev-MERID/81425bd3-1fb8-4283-acab-2fb2749635a7/subagents/agent-ab5039151951c24b9.jsonl',
    'C_api_endpoints': r'C:/Users/Chris/.claude/projects/c--Dev-MERID/81425bd3-1fb8-4283-acab-2fb2749635a7/subagents/agent-affbca9fb639f1a4a.jsonl',
}

for label, path in files.items():
    print(f'\n\n===== {label} =====')
    lines = open(path, encoding='utf-8').readlines()
    print(f'  Total lines: {len(lines)}')

    best = None
    best_len = 0
    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            if obj.get('type') == 'assistant':
                role, text = get_text_from_message(obj)
                if len(text) > best_len:
                    best_len = len(text)
                    best = (i, text)
        except Exception as e:
            pass

    if best:
        idx, text = best
        print(f'  Longest assistant msg at line {idx}, len={len(text)}')
        out_path = f'C:/Dev/MERID/tmp_agent_{label}.txt'
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'  Written to {out_path}')
        # Print first 500 chars
        print(f'  Preview: {text[:300]}')
    else:
        print('  No assistant messages found - checking message structure...')
        # Debug: show message structure of line 154 (last assistant)
        obj = json.loads(lines[-1])
        msg = obj.get('message', {})
        print(f'  message type: {type(msg)}')
        if isinstance(msg, dict):
            print(f'  message keys: {list(msg.keys())}')
            for k, v in msg.items():
                print(f'    {k}: {repr(str(v)[:100])}')

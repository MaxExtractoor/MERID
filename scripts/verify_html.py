with open('c:/Dev/MERID/web/templates/unified.html', 'r', encoding='utf-8') as f:
    content = f.read()
    print('TEST script present:', '[TEST] Page loaded' in content)
    print('institutional.js v=21:', 'institutional.js?v=21' in content)
    print('File size:', len(content))

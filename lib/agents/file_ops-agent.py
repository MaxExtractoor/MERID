import json
import sys
import os

def file_op(params):
  op = params.get('operation')
  file = params.get('file')
  if op == 'read':
    with open(file, 'r') as f:
      return {"content": f.read()}
  elif op == 'write':
    with open(file, 'w') as f:
      f.write(params.get('content', ''))
    return {"status": "written"}
  return {"error": "Invalid op"}

input_data = sys.stdin.read().trim()
if input_data:
  params = json.loads(input_data)
  result = file_op(params)
  print(json.dumps(result))

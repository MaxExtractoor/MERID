import pyautogui
import json
import sys
import time
from datetime import datetime

pyautogui.FAILSAFE = True  # Move mouse to top-left corner to emergency stop

def run_task(task):
  task = task.lower()
  try:
    if "open notepad" in task:
      pyautogui.hotkey('win', 'r')
      time.sleep(0.5)
      pyautogui.write('notepad')
      pyautogui.press('enter')
      time.sleep(1)
      return {"status": "success", "message": "Notepad opened"}

    if "type" in task or "write" in task:
      # Extract text after "type" or "write"
      text = task.split("type", 1)[1] if "type" in task else task.split("write", 1)[1]
      text = text.strip(' .,!')
      pyautogui.write(text)
      return {"status": "success", "message": f"Typed: {text}"}

    if "screenshot" in task or "screen shot" in task:
      filename = f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
      pyautogui.screenshot().save(filename)
      return {"status": "success", "message": f"Screenshot saved as {filename}"}

    if "close window" in task or "close app" in task:
      pyautogui.hotkey('alt', 'f4')
      return {"status": "success", "message": "Closed active window"}

    return {"status": "error", "message": "Task not supported yet"}

  except Exception as e:
    return {"status": "error", "message": str(e)}

# Read from stdin (from router)
input_data = sys.stdin.read().strip()
if input_data:
  try:
    params = json.loads(input_data)
    result = run_task(params.get("task", ""))
    print(json.dumps(result))
  except:
    print(json.dumps({"status": "error", "message": "Invalid input"}))

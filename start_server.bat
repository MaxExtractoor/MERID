@echo off
cd /d c:\Dev\MERID
"C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\Scripts\uvicorn.exe" web.main_15m_lean:app --host 0.0.0.0 --port 8011 > server_output.log 2>&1

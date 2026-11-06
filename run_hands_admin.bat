@echo off
rem Start the program with only the small input helper elevated (voice_mouse_hands, standard library only);
rem speech recognition, the downloaded models and the screen overlay stay as your normal user.
rem If the helper is already running (install_hands_task.bat) it is simply used. Otherwise it is started with
rem the Windows prompt and then keeps running like a server until you close it.
rem Runs with no console; use run_hands_admin_console.bat to see messages. Extra options pass through:
rem     run_hands_admin.bat --corner top-left
cd /d "%~dp0"
where pyw >nul 2>&1
if errorlevel 1 (set "PYEXE=pythonw") else (set "PYEXE=pyw")
start "" %PYEXE% voice_mouse.py --admin-hands %*

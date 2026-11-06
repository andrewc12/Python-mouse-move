@echo off
rem Safer way to reach administrator windows: only the small input helper (voice_mouse_hands.py, standard
rem library only) runs elevated; speech recognition, the downloaded models and the screen overlay stay normal.
rem Double-click, accept the Windows prompt. The program starts with no console; extra options pass through:
rem     run_hands_admin.bat --corner top-left
rem To see messages and errors use run_hands_admin_console.bat.
cd /d "%~dp0"
where pyw >nul 2>&1
if errorlevel 1 (set "PYEXE=pythonw") else (set "PYEXE=pyw")
start "" %PYEXE% voice_mouse.py --admin-hands %*

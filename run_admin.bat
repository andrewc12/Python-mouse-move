@echo off
rem Launch voice_mouse.py as administrator with NO console window.
rem Double-click this file and accept the Windows permission prompt. Messages and errors are not
rem shown (heard.jsonl still logs what was recognised); if it will not start, run
rem run_admin_console.bat instead to see why. Extra options are passed through, for example:
rem     run_admin.bat --corner top-left
cd /d "%~dp0"
where pyw >nul 2>&1
if errorlevel 1 (set "PYEXE=pythonw") else (set "PYEXE=pyw")
start "" %PYEXE% voice_mouse.py --admin %*

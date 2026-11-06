@echo off
rem Start Voice Mouse using the input helper that install_hands_task.bat runs elevated at logon.
rem Only the helper is elevated; this program stays a normal user program. No Windows prompt.
rem Uses dist\voice_mouse.exe (from build.bat) if it exists, else voice_mouse.exe beside this file,
rem else voice_mouse.py with Python (no console window). Extra options pass through, for example:
rem     run_voice_mouse.bat --corner top-left
rem If it says it cannot reach the input helper, run install_hands_task.bat once (as administrator),
rem or sign out and in again so the logon task starts it.
cd /d "%~dp0"
if exist "dist\voice_mouse.exe" goto use_dist
if exist "voice_mouse.exe" goto use_beside
where pyw >nul 2>&1
if errorlevel 1 (set "PYEXE=pythonw") else (set "PYEXE=pyw")
start "" %PYEXE% voice_mouse.py --use-hands %*
goto end
:use_dist
start "" "dist\voice_mouse.exe" --use-hands %*
goto end
:use_beside
start "" "voice_mouse.exe" --use-hands %*
:end

@echo off
rem Same as run_admin.bat but WITH a console window, so you can see messages and errors (use this to debug).
rem Double-click this file. Windows shows its permission prompt; accept it and the program
rem starts in a new elevated window. Any extra options are passed through, for example:
rem     run_admin_console.bat --corner top-left
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (set "PYEXE=python") else (set "PYEXE=py")
%PYEXE% voice_mouse.py --admin %*
if errorlevel 1 (
  echo.
  echo The program stopped with an error. See the message above.
  pause
)

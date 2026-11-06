@echo off
rem Launch voice_mouse.py as administrator (so it can click and type into admin windows).
rem Double-click this file. Windows shows its permission prompt; accept it and the program
rem starts in a new elevated window. Any extra options are passed through, for example:
rem     run_admin.bat --hide-console --corner top-left
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (set "PYEXE=python") else (set "PYEXE=py")
%PYEXE% voice_mouse.py --admin %*
if errorlevel 1 (
  echo.
  echo The program stopped with an error. See the message above.
  pause
)

@echo off
rem Same as run_hands_admin.bat but WITH a console window, so you can see messages and errors.
rem Only voice_mouse_hands.py is elevated (it opens its own small console after the Windows prompt).
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (set "PYEXE=python") else (set "PYEXE=py")
%PYEXE% voice_mouse.py --admin-hands %*
if errorlevel 1 (
  echo.
  echo The program stopped with an error. See the message above.
  pause
)

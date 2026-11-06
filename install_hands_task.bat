@echo off
rem Run the hands (voice_mouse_hands) as a server that starts ELEVATED at every logon, with no Windows prompt.
rem This is the plain version (no UI access, so the grid cannot draw above the top window layer). For the full
rem version use install_hands_signed.bat instead. Right-click this file -> Run as administrator, once.
rem Why a scheduled task and not a Windows service: a service has no access to your desktop, so it could not
rem click or type for you. The task uses no time limit and restarts the hands if they ever stop.
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator rights. Right-click the file and choose "Run as administrator".
  pause & exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_hands.ps1"
if errorlevel 1 (echo. & echo Failed. See the message above. & pause & exit /b 1)
pause

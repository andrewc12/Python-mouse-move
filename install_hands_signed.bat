@echo off
rem Give the hands UI ACCESS, the accessibility privilege that lets the grid and status box draw above
rem every other window (including always-on-top and administrator windows) and lets the hands click and
rem type into administrator windows. Run build.bat first. Right-click this file -> Run as administrator, once
rem (and again after each rebuild of the hands).
rem What it does: makes a certificate that only this PC trusts, signs the hands with it, copies them to
rem C:\Program Files\VoiceMouse\hands (Windows only allows UI access from there) and adds a Startup shortcut.
rem It cannot cover the Windows lock screen, UAC prompts or exclusive full-screen games: nobody can.
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator rights. Right-click the file and choose "Run as administrator".
  pause & exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_hands.ps1" -Signed
if errorlevel 1 (echo. & echo Failed. See the message above. & pause & exit /b 1)
pause

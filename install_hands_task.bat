@echo off
rem Make the input helper (voice_mouse_hands) run as a server: start it elevated at every logon, with no
rem Windows prompt, and keep it running. Right-click this file -> Run as administrator, once.
rem Uses dist\voice_mouse_hands.exe (from build.bat) if it exists, else voice_mouse_hands.exe beside this file,
rem else voice_mouse_hands.py with Python.
rem Why a scheduled task and not a Windows service: a service runs in a separate session with no access to your
rem desktop, so it cannot click or type for you. A task set to "run with highest privileges" runs in YOUR
rem session, elevated, which is what the hands need.
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator rights. Right-click the file and choose "Run as administrator".
  pause & exit /b 1
)
set "TASK=VoiceMouseHands"
if exist "dist\voice_mouse_hands.exe" goto use_dist
if exist "voice_mouse_hands.exe" goto use_beside
where pyw >nul 2>&1
if errorlevel 1 (set "PYEXE=pythonw") else (set "PYEXE=pyw")
set "RUN=%PYEXE% \"%~dp0voice_mouse_hands.py\""
goto create
:use_dist
set "RUN=\"%~dp0dist\voice_mouse_hands.exe\""
goto create
:use_beside
set "RUN=\"%~dp0voice_mouse_hands.exe\""
:create
schtasks /Create /TN "%TASK%" /TR "%RUN%" /SC ONLOGON /RL HIGHEST /F
if errorlevel 1 (echo Could not create the task. & pause & exit /b 1)
schtasks /Run /TN "%TASK%" >nul
echo.
echo Installed and started. The hands now run elevated whenever you are logged in.
echo Their log is %%LOCALAPPDATA%%\voice_mouse\hands.log
echo Start the program with:   voice_mouse.exe --use-hands
echo Stop or remove it with:   uninstall_hands_task.bat
pause

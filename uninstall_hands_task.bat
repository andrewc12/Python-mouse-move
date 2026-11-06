@echo off
rem Stop the hands and remove everything the install scripts added. Right-click -> Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator rights. Right-click the file and choose "Run as administrator".
  pause & exit /b 1
)
schtasks /End /TN "VoiceMouseHands" >nul 2>&1
schtasks /Delete /TN "VoiceMouseHands" /F >nul 2>&1
taskkill /im voice_mouse_hands.exe /f >nul 2>&1
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Voice Mouse hands.lnk" >nul 2>&1
if exist "%ProgramFiles%\VoiceMouse" rmdir /s /q "%ProgramFiles%\VoiceMouse"
echo Removed the task, the Startup shortcut and %ProgramFiles%\VoiceMouse.
echo The local certificate "Voice Mouse (local certificate)" is still trusted on this PC. To remove it, open
echo certlm.msc and delete it from Personal, Trusted Root Certification Authorities and Trusted Publishers.
pause

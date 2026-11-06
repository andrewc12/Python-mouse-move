@echo off
rem Stop the input helper and remove its logon task. Right-click -> Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator rights. Right-click the file and choose "Run as administrator".
  pause & exit /b 1
)
schtasks /End /TN "VoiceMouseHands" >nul 2>&1
schtasks /Delete /TN "VoiceMouseHands" /F
taskkill /im voice_mouse_hands.exe /f >nul 2>&1
echo Done.
pause

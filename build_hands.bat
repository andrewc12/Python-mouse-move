@echo off
rem Build the small input helper as its own exe. It needs no packages (standard library only), so the
rem elevated exe contains no speech or model code. Put it next to voice_mouse.exe; "--admin-hands" finds it.
rem First time only:   py -m pip install nuitka ordered-set zstandard
py -m nuitka ^
  --standalone ^
  --assume-yes-for-downloads ^
  --windows-console-mode=force ^
  --output-dir=build ^
  voice_mouse_hands.py
if errorlevel 1 (echo Build failed & exit /b 1)
echo.
echo Built: build\voice_mouse_hands.dist\voice_mouse_hands.exe
echo Copy that whole folder's contents next to voice_mouse.exe (or just use --standalone for both into one folder).
rem Add --onefile for a single small exe. Add --windows-uac-admin to make it always ask for administrator rights.

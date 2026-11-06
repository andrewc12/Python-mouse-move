@echo off
rem Build voice_mouse.exe with Nuitka. Run from this folder. First time only:
rem     py -m pip install nuitka ordered-set zstandard vosk sounddevice
rem A C compiler is needed: Nuitka offers to download MinGW64 automatically on first run (say yes),
rem or install Visual Studio Build Tools instead.
py -m nuitka ^
  --standalone ^
  --enable-plugin=tk-inter ^
  --include-package=vosk ^
  --include-package-data=vosk ^
  --include-package-data=_sounddevice_data ^
  --assume-yes-for-downloads ^
  --windows-console-mode=force ^
  --output-dir=build ^
  voice_mouse.py
if errorlevel 1 (echo Build failed & exit /b 1)
echo.
echo Built: build\voice_mouse.dist\voice_mouse.exe
echo Copy your "models" folder (vosk-model-small-en-us-0.15) next to the exe to skip the download.
rem Add --windows-console-mode=disable to hide the console window (then you lose the printed log).
rem Add --onefile for a single exe (slower start-up: it unpacks to a temp folder each run).
rem Add --windows-uac-admin to make the exe always ask for administrator rights (so it can click admin windows).

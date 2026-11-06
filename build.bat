@echo off
rem Build Voice Mouse as TWO programs, one after the other:
rem   part 1  dist\hands\voice_mouse_hands.exe   the small helper: clicks, keys, typing AND the grid / status box
rem            drawing. Standard library only. Built as a folder (not one file) with a "UI access" manifest:
rem            a UI-access program must be signed and run from Program Files, and a one-file exe unpacks
rem            itself into a temp folder, which Windows refuses. install_hands_signed.bat does the signing/installing.
rem   part 2  dist\voice_mouse.exe                speech recognition and dictation logic (single file).
rem NO model is packed into either exe. Models live in one shared folder (default
rem %LOCALAPPDATA%\voice_mouse\models, or set VOICE_MOUSE_MODELS) and are downloaded once with
rem     dist\voice_mouse.exe --download-models
rem so every rebuild, copy or version reuses the same download.
rem
rem Usage:   build.bat            build both
rem          build.bat hands      only part 1
rem          build.bat main       only part 2
rem First time only:
rem     py -m pip install nuitka ordered-set zstandard
rem     py -m pip install -r requirements.txt          (part 2 only: vosk, sounddevice, sherpa-onnx, ...)
rem A C compiler is needed: Nuitka offers to download MinGW64 the first time (say yes).
rem
rem Settings (edit here):
set "HANDS_CONSOLE=disable"
set "MAIN_CONSOLE=force"
set "HANDS_UIACCESS=--windows-uac-uiaccess"
set "HANDS_ADMIN_MANIFEST="
rem   HANDS_CONSOLE / MAIN_CONSOLE: force = show a console, disable = no console (the hands write hands.log,
rem   the main program writes voice_mouse.log).
rem   HANDS_UIACCESS: the accessibility flag that lets the hands draw above every other window and drive
rem   elevated windows (see install_hands_signed.bat). Empty it to build an ordinary exe.
rem   HANDS_ADMIN_MANIFEST: set to --windows-uac-admin to ALSO run the hands as full administrator
rem   (a Windows prompt at every start). Usually not needed: UI access already reaches administrator windows.

cd /d "%~dp0"
set "WHAT=%~1"
if "%WHAT%"=="" set "WHAT=all"
if not exist dist mkdir dist

if /i "%WHAT%"=="main" goto part2

:part1
echo.
echo === Part 1 of 2: hands (folder dist\hands) ===
py -m nuitka ^
  --standalone ^
  --enable-plugin=tk-inter ^
  --include-module=voice_mouse_ui ^
  --assume-yes-for-downloads ^
  --windows-console-mode=%HANDS_CONSOLE% ^
  %HANDS_UIACCESS% ^
  %HANDS_ADMIN_MANIFEST% ^
  --output-dir=build ^
  voice_mouse_hands.py
if errorlevel 1 (echo Part 1 failed & exit /b 1)
robocopy build\voice_mouse_hands.dist dist\hands /MIR /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (echo Could not copy the hands build into dist\hands & exit /b 1)
if /i "%WHAT%"=="hands" goto done

:part2
echo.
echo === Part 2 of 2: voice_mouse.exe ===
py -m nuitka ^
  --onefile ^
  --onefile-tempdir-spec="{CACHE_DIR}/voice_mouse" ^
  --enable-plugin=tk-inter ^
  --include-package=vosk ^
  --include-package-data=vosk ^
  --include-package-data=_sounddevice_data ^
  --include-package=sherpa_onnx ^
  --include-package-data=sherpa_onnx ^
  --assume-yes-for-downloads ^
  --windows-console-mode=%MAIN_CONSOLE% ^
  --output-dir=build ^
  --output-filename=voice_mouse.exe ^
  voice_mouse.py
if errorlevel 1 (echo Part 2 failed & exit /b 1)
copy /y build\voice_mouse.exe dist\voice_mouse.exe >nul

:done
echo.
echo Built into dist\ :
dir /b dist\*.exe
dir /b dist\hands\voice_mouse_hands.exe
echo.
echo Next:
echo   1. dist\voice_mouse.exe --download-models        (once; shared by every build)
echo   2. install_hands_signed.bat  (once, as administrator: signs the hands, installs them under Program Files, starts them at logon)
echo   3. run_voice_mouse.bat
rem The {CACHE_DIR} spec makes the onefile exe unpack once and reuse that copy, so later starts are fast.
rem voice_mouse.py imports voice_mouse_hands.py for its key tables, so part 2 contains that code too, but only
rem part 1 ever gets extra privileges. The main program finds the hands at %ProgramFiles%\VoiceMouse\hands first,
rem then in a "hands" folder or beside itself.
